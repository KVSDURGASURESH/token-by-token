"""Policy-derived Episode 1 execution-material closure.

The caller may select concrete, reviewed inputs, but may not substitute digest
strings for their bytes.  The resulting material manifest remains the v1
``{path, sha256}`` format consumed by the authorization verifier.  The receipt
is deliberately outside the material aggregate, avoiding a self-hash cycle.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .episode1 import canonical_json


class MaterialClosureError(ValueError):
    """The selected execution inputs do not form the required closed set."""


@dataclass(frozen=True)
class MaterialClosureProfile:
    schema_version: str
    python_roots: tuple[str, ...]
    fixed_files: tuple[str, ...]
    collector_roots: tuple[str, ...]
    launcher_path: str
    private_schema_path: str

    def checked(self) -> "MaterialClosureProfile":
        if self.schema_version != "episode1.material-closure-profile.v1":
            raise MaterialClosureError("unsupported material closure profile")
        for label, values in (
            ("python roots", self.python_roots),
            ("fixed files", self.fixed_files),
            ("collector roots", self.collector_roots),
        ):
            if not values or len(values) != len(set(values)):
                raise MaterialClosureError(f"{label} must be nonempty and unique")
            for value in values:
                _relative(value)
        _relative(self.launcher_path)
        _relative(self.private_schema_path)
        if self.launcher_path not in self.fixed_files or self.private_schema_path not in self.fixed_files:
            raise MaterialClosureError("launcher and private schema must be fixed materials")
        return self


PRODUCTION_PROFILE = MaterialClosureProfile(
    schema_version="episode1.material-closure-profile.v1",
    python_roots=(
        "scripts/execute_episode1.py",
        "scripts/episode1_build.py",
        "scripts/episode1_cpu_smoke.py",
        "scripts/episode1_watchdog.py",
        "scripts/watchdog_entry.py",
        "scripts/restart_cleanup_entry.py",
    ),
    fixed_files=(
        "pyproject.toml",
        "runtime/episode1/client-environment.json",
        "runtime/episode1/entrypoint.sh",
        "runtime/episode1/control.sh",
        "uv.lock",
        "schemas/episode1-observation.schema.json",
        "schemas/episode1-phase-ledger.schema.json",
        "schemas/episode1-protocol.schema.json",
        "schemas/episode1-public-aggregate.schema.json",
        "schemas/episode1-private-evidence.schema.json",
    ),
    collector_roots=(
        "src/runpod_benchmark/episode1_capture.py",
        "src/runpod_benchmark/episode1_telemetry.py",
        "src/runpod_benchmark/episode1_promotion.py",
    ),
    launcher_path="runtime/episode1/entrypoint.sh",
    private_schema_path="schemas/episode1-private-evidence.schema.json",
)


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise MaterialClosureError("material path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise MaterialClosureError("material path must be canonical and relative")
    return value


def _read(root: Path, relative: str, *, maximum: int = 256 * 1024 * 1024) -> bytes:
    """Read a bounded regular file while refusing every symlink component."""
    parts = _relative(relative).split("/")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        try:
            before = os.fstat(file_descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise MaterialClosureError("material is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(file_descriptor)
            identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            if len(raw) > maximum or identity(before) != identity(after):
                raise MaterialClosureError("material changed while it was read")
            return raw
        finally:
            os.close(file_descriptor)
    except OSError as exc:
        raise MaterialClosureError("material path is missing, linked, or unsafe") from exc
    finally:
        os.close(descriptor)


def read_material_bytes(
    repository_root: Path, material_manifest: Mapping[str, Any]
) -> dict[str, bytes]:
    """Read exactly the files named by an already compiled material manifest."""
    if (
        not isinstance(material_manifest, Mapping)
        or set(material_manifest) != {"classification", "aggregate_sha256", "files"}
        or material_manifest.get("classification") != "execution_material_hashes"
        or not isinstance(material_manifest.get("files"), list)
    ):
        raise MaterialClosureError("material manifest is open or incomplete")
    root = repository_root.resolve(strict=True)
    result: dict[str, bytes] = {}
    prior = ""
    for entry in material_manifest["files"]:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "sha256"}:
            raise MaterialClosureError("material manifest entry is open or incomplete")
        path = _relative(entry["path"])
        if path <= prior or path in result:
            raise MaterialClosureError("material manifest paths are not strictly sorted")
        raw = _read(root, path)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise MaterialClosureError("material bytes differ from compiled digest")
        result[path] = raw
        prior = path
    if not result or _manifest([
        {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}
        for path, raw in result.items()
    ]) != dict(material_manifest):
        raise MaterialClosureError("material manifest aggregate is invalid")
    return result


def read_repository_file(
    repository_root: Path, relative_path: str, *, maximum: int = 256 * 1024 * 1024
) -> bytes:
    """Public bounded reader used by the production entry point."""
    return _read(repository_root.resolve(strict=True), relative_path, maximum=maximum)


def _module_path(module: str) -> str:
    return "src/" + module.replace(".", "/") + ".py"


def _package_init_paths(module: str) -> set[str]:
    parts = module.split(".")[:-1]
    return {"src/" + "/".join(parts[:index]) + "/__init__.py" for index in range(1, len(parts) + 1)}


def _local_imports(path: str, raw: bytes) -> tuple[set[str], set[str]]:
    """Return (required modules, possible from-import submodules).

    ``import package.module`` and the base of ``from package.module import x``
    must resolve to local source.  The imported name ``x`` may instead be an
    attribute defined by the base module, so it is included when a matching
    local submodule exists but cannot be rejected merely because none exists.
    """
    try:
        tree = ast.parse(raw, filename=path)
    except (SyntaxError, UnicodeError) as exc:
        raise MaterialClosureError(f"cannot parse Python material {path}") from exc
    if path.startswith("src/"):
        current = path[4:-3].replace("/", ".")
        package = current.rsplit(".", 1)[0]
    else:
        package = ""
    required: set[str] = set()
    possible: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "runpod_benchmark" or alias.name.startswith("runpod_benchmark."):
                    required.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".") if package else []
                if node.level > len(base_parts) + 1:
                    raise MaterialClosureError("relative import escapes the package")
                prefix = ".".join(base_parts[: len(base_parts) - node.level + 1])
                base = ".".join(filter(None, (prefix, node.module or "")))
            else:
                base = node.module or ""
            if base == "runpod_benchmark" or base.startswith("runpod_benchmark."):
                if node.module:
                    required.add(base)
                for alias in node.names:
                    if alias.name != "*":
                        possible.add(".".join(filter(None, (base, alias.name))))
    return required, possible


def _source_module(path: str) -> str | None:
    if not path.startswith("src/") or not path.endswith(".py"):
        return None
    module = path[4:-3].replace("/", ".")
    if module.endswith(".__init__"):
        module = module.removesuffix(".__init__")
    return module


def _resolve_module(root: Path, module: str) -> str | None:
    candidates = [_module_path(module), "src/" + module.replace(".", "/") + "/__init__.py"]
    return next((candidate for candidate in candidates if (root / candidate).is_file()), None)


def _python_closure(root: Path, roots: Sequence[str]) -> set[str]:
    pending = list(roots)
    observed: set[str] = set()
    while pending:
        path = _relative(pending.pop())
        if path in observed:
            continue
        raw = _read(root, path)
        observed.add(path)
        source_module = _source_module(path)
        if source_module is not None:
            pending.extend(sorted(_package_init_paths(source_module)))
        required, possible = _local_imports(path, raw)
        for module in sorted(required | possible):
            selected = _resolve_module(root, module)
            if selected is not None:
                pending.append(selected)
                pending.extend(sorted(_package_init_paths(module)))
            elif module in required:
                raise MaterialClosureError(f"required local import does not resolve: {module}")
    return observed


def _build_paths(build_manifest: Mapping[str, Any]) -> set[str]:
    paths: set[str] = set()
    materials = build_manifest.get("materials")
    runtimes = build_manifest.get("runtimes")
    if not isinstance(materials, list) or not isinstance(runtimes, list):
        raise MaterialClosureError("validated build manifest lacks materials or runtimes")
    for entry in materials:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "sha256"}:
            raise MaterialClosureError("build material entry is not closed")
        paths.add(_relative(entry["path"]))
    runtime_names: set[str] = set()
    for runtime in runtimes:
        if not isinstance(runtime, Mapping) or runtime.get("runtime") not in {"vllm", "sglang"}:
            raise MaterialClosureError("build runtime selection is invalid")
        name = str(runtime["runtime"])
        runtime_names.add(name)
        paths.add(_relative(runtime.get("lock_path")))
    if runtime_names != {"vllm", "sglang"}:
        raise MaterialClosureError("build manifest must select both runtimes exactly once")
    return paths


def _manifest(entries: list[dict[str, str]]) -> dict[str, Any]:
    aggregate = hashlib.sha256(canonical_json(entries).encode()).hexdigest()
    return {
        "classification": "execution_material_hashes",
        "aggregate_sha256": aggregate,
        "files": entries,
    }


def compile_material_closure(
    repository_root: Path,
    profile: MaterialClosureProfile,
    build_manifest: Mapping[str, Any],
    explicit_inputs: Mapping[str, str],
    *,
    dockerfile_builder: Callable[[Mapping[str, Any], str], bytes],
) -> dict[str, Any]:
    """Compile the exact v1 material set and all plan digest projections.

    ``build_manifest`` must already have passed the build tool's strict
    validation. Required explicit roles are paths, never caller-provided hashes.
    """
    profile.checked()
    required_roles = {"build_manifest", "prompt_evidence", "provider_adapter", "build_attestation"}
    if set(explicit_inputs) != required_roles:
        raise MaterialClosureError("explicit material roles are open or incomplete")
    root = repository_root.resolve(strict=True)
    role_paths = {name: _relative(value) for name, value in explicit_inputs.items()}
    build_raw = _read(root, role_paths["build_manifest"])
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        observed_build = json.loads(
            build_raw.decode("utf-8", errors="strict"),
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise MaterialClosureError("build manifest bytes are not valid JSON") from exc
    if observed_build != build_manifest:
        raise MaterialClosureError("validated build manifest differs from selected bytes")

    python_roots = profile.python_roots + (role_paths["provider_adapter"],)
    paths = _python_closure(root, python_roots)
    paths.update(profile.fixed_files)
    paths.update(_build_paths(build_manifest))
    paths.update(role_paths.values())
    collector_paths = _python_closure(root, profile.collector_roots)
    paths.update(collector_paths)
    raw_by_path = {
        path: build_raw if path == role_paths["build_manifest"] else _read(root, path)
        for path in sorted(paths)
    }
    entries = [
        {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}
        for path, raw in raw_by_path.items()
    ]
    material = _manifest(entries)

    build_manifest_sha256 = hashlib.sha256(
        (canonical_json(build_manifest) + "\n").encode()
    ).hexdigest()
    build_spec = dockerfile_builder(build_manifest, build_manifest_sha256)
    if not isinstance(build_spec, bytes):
        raise MaterialClosureError("Dockerfile builder did not return bytes")
    runtime_digests = {}
    for runtime in build_manifest["runtimes"]:
        lock_path = _relative(runtime["lock_path"])
        runtime_digests[str(runtime["runtime"])] = hashlib.sha256(raw_by_path[lock_path]).hexdigest()
    collector_entries = [entry for entry in entries if entry["path"] in collector_paths]
    collector_manifest = {
        "schema_version": "episode1.collector-closure.v1",
        "files": collector_entries,
    }
    private_schema_path = profile.private_schema_path
    derived = {
        "material_sha256": material["aggregate_sha256"],
        "build_spec_sha256": hashlib.sha256(build_spec).hexdigest(),
        "dependency_lock_sha256": runtime_digests,
        "launcher_sha256": hashlib.sha256(raw_by_path[profile.launcher_path]).hexdigest(),
        "build_attestation_sha256": hashlib.sha256(raw_by_path[role_paths["build_attestation"]]).hexdigest(),
        "collector_sha256": hashlib.sha256(canonical_json(collector_manifest).encode()).hexdigest(),
        "private_schema_sha256": hashlib.sha256(raw_by_path[private_schema_path]).hexdigest(),
    }
    receipt_body = {
        "schema_version": "episode1.material-closure-receipt.v1",
        "profile_sha256": hashlib.sha256(canonical_json({
            "schema_version": profile.schema_version,
            "python_roots": list(profile.python_roots),
            "fixed_files": list(profile.fixed_files),
            "collector_roots": list(profile.collector_roots),
            "launcher_path": profile.launcher_path,
            "private_schema_path": profile.private_schema_path,
        }).encode()).hexdigest(),
        "material_sha256": material["aggregate_sha256"],
        "material_file_count": len(entries),
        "roles": dict(sorted(role_paths.items())),
        "collector_manifest": collector_manifest,
        "derived_plan_digests": derived,
    }
    receipt = {**receipt_body, "receipt_sha256": hashlib.sha256(canonical_json(receipt_body).encode()).hexdigest()}
    return {
        "material_manifest": material,
        "closure_receipt": receipt,
        "derived_plan_digests": derived,
    }


def verify_exact_material_manifest(compiled: Mapping[str, Any], supplied: Mapping[str, Any]) -> None:
    """Reject a caller manifest containing any missing, extra, or substituted file."""
    expected = compiled.get("material_manifest")
    if supplied != expected:
        raise MaterialClosureError("supplied material manifest is not the policy-derived exact closure")
