from __future__ import annotations

import json
from pathlib import Path

from token_by_token_cli.errors import ClientError


FORBIDDEN_MODULE_ROOTS = {"runpod_benchmark", "runtime", "deploy", "scripts", "data"}
FORBIDDEN_RESOURCE_PARTS = {"configs/combos", "results/", "raw/", "private/", ".cloudflare/", "credentials"}
FORBIDDEN_MARKERS = (
    b"private-benchmark-tool",
    b"runpod_benchmark",
    b"agentbench",
    b"agentbench --profile",
)


def _contains_forbidden_marker(payload: bytes) -> bool:
    lowered = payload.lower()
    return any(marker in lowered for marker in FORBIDDEN_MARKERS)


def audit_binary(path: Path, analysis_toc: Path, extracted_root: Path) -> None:
    path = Path(path)
    analysis_toc = Path(analysis_toc)
    extracted_root = Path(extracted_root)
    if not path.is_file() or not analysis_toc.is_file() or not extracted_root.is_dir():
        raise ClientError("BINARY_AUDIT_INPUT", "binary audit inputs are incomplete")
    try:
        inventory = json.loads(analysis_toc.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClientError("BINARY_AUDIT_INPUT", "analysis inventory is invalid") from error
    modules = inventory.get("modules")
    resources = inventory.get("resources")
    if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        raise ClientError("BINARY_AUDIT_INPUT", "module inventory must be a string list")
    if not isinstance(resources, list) or not all(isinstance(item, str) for item in resources):
        raise ClientError("BINARY_AUDIT_INPUT", "resource inventory must be a string list")
    if any(module.split(".", 1)[0].lower() in FORBIDDEN_MODULE_ROOTS for module in modules):
        raise ClientError("FORBIDDEN_BUILD_INPUT", "analysis contains a forbidden module root")
    if any(any(part in resource.replace("\\", "/").lower() for part in FORBIDDEN_RESOURCE_PARTS) for resource in resources):
        raise ClientError("FORBIDDEN_BUILD_INPUT", "analysis contains a forbidden resource path")
    if _contains_forbidden_marker(path.read_bytes()):
        raise ClientError("FORBIDDEN_BINARY_CONTENT", "candidate executable contains a forbidden private marker")
    for candidate in extracted_root.rglob("*"):
        if candidate.is_symlink():
            raise ClientError("FORBIDDEN_BINARY_CONTENT", "candidate archive contains a link")
        if candidate.is_file() and _contains_forbidden_marker(candidate.read_bytes()):
            raise ClientError("FORBIDDEN_BINARY_CONTENT", "candidate archive contains a forbidden private marker")

