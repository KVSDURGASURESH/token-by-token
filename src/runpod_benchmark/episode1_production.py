"""Fail-closed production composition for an authorized Episode 1 run.

This module performs no provider operation on import.  It verifies that the
plan projects the policy-derived bytes, verifies the external authorization,
and only then imports the selected provider adapter.
"""

from __future__ import annotations

import importlib.metadata
import hashlib
import json
import math
import platform
import re
import sys
import tomllib
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .episode1_application import ExecutionResult, RunContext, execute_episode1
from .episode1_material_closure import (
    MaterialClosureProfile,
    compile_material_closure,
    read_material_bytes,
    verify_exact_material_manifest,
)


class ProductionCompositionError(ValueError):
    """The selected production inputs or adapter are not a closed execution."""


# The retained client contract fixes these reviewed roots.  The uv lock, rather
# than a caller-supplied list, expands them to every required active dependency.
# Unrelated installed distributions are outside this execution-closure policy.
_CLIENT_DISTRIBUTIONS = {"jsonschema", "packaging", "transformers", "zstandard"}
_IMAGE_ATTESTATION_KEYS = {
    "schema_version", "classification", "build_manifest_sha256",
    "image_manifest_digest", "config_digest", "layer_digests",
    "oci_archive_sha256", "final_filesystem_sha256",
    "local_build_receipt_sha256", "resource_bounds", "cpu_report_sha256",
    "attestation_digests", "cpu_report", "gpu_validation",
    "registry_publication",
}
_CPU_REPORT_KEYS = {
    "schema_version", "status", "manifest_sha256", "platform",
    "python_version", "materials", "system_inventory", "dependencies",
    "host_keys_present", "gpu_validation",
}
_DEPENDENCY_REPORT_KEYS = {
    "schema_version", "status", "runtime", "lock_sha256",
    "lock_package_count", "installed_package_count", "bootstrap_allowlist",
    "inventory", "active_dependency_checks", "allowed_dependency_mismatches",
    "errors", "python_version", "platform", "bootstrap_manifest_sha256",
}


PRODUCTION_TELEMETRY_SERIES = (
    "native-active-requests",
    "native-waiting-requests",
    "native-kv-occupancy",
    "native-queue-seconds-sum",
    "native-prefill-work",
    "native-decode-work",
    "system-gpu-utilization",
    "system-gpu-memory-used",
    "system-gpu-memory-total",
    "system-gpu-power",
    "system-gpu-temperature",
    "system-process-cpu-ticks",
    "system-process-cpu-clock-hz",
    "system-process-rss",
    "system-process-read",
    "system-process-write",
    "system-host-cpu-total",
    "system-host-cpu-busy",
    "system-host-cpu-logical-count",
    "system-host-memory-total",
    "system-host-memory-available",
    "system-host-network-rx",
    "system-host-network-tx",
)


def _strict_json_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProductionCompositionError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise ProductionCompositionError(f"{label} must be an object")
    return value


def _canonical_distribution_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name) is None
    ):
        raise ProductionCompositionError("client distribution identity is invalid")
    return re.sub(r"[-_.]+", "-", name).lower()


