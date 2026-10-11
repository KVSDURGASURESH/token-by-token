#!/usr/bin/env python3
"""Closed, CPU-only validation of an installed environment against a hashed lock."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import platform
import re
import site
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version
except ImportError:  # packaging bundled by pip is still loaded from this interpreter's venv.
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name
    from pip._vendor.packaging.version import InvalidVersion, Version


class ValidationInputError(ValueError):
    pass


@dataclass(frozen=True)
class Distribution:
    name: str
    version: str
    requires: tuple[str, ...] = ()
    provides_extras: tuple[str, ...] = ()


@dataclass(frozen=True)
class Lock:
    sha256: str
    packages: Mapping[str, str]
    hash_counts: Mapping[str, int]


_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*\\$")
_HASH = re.compile(r"^\s+--hash=sha256:([0-9a-fA-F]{64})(?:\s*\\)?$")
_URL_OPT = re.compile(r"^--(?:extra-)?index-url\s+https://\S+$")


def parse_lock_bytes(raw: bytes) -> Lock:
    """Parse the deliberately narrow uv/pip-compile frozen lock grammar."""
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationInputError("lock_not_utf8") from exc
    packages: dict[str, str] = {}
    hashes: dict[str, int] = {}
    current: str | None = None
    only_binary = False
    saw_index = False
    for number, original in enumerate(text.splitlines(), 1):
        line = original.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _URL_OPT.fullmatch(stripped):
            if current is not None:
                raise ValidationInputError(f"option_inside_requirement:{number}")
            saw_index = True
            continue
        if stripped == "--only-binary :all:":
            if current is not None:
                raise ValidationInputError(f"option_inside_requirement:{number}")
            only_binary = True
            continue
        match = _REQ.fullmatch(stripped)
        if match:
            if current is not None and hashes[current] == 0:
                raise ValidationInputError(f"requirement_without_hash:{current}")
            name = canonicalize_name(match.group(1))
            try:
                version = str(Version(match.group(2)))
            except InvalidVersion as exc:
                raise ValidationInputError(f"invalid_version:{number}") from exc
            if name in packages:
                raise ValidationInputError(f"duplicate_requirement:{name}")
            packages[name] = version
            hashes[name] = 0
            current = name
            continue
        match = _HASH.fullmatch(line)
        if match and current is not None:
            hashes[current] += 1
            continue
        # This rejects editable/VCS/direct URL/path/archive/constraint/include and
        # every option outside the small allowlist above.
        raise ValidationInputError(f"unsupported_lock_line:{number}")
    if current is not None and hashes[current] == 0:
        raise ValidationInputError(f"requirement_without_hash:{current}")
    if not packages:
        raise ValidationInputError("empty_lock")
    if not saw_index:
        raise ValidationInputError("missing_https_index")
    if not only_binary:
        raise ValidationInputError("missing_only_binary_all")
    return Lock(digest, packages, hashes)


def installed_distributions() -> list[Distribution]:
    result: list[Distribution] = []
    prefix = Path(sys.prefix).resolve()
    for dist in md.distributions():
        name = dist.metadata.get("Name")
        if not name:
            raise ValidationInputError("installed_distribution_without_name")
        try:
            location = Path(dist.locate_file("")).resolve()
            location.relative_to(prefix)
        except (OSError, ValueError) as exc:
            raise ValidationInputError("distribution_outside_venv") from exc
        result.append(Distribution(
            canonicalize_name(name), str(Version(dist.version)),
            tuple(dist.requires or ()), tuple(dist.metadata.get_all("Provides-Extra") or ()),
        ))
    return result


POLICIES = {
    "vllm": {
        "roots": ("vllm==0.29.0",),
        "pins": {"vllm": "0.29.0", "torch": "2.13.0+cu130", "triton": "3.7.1", "nvidia-nccl-cu13": "2.29.7"},
        "allowed": (),
    },
    "sglang": {
        "roots": ("sglang[all]==0.5.20", "sglang-kernel==0.4.7"),
        "pins": {"sglang": "0.5.20", "sglang-kernel": "0.4.7", "torch": "2.13.0+cu130", "triton": "3.7.1", "nvidia-nccl-cu13": "2.30.7"},
        "allowed": (("torch", "nvidia-nccl-cu13", "==2.29.7", "sys_platform == \"linux\"", "2.30.7"),),
    },
}


def _error(code: str, **fields: str) -> dict[str, str]:
    return {"code": code, **fields}


def validate(
    *, runtime: str, lock: Lock, distributions: Iterable[Distribution],
    bootstrap_allowlist: Mapping[str, str] | None = None,
    marker_environment: Mapping[str, str] | None = None,
) -> dict:
    """Pure validation core. Its inputs contain no filesystem locations."""
    if runtime not in POLICIES:
        raise ValidationInputError("unknown_runtime")
    bootstrap: dict[str, str] = {}
    for raw_name, raw_version in (bootstrap_allowlist or {}).items():
        name = canonicalize_name(raw_name)
        if name in bootstrap:
            raise ValidationInputError("duplicate_bootstrap_package")
        bootstrap[name] = str(Version(raw_version))
    inventory: dict[str, Distribution] = {}
    errors: list[dict[str, str]] = []
    for item in distributions:
        name = canonicalize_name(item.name)
        normalized = Distribution(name, str(Version(item.version)), tuple(item.requires), tuple(item.provides_extras))
        if name in inventory:
            errors.append(_error("duplicate_installed_distribution", package=name))
        else:
            inventory[name] = normalized
    for name, expected in sorted(lock.packages.items()):
        actual = inventory.get(name)
        if actual is None:
            errors.append(_error("missing_package", package=name, expected=expected))
        elif actual.version != expected:
            errors.append(_error("version_mismatch", package=name, expected=expected, actual=actual.version))
    for name, item in sorted(inventory.items()):
        if name in lock.packages:
            continue
        if bootstrap.get(name) == item.version:
            continue
        errors.append(_error("unexpected_package", package=name, actual=item.version))
    for name, version in sorted(bootstrap.items()):
        if name in lock.packages:
            errors.append(_error("bootstrap_overlaps_lock", package=name))
        elif name in inventory and inventory[name].version != version:
            errors.append(_error("bootstrap_version_mismatch", package=name, expected=version, actual=inventory[name].version))

    policy = POLICIES[runtime]
    for name, expected in policy["pins"].items():
        if lock.packages.get(name) != expected:
            errors.append(_error("policy_lock_pin_mismatch", package=name, expected=expected,
                                 actual=lock.packages.get(name, "missing")))

    env = dict(marker_environment or default_environment())
    active_extras: dict[str, set[str]] = {name: set() for name in inventory}
    for raw_root in policy["roots"]:
        root = Requirement(raw_root)
        name = canonicalize_name(root.name)
        active_extras.setdefault(name, set()).update(canonicalize_name(x) for x in root.extras)

    parsed_requirements: dict[str, tuple[Requirement, ...]] = {}
    for source, dist in sorted(inventory.items()):
        parsed: list[Requirement] = []
        for raw_requirement in dict.fromkeys(dist.requires):
            try:
                parsed.append(Requirement(raw_requirement))
            except Exception:
                errors.append(_error("invalid_installed_requirement", package=source))
        parsed_requirements[source] = tuple(parsed)

    def is_active(req: Requirement, extras: set[str]) -> bool:
        return req.marker is None or any(
            req.marker.evaluate({**env, "extra": extra}) for extra in ({""} | extras)
        )

    # Compute the extras closure first. Every distribution participates with its
    # base requirements; roots add selected extras. Evaluation happens once only
    # after this reaches a fixed point.
    changed = True
    while changed:
        changed = False
        for source, requirements in parsed_requirements.items():
            for req in requirements:
                if not is_active(req, active_extras[source]) or req.url:
                    continue
                target = canonicalize_name(req.name)
                if target not in inventory:
                    continue
                requested = {canonicalize_name(extra) for extra in req.extras}
                before = len(active_extras[target])
                active_extras[target].update(requested)
                changed = changed or len(active_extras[target]) != before

    mismatches: list[tuple[str, str, str, str, str]] = []
    checks = 0
    for source, dist in sorted(inventory.items()):
        extras = active_extras[source]
        declared_extras = {canonicalize_name(extra) for extra in dist.provides_extras}
        for extra in sorted(extras - declared_extras):
            errors.append(_error("undeclared_requested_extra", package=source, extra=extra))
        for req in parsed_requirements[source]:
            if not is_active(req, extras):
                continue
            checks += 1
            target = canonicalize_name(req.name)
            if req.url:
                errors.append(_error("direct_installed_requirement", package=source, dependency=target))
                continue
            target_dist = inventory.get(target)
            if target_dist is None:
                errors.append(_error("active_dependency_missing", package=source, dependency=target))
                continue
            if req.specifier and not req.specifier.contains(Version(target_dist.version), prereleases=True):
                marker = str(req.marker) if req.marker else ""
                mismatches.append((source, target, str(req.specifier), marker, target_dist.version))
    expected_mismatches = sorted(policy["allowed"])
    actual_mismatches = sorted(mismatches)
    if actual_mismatches != expected_mismatches:
        errors.append(_error("dependency_mismatch_set", expected=json.dumps(expected_mismatches, separators=(",", ":")),
                             actual=json.dumps(actual_mismatches, separators=(",", ":"))))
    return {
        "schema_version": "episode1.dependency-validation.v1",
        "status": "pass" if not errors else "fail",
        "runtime": runtime,
        "lock_sha256": lock.sha256,
        "lock_package_count": len(lock.packages),
        "installed_package_count": len(inventory),
        "bootstrap_allowlist": [{"name": n, "version": v} for n, v in sorted(bootstrap.items())],
        "inventory": [{"name": n, "version": d.version} for n, d in sorted(inventory.items())],
        "active_dependency_checks": checks,
        "allowed_dependency_mismatches": [
            {"package": a, "dependency": b, "required": c, "marker": d, "installed": e}
            for a, b, c, d, e in actual_mismatches if (a, b, c, d, e) in expected_mismatches
        ],
        "errors": errors,
    }


def _read_bootstrap(path: Path | None) -> tuple[dict[str, str], str | None]:
    if path is None:
        return {}, None
    raw = path.read_bytes()
    try:
        obj = json.loads(raw)
        if set(obj) != {"schema_version", "packages"} or obj["schema_version"] != "episode1.bootstrap.v1" or not isinstance(obj["packages"], dict):
            raise ValueError
        packages = {}
        for raw_name, raw_version in obj["packages"].items():
            name = canonicalize_name(raw_name)
            if name in packages:
                raise ValueError
            packages[name] = str(Version(raw_version))
    except Exception as exc:
        raise ValidationInputError("invalid_bootstrap_manifest") from exc
    return packages, hashlib.sha256(raw).hexdigest()


def _closed_failure(runtime: str, code: str) -> dict:
    return {"schema_version": "episode1.dependency-validation.v1", "status": "fail", "runtime": runtime,
            "lock_sha256": None, "lock_package_count": 0, "installed_package_count": 0,
            "bootstrap_allowlist": [], "inventory": [], "active_dependency_checks": 0,
            "allowed_dependency_mismatches": [], "errors": [{"code": code}]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, choices=sorted(POLICIES))
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--bootstrap-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if sys.version_info[:2] != (3, 12):
            raise ValidationInputError("python_not_3_12")
        if sys.prefix == sys.base_prefix:
            raise ValidationInputError("not_isolated_venv")
        if site.ENABLE_USER_SITE is not False:
            raise ValidationInputError("user_site_enabled")
        env = default_environment()
        if env.get("sys_platform") != "linux" or env.get("platform_machine") != "x86_64":
            raise ValidationInputError("platform_not_linux_x86_64")
        lock = parse_lock_bytes(args.lock.read_bytes())
        bootstrap, bootstrap_sha = _read_bootstrap(args.bootstrap_manifest)
        result = validate(runtime=args.runtime, lock=lock, distributions=installed_distributions(),
                          bootstrap_allowlist=bootstrap, marker_environment=env)
        result["python_version"] = platform.python_version()
        result["platform"] = "linux-x86_64"
        result["bootstrap_manifest_sha256"] = bootstrap_sha
    except (OSError, ValidationInputError) as exc:
        code = str(exc) if isinstance(exc, ValidationInputError) else "input_unreadable"
        result = _closed_failure(args.runtime, code)
    except Exception:
        # Metadata is untrusted input. Never leak a traceback, path, or metadata
        # payload into the machine-consumed receipt.
        result = _closed_failure(args.runtime, "internal_validation_error")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
