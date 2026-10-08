from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

from token_by_token_cli.errors import ClientError


FORBIDDEN_MODULE_ROOTS = {"private_runtime", "runtime", "deploy", "scripts", "data"}
FORBIDDEN_RESOURCE_PARTS = {"configs/combos", "results/", "raw/", "private/", ".cloudflare/", "credentials"}
FORBIDDEN_MARKERS = (
    b"--profile",
    b"private-benchmark-tool",
)
# Digests let the public guard reject known private package/tool identifiers
# without publishing those identifiers in the client source or binary.
FORBIDDEN_TOKEN_DIGESTS = {
    "012c41d3eb9b3a6c53088bf06b61e51b9bb7d08273a4ea8b09e9f8ecf5265e7d",
    "1cc188ed89503634c8d8859d3a7fcb7cc1b6714fd19f9ca173135f1e5d79b05f",
    "3a9abd26311b995a3a709191811ab9a392f01ac30bd7ab2b6bc82d552922b5f1",
    "5f9a04a312f1f7938bcd1bc1dba645b36ffcc16418ca674b3b5cfb70272224e0",
    "64f9281fcca718d226f43ccf6b94aefb402c3b16f7c6fbbde9124c1c23463106",
    "8b2e8e4ae104d7ef1ceb10d3de95390e625cd159d5ff5c8e8aabe9e9b46a4b43",
    "af07d0aea9eac9f7b82cb5f82d6324d33b785e6fa7dfe844fcabb3a4a9929b30",
}
APPROVED_MODULE_ROOTS = frozenset(sys.stdlib_module_names) | {
    "attr",
    "attrs",
    "jsonschema",
    "jsonschema_specifications",
    "pyi_rth_inspect",
    "pyi_rth_multiprocessing",
    "pyi_rth_pkgutil",
    "referencing",
    "rpds",
    "run_client",
    "token_by_token_cli",
    "typing_extensions",
}
APPROVED_RESOURCE_NAMES = {
    "base_library.zip",
    "jsonschema/benchmarks/issue232/issue.json",
    "token_by_token_cli/resources/episodes/catalog.v1.json",
    "token_by_token_cli/resources/schemas/episode-manifest.v1.schema.json",
    "token_by_token_cli/resources/schemas/inventory.v1.schema.json",
    "token_by_token_cli/resources/schemas/run-replay.v1.schema.json",
}
REQUIRED_MODULES = {
    "run_client",
    "token_by_token_cli.bundle",
    "token_by_token_cli.cli",
    "token_by_token_cli.contracts",
    "token_by_token_cli.offline",
    "token_by_token_cli.selftest",
    "token_by_token_cli.verify",
}
REQUIRED_RESOURCES = {
    "token_by_token_cli/resources/episodes/catalog.v1.json",
    "token_by_token_cli/resources/schemas/episode-manifest.v1.schema.json",
    "token_by_token_cli/resources/schemas/inventory.v1.schema.json",
    "token_by_token_cli/resources/schemas/run-replay.v1.schema.json",
}
APPROVED_RESOURCE_PREFIXES = (
    "attrs-26.1.0.dist-info/",
    "jsonschema-4.25.1.dist-info/",
    "jsonschema_specifications/schemas/",
)
CREDENTIAL_PATTERNS = (
    re.compile(rb"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\brp_[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
)
LIBPYTHON_RE = re.compile(r"^libpython3\.\d+(?:\.so(?:\.\d+)*)?(?:\.dylib)?$")
PYTHON_DLL_RE = re.compile(r"^python3\d{2}\.dll$")
RPDS_LIBRARY_RE = re.compile(r"^rpds/rpds\.[A-Za-z0-9_.-]+\.(?:so|pyd|dylib)$")
SYSTEM_LIBRARY_RE = re.compile(
    r"^(?:lib(?:bz2|crypto|expat|ffi|lzma|ncurses|readline|ssl|tinfo|uuid|z)"
    r"[A-Za-z0-9_.-]*\.so(?:\.\d+)*|python3\.dll|VCRUNTIME140(?:_1)?\.dll)$",
    re.IGNORECASE,
)


def _contains_forbidden_marker(payload: bytes) -> bool:
    lowered = payload.lower()
    if any(marker in lowered for marker in FORBIDDEN_MARKERS) or any(
        pattern.search(payload) for pattern in CREDENTIAL_PATTERNS
    ):
        return True
    tokens = [token.lstrip(b"-") for token in re.findall(rb"[a-z0-9_-]{3,64}", lowered)]
    candidates = [*tokens, *(b" ".join(tokens[index : index + 2]) for index in range(len(tokens) - 1))]
    return any(hashlib.sha256(token).hexdigest() in FORBIDDEN_TOKEN_DIGESTS for token in candidates)


def _approved_resource(resource: str) -> bool:
    normalized = resource.replace("\\", "/")
    filename = normalized.rsplit("/", 1)[-1]
    stdlib_extension = (
        filename.endswith((".so", ".pyd", ".dylib"))
        and filename.split(".", 1)[0] in sys.stdlib_module_names
    )
    return (
        normalized in APPROVED_RESOURCE_NAMES
        or normalized.startswith(APPROVED_RESOURCE_PREFIXES)
        or LIBPYTHON_RE.fullmatch(normalized) is not None
        or PYTHON_DLL_RE.fullmatch(normalized) is not None
        or RPDS_LIBRARY_RE.fullmatch(normalized) is not None
        or stdlib_extension
        or SYSTEM_LIBRARY_RE.fullmatch(normalized) is not None
    )


def _archive_member_name(path: Path) -> str:
    return re.sub(r"^\d+-", "", path.name, count=1)


def _base_library_modules(path: Path) -> set[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            modules: set[str] = set()
            total_size = 0
            for info in archive.infolist():
                if info.is_dir() or not info.filename.endswith((".py", ".pyc")):
                    continue
                total_size += info.file_size
                if info.file_size > 8 * 1024 * 1024 or total_size > 32 * 1024 * 1024:
                    raise ClientError("BINARY_AUDIT_INPUT", "extracted standard-library archive is oversized")
                if _contains_forbidden_marker(archive.read(info)):
                    raise ClientError(
                        "FORBIDDEN_BINARY_CONTENT",
                        "candidate standard-library archive contains a forbidden private marker",
                    )
                parts = info.filename.replace("\\", "/").rsplit(".", 1)[0].split("/")
                if parts[-1] == "__init__":
                    parts.pop()
                if parts:
                    modules.add(".".join(parts))
            if archive.testzip() is not None:
                raise ClientError("BINARY_AUDIT_INPUT", "extracted standard-library archive is corrupt")
            return modules
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise ClientError("BINARY_AUDIT_INPUT", "extracted standard-library archive is invalid") from error


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
    module_roots = [module.split(".", 1)[0].lower() for module in modules]
    if not REQUIRED_MODULES.issubset(modules):
        raise ClientError("BINARY_AUDIT_INPUT", "analysis inventory is missing required public client modules")
    if any(root not in APPROVED_MODULE_ROOTS for root in module_roots):
        raise ClientError("FORBIDDEN_BUILD_INPUT", "analysis contains a module outside the public allowlist")
    if any(
        root in FORBIDDEN_MODULE_ROOTS
        or hashlib.sha256(root.encode("utf-8")).hexdigest() in FORBIDDEN_TOKEN_DIGESTS
        for root in module_roots
    ):
        raise ClientError("FORBIDDEN_BUILD_INPUT", "analysis contains a forbidden module root")
    if any(any(part in resource.replace("\\", "/").lower() for part in FORBIDDEN_RESOURCE_PARTS) for resource in resources):
        raise ClientError("FORBIDDEN_BUILD_INPUT", "analysis contains a forbidden resource path")
    if any(not _approved_resource(resource) for resource in resources):
        raise ClientError("FORBIDDEN_BUILD_INPUT", "analysis contains a resource outside the public allowlist")
    if not REQUIRED_RESOURCES.issubset(resources):
        raise ClientError("BINARY_AUDIT_INPUT", "analysis inventory is missing required public resources")
    if _contains_forbidden_marker(path.read_bytes()):
        raise ClientError("FORBIDDEN_BINARY_CONTENT", "candidate executable contains a forbidden private marker")
    extracted_files = [candidate for candidate in extracted_root.rglob("*") if candidate.is_file()]
    extracted_names = [candidate.relative_to(extracted_root).as_posix() for candidate in extracted_files]
    extracted_modules = {_archive_member_name(candidate) for candidate in extracted_files}
    base_libraries = [candidate for candidate in extracted_files if _archive_member_name(candidate) == "base_library.zip"]
    if len(base_libraries) > 1:
        raise ClientError("BINARY_AUDIT_INPUT", "extracted archive contains duplicate standard-library archives")
    if base_libraries:
        extracted_modules.update(_base_library_modules(base_libraries[0]))
    missing_modules = sorted(set(modules) - extracted_modules)
    if missing_modules:
        raise ClientError("BINARY_AUDIT_INPUT", "extracted archive does not account for every analyzed module")
    missing_resources = sorted(
        resource for resource in resources if not any(name.endswith(resource) for name in extracted_names)
    )
    if missing_resources:
        raise ClientError("BINARY_AUDIT_INPUT", "extracted archive does not account for every analyzed resource")
    for candidate in extracted_root.rglob("*"):
        if candidate.is_symlink():
            raise ClientError("FORBIDDEN_BINARY_CONTENT", "candidate archive contains a link")
        if candidate.is_file() and _contains_forbidden_marker(candidate.read_bytes()):
            raise ClientError("FORBIDDEN_BINARY_CONTENT", "candidate archive contains a forbidden private marker")
