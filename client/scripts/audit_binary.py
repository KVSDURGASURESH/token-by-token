from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re

from token_by_token_cli.errors import ClientError


FORBIDDEN_MODULE_ROOTS = {"private_runtime", "runtime", "deploy", "scripts", "data"}
FORBIDDEN_RESOURCE_PARTS = {"configs/combos", "results/", "raw/", "private/", ".cloudflare/", "credentials"}
FORBIDDEN_MARKERS = (
    b"private-benchmark-tool",
)
# Digests let the public guard reject known private package/tool identifiers
# without publishing those identifiers in the client source or binary.
FORBIDDEN_TOKEN_DIGESTS = {
    "012c41d3eb9b3a6c53088bf06b61e51b9bb7d08273a4ea8b09e9f8ecf5265e7d",
    "5f9a04a312f1f7938bcd1bc1dba645b36ffcc16418ca674b3b5cfb70272224e0",
}


def _contains_forbidden_marker(payload: bytes) -> bool:
    lowered = payload.lower()
    if any(marker in lowered for marker in FORBIDDEN_MARKERS):
        return True
    tokens = re.findall(rb"[a-z0-9_-]{4,64}", lowered)
    return any(hashlib.sha256(token).hexdigest() in FORBIDDEN_TOKEN_DIGESTS for token in tokens)


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
    module_roots = (module.split(".", 1)[0].lower().encode("utf-8") for module in modules)
    if any(
        root.decode("utf-8") in FORBIDDEN_MODULE_ROOTS
        or hashlib.sha256(root).hexdigest() in FORBIDDEN_TOKEN_DIGESTS
        for root in module_roots
    ):
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