def _selected_lock_closure(lock_raw: bytes) -> dict[str, str]:
    """Resolve the fixed client roots through active uv-lock dependency edges."""
    try:
        lock = tomllib.loads(lock_raw.decode("utf-8", errors="strict"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ProductionCompositionError("client dependency lock is invalid") from exc
    if (
        not isinstance(lock, dict)
        or lock.get("version") != 1
        or lock.get("revision") != 3
        or not isinstance(lock.get("requires-python"), str)
        or not isinstance(lock.get("package"), list)
    ):
        raise ProductionCompositionError("client dependency lock is unsupported")
    try:
        from packaging.markers import InvalidMarker, Marker, default_environment
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.version import InvalidVersion, Version
    except (ImportError, ModuleNotFoundError) as exc:
        raise ProductionCompositionError("marker evaluator is absent") from exc
    try:
        if Version(platform.python_version()) not in SpecifierSet(lock["requires-python"]):
            raise ProductionCompositionError("executing Python is outside the client lock")
    except (InvalidSpecifier, InvalidVersion) as exc:
        raise ProductionCompositionError("client dependency Python policy is invalid") from exc
    packages: dict[str, Mapping[str, Any]] = {}
    for package in lock["package"]:
        if not isinstance(package, Mapping):
            raise ProductionCompositionError("client dependency lock package is invalid")
        name = _canonical_distribution_name(package.get("name"))
        version = package.get("version")
        dependencies = package.get("dependencies", [])
        if (
            name in packages
            or not isinstance(version, str)
            or not version
            or not isinstance(dependencies, list)
        ):
            raise ProductionCompositionError("client dependency lock package is ambiguous")
        packages[name] = package
    environment = default_environment()
    pending = sorted(_CLIENT_DISTRIBUTIONS)
    selected: dict[str, str] = {}
    while pending:
        name = _canonical_distribution_name(pending.pop())
        if name in selected:
            continue
        package = packages.get(name)
        if package is None:
            raise ProductionCompositionError("client dependency lock closure is incomplete")
        selected[name] = package["version"]
        for dependency in package.get("dependencies", []):
            if not isinstance(dependency, Mapping) or not isinstance(dependency.get("name"), str):
                raise ProductionCompositionError("client dependency lock edge is invalid")
            marker = dependency.get("marker")
            if marker is not None and not isinstance(marker, str):
                raise ProductionCompositionError("client dependency marker is invalid")
            try:
                active = marker is None or Marker(marker).evaluate(environment)
            except (InvalidMarker, ValueError, KeyError) as exc:
                raise ProductionCompositionError("client dependency marker is invalid") from exc
            if active:
                pending.append(dependency["name"])
    return selected


def _verify_client_environment(raw: bytes, lock_raw: bytes) -> None:
    value = _strict_json_object(raw, "client environment contract")
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "python_implementation", "python_version", "distributions"
    } or value["schema_version"] != "episode1.client-environment.v1":
        raise ProductionCompositionError("client environment contract is open or incomplete")
    observed_python = ".".join(str(item) for item in sys.version_info[:3])
    if value["python_implementation"] != platform.python_implementation() or value["python_version"] != observed_python:
        raise ProductionCompositionError("executing Python differs from the selected client environment")
    distributions = value["distributions"]
    if not isinstance(distributions, Mapping) or set(distributions) != _CLIENT_DISTRIBUTIONS:
        raise ProductionCompositionError("client distribution contract is incomplete")
    for name, expected in distributions.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise ProductionCompositionError("client distribution contract is invalid")
    required = _selected_lock_closure(lock_raw)
    declared = {_canonical_distribution_name(name): version for name, version in distributions.items()}
    if any(required.get(name) != version for name, version in declared.items()):
        raise ProductionCompositionError("client distribution contract differs from dependency lock")
    for name, expected in sorted(required.items()):
        try:
            observed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ProductionCompositionError("selected client distribution is absent") from exc
        if observed != expected:
            raise ProductionCompositionError("selected client distribution version differs")


def _bare_sha(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _oci_sha(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and _bare_sha(value[7:])


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductionCompositionError("build attestation contains invalid JSON values") from exc


def _runtime_lock_inventory(raw: bytes) -> list[dict[str, str]]:
    """Derive the installed inventory required by a retained hashed pip lock."""
    try:
        text = raw.decode("utf-8", errors="strict")
        from packaging.version import InvalidVersion, Version
    except (UnicodeError, ImportError, ModuleNotFoundError) as exc:
        raise ProductionCompositionError("selected runtime lock is invalid") from exc
    packages: dict[str, dict[str, Any]] = {}
    current: str | None = None
    binary_only = False
    index_seen = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "--only-binary :all:":
            if current is not None:
                raise ProductionCompositionError("selected runtime lock is invalid")
            binary_only = True
            continue
        if stripped.startswith(("--index-url ", "--extra-index-url ")):
            if current is not None:
                raise ProductionCompositionError("selected runtime lock is invalid")
            url = stripped.split(None, 1)[1]
            parsed = urllib.parse.urlsplit(url)
            if (
                parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
            ):
                raise ProductionCompositionError("selected runtime lock index is invalid")
            index_seen = True
            continue
        package_match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*\\", stripped
        )
        if package_match:
            name = _canonical_distribution_name(package_match.group(1))
            if name in packages:
                raise ProductionCompositionError("selected runtime lock is ambiguous")
            try:
                version = str(Version(package_match.group(2)))
            except InvalidVersion as exc:
                raise ProductionCompositionError("selected runtime lock is invalid") from exc
            packages[name] = {"version": version, "hashes": set()}
            current = name
            continue
        hash_match = re.fullmatch(r"--hash=sha256:([0-9a-f]{64})(?:\s*\\)?", stripped)
        if current is not None and hash_match:
            packages[current]["hashes"].add(hash_match.group(1))
            continue
        raise ProductionCompositionError("selected runtime lock is invalid")
    if (
        not binary_only or not index_seen or not packages
        or any(not package["hashes"] for package in packages.values())
    ):
        raise ProductionCompositionError("selected runtime lock is incomplete")
    return [
        {"name": name, "version": package["version"]}
        for name, package in sorted(packages.items())
    ]


def _verify_cpu_report(
    report: Any, build_manifest: Mapping[str, Any], build_manifest_sha256: str,
    runtime_lock_bytes: Mapping[str, bytes],
) -> None:
    if not isinstance(report, Mapping) or set(report) != _CPU_REPORT_KEYS:
        raise ProductionCompositionError("CPU build report is open or incomplete")
    if (
        report["schema_version"] != "episode1.cpu-smoke.v1"
        or report["status"] != "pass"
        or report["manifest_sha256"] != build_manifest_sha256
        or report["platform"] != "linux/amd64"
        or report["host_keys_present"] is not False
        or report["gpu_validation"] != "not_run"
        or not isinstance(report["python_version"], str)
        or re.fullmatch(r"3\.12\.[0-9]+", report["python_version"]) is None
        or report["materials"] != build_manifest.get("materials")
    ):
        raise ProductionCompositionError("CPU build report is not bound to selected materials")
    inventory = report["system_inventory"]
    if not isinstance(inventory, list):
        raise ProductionCompositionError("CPU system inventory is invalid")
    observed_identities: set[tuple[str, str]] = set()
    for package in inventory:
        if (
            not isinstance(package, Mapping)
            or set(package) != {"name", "version", "architecture"}
            or not all(isinstance(value, str) and value for value in package.values())
        ):
            raise ProductionCompositionError("CPU system inventory is invalid")
        identity = (package["name"], package["architecture"])
        if identity in observed_identities:
            raise ProductionCompositionError("CPU system inventory is ambiguous")
        observed_identities.add(identity)
    expected_packages = build_manifest.get("system_packages")
    if not isinstance(expected_packages, list) or any(
        not isinstance(package, Mapping)
        or {key: package.get(key) for key in ("name", "version", "architecture")}
        not in inventory
        for package in expected_packages
    ):
        raise ProductionCompositionError("CPU system inventory differs from build manifest")
    runtimes = build_manifest.get("runtimes")
    dependencies = report["dependencies"]
    if not isinstance(runtimes, list) or not isinstance(dependencies, list) or len(dependencies) != 2:
        raise ProductionCompositionError("CPU dependency reports are incomplete")
    selected_locks: dict[str, tuple[str, list[dict[str, str]]]] = {}
    for runtime in runtimes:
        if not isinstance(runtime, Mapping):
            raise ProductionCompositionError("selected runtime lock set is invalid")
        name = runtime.get("runtime")
        lock_path = runtime.get("lock_path")
        lock_sha256 = runtime.get("lock_sha256")
        if (
            name in selected_locks or name not in {"vllm", "sglang"}
            or not isinstance(lock_path, str) or not isinstance(lock_sha256, str)
            or lock_path not in runtime_lock_bytes
            or hashlib.sha256(runtime_lock_bytes[lock_path]).hexdigest() != lock_sha256
        ):
            raise ProductionCompositionError("selected runtime lock set is invalid")
        selected_locks[name] = (
            lock_sha256, _runtime_lock_inventory(runtime_lock_bytes[lock_path])
        )
    if set(selected_locks) != {"vllm", "sglang"}:
        raise ProductionCompositionError("selected runtime lock set is invalid")
    seen: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, Mapping) or set(dependency) != _DEPENDENCY_REPORT_KEYS:
            raise ProductionCompositionError("CPU dependency report is open or incomplete")
        runtime = dependency.get("runtime")
        if (
            runtime in seen
            or runtime not in selected_locks
            or dependency.get("schema_version") != "episode1.dependency-validation.v1"
            or dependency.get("status") != "pass"
            or dependency.get("lock_sha256") != selected_locks[runtime][0]
            or dependency.get("errors") != []
            or dependency.get("bootstrap_allowlist") != []
            or dependency.get("bootstrap_manifest_sha256") is not None
            or dependency.get("platform") != "linux-x86_64"
            or dependency.get("python_version") != report["python_version"]
            or type(dependency.get("active_dependency_checks")) is not int
            or dependency["active_dependency_checks"] <= 0
            or type(dependency.get("lock_package_count")) is not int
            or type(dependency.get("installed_package_count")) is not int
            or not isinstance(dependency.get("inventory"), list)
            or dependency["inventory"] != selected_locks[runtime][1]
            or dependency["lock_package_count"] != len(selected_locks[runtime][1])
            or dependency["installed_package_count"] != len(selected_locks[runtime][1])
        ):
            raise ProductionCompositionError("CPU dependency report differs from selected runtime")
        expected_mismatches = (
            [] if runtime == "vllm" else [{
                "package": "torch", "dependency": "nvidia-nccl-cu13",
                "required": "==2.29.7", "marker": 'sys_platform == "linux"',
                "installed": "2.30.7",
            }]
        )
        if dependency.get("allowed_dependency_mismatches") != expected_mismatches:
            raise ProductionCompositionError("CPU dependency exception differs from build policy")
        seen.add(runtime)


def _verify_image_attestation(
    plan: Mapping[str, Any], raw: bytes, *, build_manifest: Mapping[str, Any],
    build_manifest_sha256: str, expected_resource_bounds: Mapping[str, Any],
    runtime_lock_bytes: Mapping[str, bytes],
) -> None:
    attestation = _strict_json_object(raw, "build attestation")
    if set(attestation) != _IMAGE_ATTESTATION_KEYS:
        raise ProductionCompositionError("build attestation is open or incomplete")
    if (
        attestation["schema_version"] != "episode1.image-attestation.v2"
        or attestation["classification"] != "cpu_build_evidence"
        or hashlib.sha256(_canonical_json_bytes(build_manifest)).hexdigest() != build_manifest_sha256
        or attestation["build_manifest_sha256"] != build_manifest_sha256
        or attestation["resource_bounds"] != expected_resource_bounds
        or not _bare_sha(attestation["local_build_receipt_sha256"])
        or attestation["gpu_validation"] != "not_run"
        or attestation["registry_publication"] != "not_performed"
    ):
        raise ProductionCompositionError("build attestation is not selected CPU build evidence")
    for key in (
        "oci_archive_sha256", "final_filesystem_sha256", "cpu_report_sha256"
    ):
        if not _bare_sha(attestation[key]):
            raise ProductionCompositionError("build attestation digest is invalid")
    if not _oci_sha(attestation["config_digest"]):
        raise ProductionCompositionError("build attestation config digest is invalid")
    layers = attestation["layer_digests"]
    if (
        not isinstance(layers, list) or not layers
        or not all(_oci_sha(item) for item in layers)
    ):
        raise ProductionCompositionError("build attestation layer set is invalid")
    predicate_digests = attestation["attestation_digests"]
    if (
        not isinstance(predicate_digests, Mapping)
        or set(predicate_digests) != {
            "https://slsa.dev/provenance/v0.2", "https://spdx.dev/Document"
        }
        or not all(_oci_sha(value) for value in predicate_digests.values())
    ):
        raise ProductionCompositionError("build provenance attestations are incomplete")
    _verify_cpu_report(
        attestation["cpu_report"], build_manifest, build_manifest_sha256,
        runtime_lock_bytes,
    )
    if hashlib.sha256(_canonical_json_bytes(attestation["cpu_report"])).hexdigest() != attestation["cpu_report_sha256"]:
        raise ProductionCompositionError("CPU report digest differs from embedded report bytes")
    attested = attestation.get("image_manifest_digest")
    builds = plan.get("runtime_builds")
    if not isinstance(builds, list) or len(builds) != 2:
        raise ProductionCompositionError("plan runtime build projection is incomplete")
    planned = {build.get("derived_image_digest") for build in builds if isinstance(build, Mapping)}
    if (
        len(planned) != 1
        or None in planned
        or not _oci_sha(attested)
        or attested not in planned
    ):
        raise ProductionCompositionError("plan image digest is not bound to the build attestation")


def _verify_prompt_evidence(
    raw: bytes, supplied: Mapping[str, Any]
) -> Mapping[str, Any]:
    retained = _strict_json_object(raw, "prompt evidence")
    if retained != supplied:
        raise ProductionCompositionError("prompt evidence differs from retained material bytes")
    return retained


def verify_plan_digest_projection(
    plan: Mapping[str, Any], derived: Mapping[str, Any]
) -> None:
    """Require every byte-derived execution digest to match the compiled plan."""
    required = {
        "material_sha256", "build_spec_sha256", "dependency_lock_sha256",
        "launcher_sha256", "build_attestation_sha256", "collector_sha256",
        "private_schema_sha256",
    }
    if set(derived) != required:
        raise ProductionCompositionError("derived plan digest projection is open or incomplete")
    if plan.get("material_sha256") != derived["material_sha256"]:
        raise ProductionCompositionError("plan material digest is not byte-derived")
    builds = plan.get("runtime_builds")
    if not isinstance(builds, list) or len(builds) != 2:
        raise ProductionCompositionError("plan runtime build projection is incomplete")
    seen: set[str] = set()
    for build in builds:
        if not isinstance(build, Mapping):
            raise ProductionCompositionError("plan runtime build projection is invalid")
        runtime = str(build.get("runtime", ""))
        family = runtime.split("-", 1)[0]
        if family not in {"vllm", "sglang"} or family in seen:
            raise ProductionCompositionError("plan runtime build identity is invalid")
        seen.add(family)
        expected = {
            "build_spec_sha256": derived["build_spec_sha256"],
            "dependency_lock_sha256": derived["dependency_lock_sha256"].get(family),
            "launcher_sha256": derived["launcher_sha256"],
            "build_attestation_sha256": derived["build_attestation_sha256"],
        }
        if any(build.get(key) != value for key, value in expected.items()):
            raise ProductionCompositionError(
                f"plan runtime build digests are not byte-derived for {family}"
            )
    capture = plan.get("capture")
    if not isinstance(capture, Mapping) or (
        capture.get("collector_sha256") != derived["collector_sha256"]
        or capture.get("private_schema_sha256") != derived["private_schema_sha256"]
    ):
        raise ProductionCompositionError("plan capture digests are not byte-derived")


@dataclass(frozen=True)
class PreparedProductionExecution:
    context: RunContext
    repository_root: Path
    provider_adapter_path: str
    provider_adapter_bytes: bytes
    prompt_evidence: Mapping[str, Any]
    closure_receipt: Mapping[str, Any]


def prepare_production_execution(
    *,
    repository_root: Path,
    profile: MaterialClosureProfile,
    build_manifest: Mapping[str, Any],
    explicit_inputs: Mapping[str, str],
    dockerfile_builder: Callable[[Mapping[str, Any], str], bytes],
    supplied_material_manifest: Mapping[str, Any],
    material_file_bytes: bytes,
    plan: Mapping[str, Any],
    authorization_receipt: Mapping[str, Any],
    plan_file_bytes: bytes,
    authorization_source_bytes: bytes,
    observed_source_commit: str,
    prompt_evidence: Mapping[str, Any],
    unique_name: str,
    telemetry_series: Sequence[str],
    build_manifest_sha256: str,
    build_resource_bounds: Mapping[str, Any],
    **context_options: Any,
) -> PreparedProductionExecution:
    """Complete every pure gate before adapter code can be imported."""
    root = repository_root.resolve(strict=True)
    compiled = compile_material_closure(
        root, profile, build_manifest, explicit_inputs,
        dockerfile_builder=dockerfile_builder,
    )
    verify_exact_material_manifest(compiled, supplied_material_manifest)
    verify_plan_digest_projection(plan, compiled["derived_plan_digests"])
    material_files = read_material_bytes(root, compiled["material_manifest"])
    _verify_client_environment(
        material_files["runtime/episode1/client-environment.json"],
        material_files["uv.lock"],
    )
    prompt_path = str(explicit_inputs["prompt_evidence"])
    retained_prompt = _verify_prompt_evidence(material_files[prompt_path], prompt_evidence)
    _verify_image_attestation(
        plan, material_files[str(explicit_inputs["build_attestation"])],
        build_manifest=build_manifest,
        build_manifest_sha256=build_manifest_sha256,
        expected_resource_bounds=build_resource_bounds,
        runtime_lock_bytes=material_files,
    )
    if tuple(telemetry_series) != PRODUCTION_TELEMETRY_SERIES:
        raise ProductionCompositionError("production telemetry selection is not the fixed contract")
    context = RunContext.create(
        plan=plan,
        authorization_receipt=authorization_receipt,
        plan_file_bytes=plan_file_bytes,
        material_file_bytes=material_file_bytes,
        material_files=material_files,
        observed_source_commit=observed_source_commit,
        authorization_source_bytes=authorization_source_bytes,
        unique_name=unique_name,
        telemetry_series=telemetry_series,
        **context_options,
    )
    return PreparedProductionExecution(
        context=context,
        repository_root=root,
        provider_adapter_path=str(explicit_inputs["provider_adapter"]),
        provider_adapter_bytes=material_files[str(explicit_inputs["provider_adapter"])],
        prompt_evidence=retained_prompt,
        closure_receipt=compiled["closure_receipt"],
    )


_COMPONENT_KEYS = {
    "provider", "guard", "runtime_factory", "cell_factory", "telemetry_factory",
    "primary_watchdog_sha256", "secondary_watchdog_sha256", "monitor_poll_seconds",
}


def _load_adapter(prepared: PreparedProductionExecution) -> ModuleType:
    name = "_episode1_bound_provider_adapter"
    module = ModuleType(name)
    module.__file__ = str(prepared.repository_root / prepared.provider_adapter_path)
    sys.modules[name] = module
    try:
        code = compile(
            prepared.provider_adapter_bytes,
            module.__file__,
            "exec",
            dont_inherit=True,
        )
        exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def execute_prepared_production(
    prepared: PreparedProductionExecution, *, private_evidence_directory: Path
) -> ExecutionResult:
    """Import the bound adapter and execute only after successful preparation."""
    module = _load_adapter(prepared)
    factory = getattr(module, "build_episode1_components", None)
    if not callable(factory):
        raise ProductionCompositionError("provider adapter lacks build_episode1_components")
    components = factory(
        context=prepared.context,
        prompt_evidence=prepared.prompt_evidence,
        private_evidence_directory=private_evidence_directory,
    )
    provider = components.get("provider") if isinstance(components, Mapping) else None
    failure: BaseException | None = None
    try:
        if not isinstance(components, Mapping) or set(components) != _COMPONENT_KEYS:
            raise ProductionCompositionError("provider adapter component set is open or incomplete")
        for key in ("runtime_factory", "cell_factory", "telemetry_factory"):
            if not callable(components[key]):
                raise ProductionCompositionError(f"provider adapter {key} is not callable")
        for key in ("primary_watchdog_sha256", "secondary_watchdog_sha256"):
            value = components[key]
            if value is not None and (
                not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ProductionCompositionError(f"provider adapter {key} is invalid")
        poll = components["monitor_poll_seconds"]
        if (
            isinstance(poll, bool) or not isinstance(poll, (int, float))
            or not math.isfinite(float(poll)) or poll <= 0
        ):
            raise ProductionCompositionError("provider adapter monitor poll is invalid")
        return execute_episode1(
            context=prepared.context,
            private_evidence_directory=private_evidence_directory,
            provider=provider,
            guard=components["guard"],
            runtime_factory=components["runtime_factory"],
            cell_factory=components["cell_factory"],
            telemetry_factory=components["telemetry_factory"],
            primary_watchdog_sha256=components["primary_watchdog_sha256"],
            secondary_watchdog_sha256=components["secondary_watchdog_sha256"],
            monitor_poll_seconds=float(poll),
        )
    except BaseException as exc:
        failure = exc
        raise
    finally:
        close = getattr(provider, "close", None)
        if not callable(close):
            if failure is None:
                raise ProductionCompositionError(
                    "provider adapter lacks bounded transport close"
                )
        else:
            closed = close()
            if closed is not True and failure is None:
                raise ProductionCompositionError(
                    "provider transport broker was not reaped"
                )
