"""Offline-input Episode 1 image build and content-addressed CPU evidence.

No downloads, registry writes, GPU access, or provider APIs are implemented.
The build subcommand explicitly invokes the operator's existing local Docker.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import gzip
import importlib
import json
import importlib.metadata
import importlib.util
import lzma
import math
import os
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath

from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.tags import compatible_tags, cpython_tags
from packaging.version import Version

BASE = "nvidia/cuda@sha256:a85c9f5af049f0ab679c1669ae6fa8393022886739af7361e85bb96878e8cdd4"
SHA = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[a-z0-9][a-z0-9+.-]*")
PACKAGE = "runpod_benchmark"
PACKAGE_PREFIX = f"src/{PACKAGE}/"
CPU_STARTUP_CONTRACT = "runtime/episode1/cpu-startup.json"
REQUIRED = {f"{PACKAGE_PREFIX}__init__.py", f"{PACKAGE_PREFIX}dependency_validator.py",
            f"{PACKAGE_PREFIX}pod_supervisor.py", f"{PACKAGE_PREFIX}episode1.py",
            f"{PACKAGE_PREFIX}episode1_remote_control.py",
            f"{PACKAGE_PREFIX}native_probe_hardening.py", "runtime/episode1/entrypoint.sh",
            "runtime/episode1/control.sh",
            CPU_STARTUP_CONTRACT}
RUNTIME_POLICY = {
    "vllm": {
        "lock_sha256": "c7319e5fc782b79780f4a4a1068f9feae6647531ab4b9540bf468f54a09b6b48",
        "package_count": 196,
        "required": {"vllm": "0.29.0", "torch": "2.13.0+cu130", "triton": "3.7.1",
                     "nvidia-nccl-cu13": "2.29.7"},
    },
    "sglang": {
        "lock_sha256": "6cba8a33762d2b224cf1599858e23dbc5c46384a25a4f7d84d0633c5ea848dc6",
        "package_count": 243,
        "required": {"sglang": "0.5.20", "sglang-kernel": "0.4.7",
                     "torch": "2.13.0+cu130", "triton": "3.7.1",
                     "nvidia-nccl-cu13": "2.30.7", "cuda-tile": "1.6.0rc5"},
    },
}
ZSTANDARD_VERSION = "0.25.0"
MAX_DEB_CONTROL_DECOMPRESSED = 32 * 1024 * 1024
GIB = 1024 ** 3
# These limits are deliberately large enough for two retained CUDA runtime
# environments, but finite so a malformed archive cannot request unbounded
# disk, CPU, or memory. They are copied into local receipts and evidence.
RESOURCE_BOUNDS = {
    "context_files": 100_000,
    "context_member_bytes": 16 * GIB,
    "context_total_bytes": 96 * GIB,
    "oci_archive_bytes": 128 * GIB,
    "oci_outer_members": 100_000,
    "oci_outer_member_bytes": 96 * GIB,
    "oci_outer_total_bytes": 256 * GIB,
    "oci_descriptors": 4_096,
    "oci_layers": 512,
    "oci_layer_members": 1_000_000,
    "oci_layer_member_bytes": 32 * GIB,
    "oci_layer_uncompressed_bytes": 192 * GIB,
    "oci_total_uncompressed_bytes": 512 * GIB,
    "oci_json_bytes": 16 * 1024 * 1024,
    "oci_evidence_bytes": 16 * 1024 * 1024,
    "oci_attestation_bytes": 32 * 1024 * 1024,
    "oci_tar_extension_bytes": 1024 * 1024,
    "oci_tar_extensions": 256,
    "oci_tar_extension_total_bytes": 64 * 1024 * 1024,
}
BUILD_INVOCATION = {
    "platform": "linux/amd64", "network": "none",
    "provenance": "mode=max,version=v0.2", "context_transport": "stdin-tar",
    "output": "oci-artifact",
}


class BuildError(ValueError):
    pass


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sealed(body):
    if not isinstance(body, dict) or "artifact_sha256" in body:
        raise BuildError("invalid_receipt")
    return {**body, "artifact_sha256": digest(canonical(body))}


def verify_seal(receipt):
    if not isinstance(receipt, dict) or not SHA.fullmatch(str(receipt.get("artifact_sha256", ""))):
        raise BuildError("invalid_receipt")
    body = {key: value for key, value in receipt.items() if key != "artifact_sha256"}
    if digest(canonical(body)) != receipt["artifact_sha256"]:
        raise BuildError("receipt_hash_mismatch")
    return receipt


def tar_name(value, *, directory=False, allow_root=False):
    """Return one canonical POSIX tar name.

    Leading ``./`` and directory trailing slashes are normal tar spellings and
    are normalized. Internal dot/empty components and all other aliases are
    rejected so duplicate detection operates on canonical names.
    """
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise BuildError("unsafe_archive_path")
    while value.startswith("./"):
        value = value[2:]
    if directory:
        value = value.rstrip("/")
    elif value.endswith("/"):
        raise BuildError("unsafe_archive_path")
    if value in {"", "."}:
        if allow_root and directory:
            return ""
        raise BuildError("unsafe_archive_path")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
        raise BuildError("unsafe_archive_path")
    if str(PurePosixPath(value)) != value:
        raise BuildError("unsafe_archive_path")
    return value


def check_budget(kind, count, total, size):
    if type(size) is not int or size < 0:
        raise BuildError("invalid_archive_size")
    limits = {
        "context": ("context_files", "context_total_bytes", "context_member_bytes"),
        "outer": ("oci_outer_members", "oci_outer_total_bytes", "oci_outer_member_bytes"),
        "layer": ("oci_layer_members", "oci_layer_uncompressed_bytes", "oci_layer_member_bytes"),
    }
    count_key, total_key, member_key = limits[kind]
    if count > RESOURCE_BOUNDS[count_key] or total > RESOURCE_BOUNDS[total_key] or size > RESOURCE_BOUNDS[member_key]:
        raise BuildError("resource_bound_exceeded")


def copy_exact(src, dst, size):
    """Copy exactly an already-budgeted size and reject growth or truncation."""
    if type(size) is not int or size < 0:
        raise BuildError("invalid_archive_size")
    remaining = size
    while remaining:
        chunk = src.read(min(1024 * 1024, remaining))
        if not chunk:
            raise BuildError("material_changed_while_copying")
        dst.write(chunk); remaining -= len(chunk)
    if src.read(1):
        raise BuildError("material_changed_while_copying")


class BoundedTarInfo(tarfile.TarInfo):
    """Cap hidden PAX/GNU extension reads before tarfile allocates them."""
    def _record_extension(self, archive):
        if type(self.size) is not int or self.size < 0:
            raise BuildError("invalid_archive_size")
        count = getattr(archive, "_episode1_extension_count", 0) + 1
        total = getattr(archive, "_episode1_extension_bytes", 0) + self.size
        if (self.size > RESOURCE_BOUNDS["oci_tar_extension_bytes"] or
                count > RESOURCE_BOUNDS["oci_tar_extensions"] or
                total > RESOURCE_BOUNDS["oci_tar_extension_total_bytes"]):
            raise BuildError("tar_extension_metadata_too_large")
        archive._episode1_extension_count = count
        archive._episode1_extension_bytes = total

    def _proc_gnulong(self, archive):
        self._record_extension(archive)
        return super()._proc_gnulong(archive)

    def _proc_sparse(self, archive):
        # Legacy sparse headers may contain an unbounded internal extension
        # chain and require filesystem-specific hole semantics.
        raise BuildError("unsupported_sparse_image_node")

    def _proc_pax(self, archive):
        self._record_extension(archive)
        buf = archive.fileobj.read(self._block(self.size))
        headers = archive.pax_headers if self.type == tarfile.XGLTYPE else archive.pax_headers.copy()
        match = re.search(br"\d+ hdrcharset=([^\n]+)\n", buf)
        if match is not None: headers["hdrcharset"] = match.group(1).decode("utf-8")
        encoding = archive.encoding if headers.get("hdrcharset") == "BINARY" else "utf-8"
        regex = re.compile(br"(\d+) ([^=]+)=")
        pos = 0
        while match := regex.match(buf, pos):
            length, keyword = match.groups(); length = int(length)
            if length <= 0 or pos + length > len(buf): raise BuildError("invalid_pax_header")
            value = buf[match.end(2) + 1:match.start(1) + length - 1]
            keyword = self._decode_pax_field(keyword, "utf-8", "utf-8", archive.errors)
            value_encoding = encoding if keyword in tarfile.PAX_NAME_FIELDS else "utf-8"
            value = self._decode_pax_field(value, value_encoding, archive.encoding, archive.errors)
            headers[keyword] = value; pos += length
        if any(key.startswith("GNU.sparse") for key in headers):
            raise BuildError("unsupported_sparse_image_node")
        try:
            following = self.fromtarfile(archive)
        except tarfile.HeaderError as exc:
            raise tarfile.SubsequentHeaderError(str(exc)) from None
        if self.type in (tarfile.XHDTYPE, tarfile.SOLARIS_XHDTYPE):
            following._apply_pax_info(headers, archive.encoding, archive.errors)
            following.offset = self.offset
            if "size" in headers:
                offset = following.offset_data
                if following.isreg() or following.type not in tarfile.SUPPORTED_TYPES:
                    offset += following._block(following.size)
                archive.offset = offset
        return following


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise BuildError("duplicate_json_key")
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(BuildError("nonfinite_json")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError("invalid_json") from exc


def closed(obj, fields):
    if not isinstance(obj, dict) or set(obj) != set(fields.split()):
        raise BuildError("invalid_manifest_fields")
    return obj


def sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise BuildError("invalid_sha256")
    return value


def rel(value):
    if (not isinstance(value, str) or not value or "\\" in value or
            any(ord(c) < 33 for c in value) or not re.fullmatch(r"[A-Za-z0-9_./+-]+", value)):
        raise BuildError("unsafe_relative_path")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or str(p) != value:
        raise BuildError("unsafe_relative_path")
    return value


def https(value):
    if not isinstance(value, str):
        raise BuildError("invalid_artifact_origin")
    url = urllib.parse.urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment or url.query:
        raise BuildError("invalid_artifact_origin")


def regular(root, name):
    name = rel(name)
    path = root / name
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink():
            raise BuildError("symlink_material")
    if not path.is_file():
        raise BuildError("missing_material")
    return path


def hashfile(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(root, record):
    path = regular(root, record["path"])
    if hashfile(path) != sha(record["sha256"]):
        raise BuildError("material_hash_mismatch")
    return path


def _module_for_material(path):
    """Return (module, is_package) for one package source material."""
    if not path.startswith(PACKAGE_PREFIX) or not path.endswith(".py"):
        return None
    tail = path[len("src/"):-3]
    parts = tail.split("/")
    if parts[-1] == "__init__":
        parts.pop()
        is_package = True
    else:
        is_package = False
    if not parts or any(not part.isidentifier() for part in parts):
        raise BuildError("invalid_python_material_path")
    return ".".join(parts), is_package


def _resolve_relative(module, is_package, level, imported):
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    ascend = level - 1
    if level < 1 or ascend >= len(package_parts):
        raise BuildError("unresolved_relative_import")
    base = package_parts[:len(package_parts) - ascend]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _required_module_chain(module):
    parts = module.split(".")
    return {".".join(parts[:i]) for i in range(1, len(parts))}


def _local_imports(tree, module, is_package):
    """Conservatively find package imports without importing staged source."""
    required = set()
    importlib_names = {"importlib"}
    import_module_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
                if alias.name == PACKAGE or alias.name.startswith(PACKAGE + "."):
                    required.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _resolve_relative(module, is_package, node.level, node.module)
            else:
                base = node.module or ""
            if base == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_names.add(alias.asname or alias.name)
            if base == PACKAGE or base.startswith(PACKAGE + "."):
                required.add(base)
                if node.module is None or base == PACKAGE:
                    for alias in node.names:
                        if alias.name != "*":
                            required.add(base + "." + alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dynamic = isinstance(node.func, ast.Name) and node.func.id in ({"__import__"} | import_module_names)
        dynamic = dynamic or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module" and
                              isinstance(node.func.value, ast.Name) and node.func.value.id in importlib_names)
        if not dynamic:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            raise BuildError("unresolved_dynamic_import")
        target = node.args[0].value
        if target.startswith("."):
            raise BuildError("unresolved_dynamic_import")
        if target == PACKAGE or target.startswith(PACKAGE + "."):
            required.add(target)
    return required


def validate_import_closure(root, material_paths, *, entry_module=None):
    """Require a complete deterministic closure for all staged package source."""
    modules = {}
    parsed = {}
    for path in sorted(material_paths):
        record = _module_for_material(path)
        if record is None:
            continue
        module, is_package = record
        if module in modules:
            raise BuildError("duplicate_python_module")
        with regular(root, path).open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > 2 * 1024 * 1024:
                raise BuildError("python_material_too_large")
            source = stream.read(2 * 1024 * 1024 + 1)
            if len(source) != size or len(source) > 2 * 1024 * 1024:
                raise BuildError("python_material_changed_or_too_large")
        try:
            parsed[module] = ast.parse(source, filename=path)
        except (SyntaxError, ValueError) as exc:
            raise BuildError("invalid_python_source") from exc
        modules[module] = is_package
    if PACKAGE not in modules or not modules[PACKAGE]:
        raise BuildError("missing_package_initializer")
    if entry_module is not None:
        if (not isinstance(entry_module, str) or
                not (entry_module == PACKAGE or entry_module.startswith(PACKAGE + "."))):
            raise BuildError("invalid_cpu_startup_module")
        if entry_module not in modules:
            raise BuildError("missing_cpu_startup_module")
    required = {PACKAGE}
    if entry_module:
        required.add(entry_module)
    for module, tree in parsed.items():
        required.update(_required_module_chain(module))
        required.update(_local_imports(tree, module, modules[module]))
    missing = sorted(name for name in required if name not in modules)
    if missing:
        raise BuildError("unresolved_local_import:" + ",".join(missing))
    return {"package": PACKAGE, "modules": sorted(modules), "entry_module": entry_module}


def cpu_startup_contract(root, material_paths):
    """Read the required closed contract for the bounded CPU CLI smoke."""
    if CPU_STARTUP_CONTRACT not in material_paths:
        raise BuildError("missing_cpu_startup_contract")
    path = regular(root, CPU_STARTUP_CONTRACT)
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if size > 4096:
            raise BuildError("cpu_startup_contract_too_large")
        raw = stream.read(4097)
        if len(raw) != size or len(raw) > 4096:
            raise BuildError("cpu_startup_contract_changed_or_too_large")
    obj = strict_json(raw)
    closed(obj, "schema_version module argv")
    if obj["schema_version"] != "episode1.cpu-startup.v1":
        raise BuildError("invalid_cpu_startup_contract")
    if obj["argv"] != ["--help"]:
        raise BuildError("unsafe_cpu_startup_argv")
    if obj["module"] != "runpod_benchmark.episode1_remote_control":
        raise BuildError("invalid_cpu_startup_module")
    return obj


def lock_packages(raw):
    """Retain each package's allowed wheel bytes, not just its hash count."""
    text = raw.decode("utf-8", "strict")
    result, current, binary, index = {}, None, False, False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == "--only-binary :all:":
            if current:
                raise BuildError("late_lock_option")
            binary = True
            continue
        if s.startswith(("--index-url ", "--extra-index-url ")):
            if current:
                raise BuildError("late_lock_option")
            https(s.split(maxsplit=1)[1]); index = True
            continue
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*\\", s)
        if m:
            current = canonicalize_name(m[1])
            if current in result:
                raise BuildError("duplicate_lock_package")
            result[current] = {"version": str(Version(m[2])), "hashes": set()}
            continue
        m = re.fullmatch(r"--hash=sha256:([0-9a-f]{64})(?:\s*\\)?", s)
        if current and m:
            result[current]["hashes"].add(m[1]); continue
        raise BuildError("unsupported_lock_line")
    if not binary or not index or not result or any(not v["hashes"] for v in result.values()):
        raise BuildError("incomplete_lock")
    return result


def validate_runtime_lock(runtime, lock_raw, locked):
    """Bind the complete retained lock and independently assert its key roots."""
    policy = RUNTIME_POLICY[runtime]
    if digest(lock_raw) != policy["lock_sha256"]:
        raise BuildError("unexpected_runtime_lock")
    if len(locked) != policy["package_count"]:
        raise BuildError("unexpected_runtime_package_count")
    for name, version in policy["required"].items():
        if name not in locked or locked[name]["version"] != version:
            raise BuildError("missing_required_runtime_package")


def validate_uv_binary(path, declared_version, source_url):
    """Statically identify the staged Linux amd64 uv executable; never run it."""
    if declared_version != "0.12.3":
        raise BuildError("unexpected_uv_version")
    parsed = urllib.parse.urlsplit(source_url)
    expected = re.fullmatch(
        r"/astral-sh/uv/releases/download/v?0\.12\.3/uv-x86_64-unknown-linux-(?:gnu|musl)\.tar\.gz",
        parsed.path,
    )
    if parsed.hostname != "github.com" or expected is None:
        raise BuildError("unexpected_uv_origin")
    size = path.stat().st_size
    if size < 64 or size > 128 * 1024 * 1024:
        raise BuildError("invalid_uv_elf")
    with path.open("rb") as stream:
        header = stream.read(64)
        if (len(header) != 64 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1 or
                header[6] != 1 or struct.unpack_from("<H", header, 16)[0] not in {2, 3} or
                struct.unpack_from("<H", header, 18)[0] != 62):
            raise BuildError("invalid_uv_elf")
        # Rust embeds its package version in the release executable. This is
        # supporting evidence; the retained SHA-256 remains the byte identity.
        needle, tail, found = declared_version.encode(), b"", False
        while chunk := stream.read(1024 * 1024):
            data = tail + chunk
            if needle in data:
                found = True
                break
            tail = data[-len(needle):]
    if not found:
        raise BuildError("uv_version_evidence_missing")


def _ar_members(path):
    """Read ordinary Debian ar members with strict names and bounded control data."""
    archive_size = path.stat().st_size
    with path.open("rb") as stream:
        if stream.read(8) != b"!<arch>\n":
            raise BuildError("invalid_deb_archive")
        seen = set()
        while True:
            header = stream.read(60)
            if not header:
                return
            if len(header) != 60 or header[58:] != b"`\n":
                raise BuildError("invalid_deb_archive")
            try:
                name = header[:16].decode("ascii").rstrip()
                length_text = header[48:58].decode("ascii").strip()
                if not length_text.isdigit():
                    raise ValueError
                length = int(length_text)
            except (UnicodeError, ValueError) as exc:
                raise BuildError("invalid_deb_archive") from exc
            name = name[:-1] if name.endswith("/") else name
            if not name or name.startswith(("/", "#1/")) or name in seen:
                raise BuildError("unsupported_deb_archive")
            seen.add(name)
            if name.startswith("control.tar") and length > 16 * 1024 * 1024:
                raise BuildError("oversized_deb_control")
            if stream.tell() + length > archive_size:
                raise BuildError("truncated_deb_archive")
            if name == "debian-binary":
                if length > 64:
                    raise BuildError("invalid_deb_archive")
                data = stream.read(length)
            elif name.startswith("control.tar"):
                data = stream.read(length)
            else:
                stream.seek(length, os.SEEK_CUR)
                data = None
            if length % 2 and stream.read(1) != b"\n":
                raise BuildError("invalid_deb_padding")
            yield name, data


def trusted_zstandard():
    """Load only the pinned decoder installed inside this Python environment."""
    try:
        distribution = importlib.metadata.distribution("zstandard")
    except importlib.metadata.PackageNotFoundError as exc:
        raise BuildError("zstandard_dependency_unavailable") from exc
    if distribution.version != ZSTANDARD_VERSION:
        raise BuildError("zstandard_dependency_unavailable")
    distribution_root = Path(distribution.locate_file("")).resolve()
    interpreter_root = Path(sys.prefix).resolve()
    try:
        distribution_root.relative_to(interpreter_root)
    except ValueError as exc:
        raise BuildError("untrusted_zstandard_dependency") from exc
    spec = importlib.util.find_spec("zstandard")
    if spec is None or spec.origin is None:
        raise BuildError("zstandard_dependency_unavailable")
    try:
        Path(spec.origin).resolve().relative_to(distribution_root)
    except ValueError as exc:
        raise BuildError("untrusted_zstandard_dependency") from exc
    module = importlib.import_module("zstandard")
    if getattr(module, "__version__", None) != ZSTANDARD_VERSION:
        raise BuildError("zstandard_dependency_unavailable")
    return module


def bounded_control_tar(name, raw):
    """Return uncompressed tar bytes under one format-independent ceiling."""
    try:
        if name == "control.tar.gz":
            stream = gzip.GzipFile(fileobj=io.BytesIO(raw))
        elif name == "control.tar.xz":
            stream = lzma.LZMAFile(io.BytesIO(raw))
        elif name == "control.tar.zst":
            zstandard = trusted_zstandard()
            stream = zstandard.ZstdDecompressor(
                max_window_size=MAX_DEB_CONTROL_DECOMPRESSED // 1024
            ).stream_reader(io.BytesIO(raw))
        else:
            return raw
        try:
            expanded = stream.read(MAX_DEB_CONTROL_DECOMPRESSED + 1)
        finally:
            stream.close()
    except BuildError:
        raise
    except ImportError as exc:
        raise BuildError("zstandard_dependency_unavailable") from exc
    except Exception as exc:
        # The pinned zstandard extension and stdlib codecs expose different
        # concrete decoder exceptions; none are meaningful outside this gate.
        raise BuildError("invalid_deb_control") from exc
    if len(expanded) > MAX_DEB_CONTROL_DECOMPRESSED:
        raise BuildError("oversized_deb_control")
    return expanded


def deb_control(path):
    members = list(_ar_members(path))
    versions = [raw for name, raw in members if name == "debian-binary"]
    control_archives = [(name, raw) for name, raw in members if name.startswith("control.tar")]
    data_archives = [name for name, _ in members if name.startswith("data.tar")]
    accepted_data = {"data.tar", "data.tar.gz", "data.tar.xz", "data.tar.zst", "data.tar.bz2", "data.tar.lzma"}
    if versions != [b"2.0\n"] or len(data_archives) != 1 or data_archives[0] not in accepted_data:
        raise BuildError("invalid_deb_archive")
    if len(control_archives) != 1:
        raise BuildError("missing_deb_control")
    name, raw = control_archives[0]
    if name not in {"control.tar", "control.tar.gz", "control.tar.xz", "control.tar.zst"}:
        raise BuildError("unsupported_deb_control_compression")
    raw = bounded_control_tar(name, raw)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            controls = [m for m in members if m.name.removeprefix("./") == "control"]
            if len(members) > 4096 or len(controls) != 1 or not controls[0].isfile() or controls[0].size > 1024 * 1024:
                raise BuildError("invalid_deb_control")
            control_raw = archive.extractfile(controls[0]).read()
    except (tarfile.TarError, OSError) as exc:
        raise BuildError("invalid_deb_control") from exc
    try:
        text = control_raw.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise BuildError("invalid_deb_control") from exc
    fields, current = {}, None
    for line in text.splitlines():
        if line.startswith((" ", "\t")):
            if current is None:
                raise BuildError("invalid_deb_control")
            fields[current] += "\n" + line[1:]
            continue
        if not line:
            current = None
            continue
        if ": " not in line:
            raise BuildError("invalid_deb_control")
        key, value = line.split(": ", 1)
        if key in fields:
            raise BuildError("invalid_deb_control")
        fields[key] = value
        current = key
    if not all(isinstance(fields.get(k), str) and fields[k] for k in ("Package", "Version", "Architecture")):
        raise BuildError("invalid_deb_control")
    return {"name": fields["Package"], "version": fields["Version"], "architecture": fields["Architecture"]}


_TARGET_PLATFORMS = ([f"manylinux_2_{minor}_x86_64" for minor in range(39, 4, -1)] +
                     ["manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64", "linux_x86_64"])
_TARGET_TAGS = (set(cpython_tags((3, 12), platforms=_TARGET_PLATFORMS)) |
                set(compatible_tags((3, 12), interpreter="cp312", platforms=_TARGET_PLATFORMS)))


def compatible_target_wheel(tags):
    return bool(set(tags) & _TARGET_TAGS)


def git_head(root):
    """Resolve a loose or packed HEAD without invoking code from the checkout."""
    marker = root / ".git"
    if marker.is_dir():
        gitdir = marker
    elif marker.is_file():
        line = marker.read_text("utf-8").strip()
        if not line.startswith("gitdir: "):
            raise BuildError("invalid_git_metadata")
        candidate = Path(line[8:])
        gitdir = candidate if candidate.is_absolute() else (root / candidate).resolve()
    else:
        raise BuildError("missing_git_metadata")
    head = (gitdir / "HEAD").read_text("ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", head):
        return head
    if not head.startswith("ref: ") or not re.fullmatch(r"refs/[A-Za-z0-9._/-]+", head[5:]) or ".." in head[5:].split("/"):
        raise BuildError("invalid_git_head")
    ref = head[5:]
    loose = gitdir / ref
    if loose.is_file():
        value = loose.read_text("ascii").strip()
    else:
        value = None
        common = gitdir
        commondir = gitdir / "commondir"
        if commondir.is_file():
            relative = Path(commondir.read_text("utf-8").strip())
            common = relative if relative.is_absolute() else (gitdir / relative).resolve()
        common_loose = common / ref
        if common_loose.is_file():
            value = common_loose.read_text("ascii").strip()
        for packed in (gitdir / "packed-refs", common / "packed-refs"):
            if value:
                break
            if packed.is_file():
                for line in packed.read_text("ascii").splitlines():
                    if line and not line.startswith(("#", "^")):
                        candidate, name = line.split(" ", 1)
                        if name == ref:
                            value = candidate
                            break
            if value:
                break
        if value is None:
            raise BuildError("missing_git_ref")
    if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", value):
        raise BuildError("invalid_git_commit")
    return value


def validate_manifest(manifest, root, *, bind_source=False):
    closed(manifest, "schema_version platform base_image source_commit builder tooling installer system_packages runtimes materials")
    if manifest["schema_version"] != "episode1.build-input.v1" or manifest["platform"] != "linux/amd64" or manifest["base_image"] != BASE:
        raise BuildError("unsupported_build_identity")
    if not isinstance(manifest["source_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", manifest["source_commit"]):
        raise BuildError("invalid_source_commit")
    if bind_source and git_head(root) != manifest["source_commit"]:
        raise BuildError("source_commit_mismatch")
    builder = closed(manifest["builder"], "docker_version_sha256 buildx_version_sha256 builder_inspect_sha256 sbom_generator")
    for key in ("docker_version_sha256", "buildx_version_sha256", "builder_inspect_sha256"): sha(builder[key])
    if not isinstance(builder["sbom_generator"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]+@sha256:[0-9a-f]{64}", builder["sbom_generator"]):
        raise BuildError("unpinned_sbom_generator")
    tooling = closed(manifest["tooling"], "build_tool_sha256 cpu_smoke_sha256")
    if (sha(tooling["build_tool_sha256"]) != hashfile(Path(__file__)) or
            sha(tooling["cpu_smoke_sha256"]) != hashfile(Path(__file__).with_name("episode1_cpu_smoke.py"))):
        raise BuildError("build_tooling_changed")
    installer = closed(manifest["installer"], "version path sha256 source_url")
    https(installer["source_url"])
    validate_uv_binary(verify_file(root, installer), installer["version"], installer["source_url"])
    materials = manifest["materials"]
    if not isinstance(materials, list) or not materials: raise BuildError("empty_materials")
    seen = set()
    for item in materials:
        closed(item, "path sha256")
        p = rel(item["path"])
        if p in seen or not (p.startswith(PACKAGE_PREFIX) and p.endswith(".py") or
                             p.startswith("schemas/episode1-") and p.endswith(".json") or
                             p.startswith("runtime/episode1/") and p.endswith((".sh", ".json"))):
            raise BuildError("unapproved_material_path")
        seen.add(p); verify_file(root, item)
    if not REQUIRED <= seen: raise BuildError("missing_required_source")
    startup = cpu_startup_contract(root, seen)
    validate_import_closure(root, seen, entry_module=startup["module"])
    packages = manifest["system_packages"]
    if not isinstance(packages, list) or not packages: raise BuildError("empty_system_packages")
    names = set()
    for item in packages:
        closed(item, "name version architecture path sha256 source_url")
        if not isinstance(item["name"], str) or not NAME.fullmatch(item["name"]) or item["name"] in names:
            raise BuildError("invalid_system_package")
        names.add(item["name"])
        if not isinstance(item["version"], str) or not re.fullmatch(r"[A-Za-z0-9.+:~_-]+", item["version"]):
            raise BuildError("invalid_system_version")
        if item["architecture"] not in {"amd64", "all"} or not item["path"].endswith(".deb"):
            raise BuildError("invalid_deb")
        https(item["source_url"])
        observed = deb_control(verify_file(root, item))
        if observed != {"name": item["name"], "version": item["version"], "architecture": item["architecture"]}:
            raise BuildError("deb_metadata_mismatch")
    if not {"python3.12", "python3.12-venv", "openssh-server", "ca-certificates"} <= names:
        raise BuildError("missing_required_system_package")
    runtimes = manifest["runtimes"]
    if not isinstance(runtimes, list) or len(runtimes) != 2: raise BuildError("invalid_runtime_pair")
    runtime_names = set()
    for runtime in runtimes:
        closed(runtime, "runtime lock_path lock_sha256 wheels")
        name = runtime["runtime"]
        if name not in {"vllm", "sglang"} or name in runtime_names: raise BuildError("invalid_runtime_pair")
        runtime_names.add(name)
        lp = verify_file(root, {"path": runtime["lock_path"], "sha256": runtime["lock_sha256"]})
        lock_raw = lp.read_bytes()
        locked = lock_packages(lock_raw)
        if runtime["lock_sha256"] != RUNTIME_POLICY[name]["lock_sha256"]:
            raise BuildError("unexpected_runtime_lock")
        validate_runtime_lock(name, lock_raw, locked)
        wheels = runtime["wheels"]
        if not isinstance(wheels, list): raise BuildError("invalid_wheel_inventory")
        selected = set()
        for item in wheels:
            closed(item, "name version filename path sha256 index_url source_url")
            https(item["index_url"]); https(item["source_url"])
            path = verify_file(root, item)
            if path.name != item["filename"] or rel(item["filename"]) != path.name:
                raise BuildError("wheel_filename_mismatch")
            try:
                n, v, _, tags = parse_wheel_filename(item["filename"])
            except Exception as exc: raise BuildError("invalid_wheel_filename") from exc
            if (n != item["name"] or str(v) != item["version"] or n in selected or n not in locked or
                    locked[n]["version"] != str(v) or item["sha256"] not in locked[n]["hashes"]):
                raise BuildError("wheel_not_bound_by_lock")
            if not compatible_target_wheel(tags):
                raise BuildError("wheel_incompatible_with_target")
            with zipfile.ZipFile(path) as archive:
                names_in_zip = archive.namelist()
                if any(PurePosixPath(x).is_absolute() or ".." in PurePosixPath(x).parts for x in names_in_zip):
                    raise BuildError("unsafe_wheel_member")
                metadata = [x for x in names_in_zip if x.endswith(".dist-info/METADATA")]
                if len(metadata) != 1: raise BuildError("invalid_wheel_metadata")
                from email.parser import BytesParser
                msg = BytesParser().parsebytes(archive.read(metadata[0]))
                if canonicalize_name(msg["Name"] or "") != n or str(Version(msg["Version"])) != str(v):
                    raise BuildError("wheel_metadata_mismatch")
            selected.add(n)
        if selected != set(locked): raise BuildError("incomplete_selected_wheels")
    return digest(canonical(manifest))


def private_write(path, raw, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True); raise


def dockerfile_bytes(manifest, manifest_sha):
    return f'''FROM {BASE} AS runtime
ENV PYTHONNOUSERSITE=1 PYTHONPATH=/opt/episode1 HUMMING_COMPILER=nvrtc
COPY payload/materials/src/runpod_benchmark /opt/episode1/runpod_benchmark
COPY payload/materials/runtime/episode1/entrypoint.sh /usr/local/bin/episode1-entrypoint
COPY payload/materials/runtime/episode1/control.sh /usr/local/bin/episode1-control
COPY Dockerfile /opt/episode1/build-spec/Dockerfile
COPY payload/materials /opt/episode1/materials
COPY payload/manifest.json payload/cpu_smoke.py /opt/episode1/
COPY payload/locks /locks
RUN --network=none --mount=type=bind,source=payload,target=/build,ro \\
    dpkg -i /build/debs/*.deb \\
 && rm -f /etc/ssh/ssh_host_* \\
 && install -m 0755 /build/uv /usr/local/bin/uv \\
 && chmod 0755 /usr/local/bin/episode1-entrypoint /usr/local/bin/episode1-control \\
 && python3.12 -m venv --without-pip /opt/venvs/vllm \\
 && python3.12 -m venv --without-pip /opt/venvs/sglang \\
 && uv pip sync --python /opt/venvs/vllm/bin/python --require-hashes --no-index --find-links /build/wheels/vllm /locks/vllm.lock \\
 && uv pip sync --python /opt/venvs/sglang/bin/python --require-hashes --no-index --find-links /build/wheels/sglang /locks/sglang.lock \\
 && rm -rf /root/.cache/uv \\
 && python3.12 /opt/episode1/cpu_smoke.py --manifest-sha256 {manifest_sha}
EXPOSE 22
ENTRYPOINT ["/usr/local/bin/episode1-entrypoint"]
'''.encode()


def expected_context_files(manifest):
    result = {"Dockerfile": digest(dockerfile_bytes(manifest, digest(canonical(manifest)))),
              ".dockerignore": digest(b"*\n!Dockerfile\n!payload\n!payload/**\n"),
              "payload/manifest.json": digest(canonical(manifest)),
              "payload/cpu_smoke.py": manifest["tooling"]["cpu_smoke_sha256"],
              "payload/uv": manifest["installer"]["sha256"]}
    for item in manifest["materials"]: result["payload/materials/" + rel(item["path"])] = sha(item["sha256"])
    for n, item in enumerate(manifest["system_packages"]): result[f"payload/debs/{n:04d}.deb"] = sha(item["sha256"])
    for runtime in manifest["runtimes"]:
        rt = runtime["runtime"]
        if rt not in {"vllm", "sglang"}: raise BuildError("invalid_runtime_pair")
        result[f"payload/locks/{rt}.lock"] = sha(runtime["lock_sha256"])
        for item in runtime["wheels"]: result[f"payload/wheels/{rt}/" + rel(item["filename"])] = sha(item["sha256"])
    return result


def prepare(manifest, root, output):
    # The free-standing `validate` command can check a staged tree. Preparing a
    # build context additionally binds source_commit to the checkout supplying it.
    manifest_sha = validate_manifest(manifest, root, bind_source=True)
    if output.exists(): raise BuildError("context_already_exists")
    smoke = Path(__file__).with_name("episode1_cpu_smoke.py").read_bytes()
    generated = [canonical(manifest), smoke, dockerfile_bytes(manifest, manifest_sha),
                 b"*\n!Dockerfile\n!payload\n!payload/**\n"]
    records = list(manifest["materials"]) + [manifest["installer"]] + list(manifest["system_packages"])
    for runtime in manifest["runtimes"]:
        records.append({"path": runtime["lock_path"], "sha256": runtime["lock_sha256"]})
        records.extend(runtime["wheels"])
    planned_sizes = [regular(root, record["path"]).stat().st_size for record in records] + [len(raw) for raw in generated]
    planned_total = 0
    for count, size in enumerate(planned_sizes, 1):
        planned_total += size; check_budget("context", count, planned_total, size)
    # Reserve the maximum accepted receipt before creating or copying anything.
    check_budget("context", len(planned_sizes) + 1,
                 planned_total + RESOURCE_BOUNDS["oci_json_bytes"], RESOURCE_BOUNDS["oci_json_bytes"])
    output.mkdir(mode=0o700, parents=True)
    copied_count = copied_total = 0
    def observe(size):
        nonlocal copied_count, copied_total
        copied_count += 1; copied_total += size
        check_budget("context", copied_count, copied_total, size)
    def copy(record, target, mode=0o600):
        source = verify_file(root, record)
        # Reserve the opened size, then copy exactly that many bounded chunks.
        # A growing source cannot consume more context disk than was budgeted.
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with source.open("rb") as src, target.open("xb") as dst:
            opened_size = os.fstat(src.fileno()).st_size
            observe(opened_size)
            copy_exact(src, dst, opened_size)
            if os.fstat(src.fileno()).st_size != opened_size:
                raise BuildError("material_changed_while_copying")
        os.chmod(target, mode)
        if hashfile(target) != record["sha256"]: raise BuildError("material_changed_while_copying")
    for item in manifest["materials"]: copy(item, output / "payload/materials" / item["path"])
    copy(manifest["installer"], output / "payload/uv", 0o755)
    for n, item in enumerate(manifest["system_packages"]): copy(item, output / f"payload/debs/{n:04d}.deb")
    for rt in manifest["runtimes"]:
        copy({"path": rt["lock_path"], "sha256": rt["lock_sha256"]}, output / f"payload/locks/{rt['runtime']}.lock")
        for item in rt["wheels"]: copy(item, output / f"payload/wheels/{rt['runtime']}" / item["filename"])
    for path, raw in zip((output / "payload/manifest.json", output / "payload/cpu_smoke.py",
                          output / "Dockerfile", output / ".dockerignore"), generated):
        observe(len(raw)); private_write(path, raw)
    inventory = {str(p.relative_to(output)): hashfile(p) for p in sorted(output.rglob("*")) if p.is_file()}
    receipt = sealed({"schema_version": "episode1.build-context.v2", "manifest_sha256": manifest_sha,
                      "tool_sha256": hashfile(Path(__file__)), "files": inventory,
                      "resource_bounds": RESOURCE_BOUNDS})
    receipt_raw = canonical(receipt); observe(len(receipt_raw))
    private_write(output / "context-receipt.json", receipt_raw)
    return receipt


def run_checked(argv, *, cwd, timeout, stdout=None, stdin=None):
    # All command output is private; the CLI reports only a closed failure reason.
    try:
        cp = subprocess.run(argv, cwd=cwd, stdin=stdin if stdin is not None else subprocess.DEVNULL, stdout=stdout or subprocess.PIPE,
                            stderr=subprocess.STDOUT if stdout else subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc: raise BuildError("external_command_unavailable_or_timeout") from exc
    if cp.returncode: raise BuildError("external_command_failed")
    return cp.stdout or b""


def context_snapshot(context):
    """Pass a verified anonymous tar FD, never a mutable directory, to BuildKit."""
    receipt_path = regular(context, "context-receipt.json")
    if receipt_path.stat().st_size > RESOURCE_BOUNDS["oci_json_bytes"]: raise BuildError("resource_bound_exceeded")
    receipt = closed(strict_json(receipt_path.read_bytes()),
                     "schema_version manifest_sha256 tool_sha256 files resource_bounds artifact_sha256")
    verify_seal(receipt)
    if (receipt["schema_version"] != "episode1.build-context.v2" or
            receipt["resource_bounds"] != RESOURCE_BOUNDS or not isinstance(receipt["files"], dict)):
        raise BuildError("invalid_context_receipt")
    sha(receipt["manifest_sha256"])
    if receipt["tool_sha256"] != hashfile(Path(__file__)): raise BuildError("build_tooling_changed")
    expected_files = receipt["files"]
    if not {"Dockerfile", ".dockerignore", "payload/manifest.json", "payload/cpu_smoke.py"} <= set(expected_files):
        raise BuildError("incomplete_context_receipt")
    total = receipt_path.stat().st_size
    check_budget("context", 1, total, total)
    for count, (name, expected) in enumerate(expected_files.items(), 2):
        rel(name); sha(expected)
        path = regular(context, name); size = path.stat().st_size; total += size
        check_budget("context", count, total, size)
    def check_membership():
        actual = set()
        for p in context.rglob("*"):
            if p.is_symlink(): raise BuildError("symlink_material")
            if not p.is_dir(): actual.add(str(p.relative_to(context)))
        if actual != set(expected_files) | {"context-receipt.json"}: raise BuildError("context_membership_changed")
    check_membership()
    manifest = strict_json(regular(context, "payload/manifest.json").read_bytes())
    if digest(canonical(manifest)) != receipt["manifest_sha256"]: raise BuildError("context_manifest_changed")
    if (manifest["tooling"]["build_tool_sha256"] != receipt["tool_sha256"] or
            expected_files["payload/cpu_smoke.py"] != manifest["tooling"]["cpu_smoke_sha256"]):
        raise BuildError("build_tooling_changed")
    if expected_files != expected_context_files(manifest): raise BuildError("context_not_derived_from_manifest")
    # TemporaryFile is unlinked on Unix. The only builder input is this read FD.
    snapshot = tempfile.TemporaryFile()
    try:
        with tarfile.open(fileobj=snapshot, mode="w") as tar:
            snapshot_count, snapshot_total = 1, receipt_path.stat().st_size
            check_budget("context", snapshot_count, snapshot_total, snapshot_total)
            for name, expected in sorted(expected_files.items()):
                path = regular(context, name)
                with path.open("rb") as src:
                    size = os.fstat(src.fileno()).st_size
                    snapshot_count += 1; snapshot_total += size
                    check_budget("context", snapshot_count, snapshot_total, size)
                    h = hashlib.sha256()
                    class Reader:
                        def read(self, count=-1):
                            raw = src.read(count); h.update(raw); return raw
                    member = tarfile.TarInfo(name); member.size = size
                    member.mode = 0o755 if name == "payload/uv" else 0o600
                    tar.addfile(member, Reader())
                    if src.read(1) or h.hexdigest() != expected: raise BuildError("context_changed_while_snapshotting")
        check_membership()
        snapshot.seek(0); snapshot_sha = hashlib.sha256()
        for chunk in iter(lambda: snapshot.read(1024 * 1024), b""): snapshot_sha.update(chunk)
        snapshot.seek(0)
        return snapshot, receipt, manifest, snapshot_sha.hexdigest()
    except BaseException:
        snapshot.close(); raise


def build(context, output, timeout):
    """Explicit external builder entry point; never called by prepare/validate."""
    if type(timeout) is not int or not 1 <= timeout <= 14400: raise BuildError("invalid_build_timeout")
    snapshot, receipt, manifest, snapshot_sha = context_snapshot(context)
    with snapshot:
        # No new builder is created. Operator must supply an authorized existing builder.
        for args, field in ((["docker", "version", "--format", "{{json .}}"], "docker_version_sha256"),
                            (["docker", "buildx", "version"], "buildx_version_sha256"),
                            (["docker", "buildx", "inspect"], "builder_inspect_sha256")):
            if digest(run_checked(args, cwd="/", timeout=30)) != manifest["builder"][field]:
                raise BuildError("builder_identity_mismatch")
        if output.exists(): raise BuildError("build_output_already_exists")
        output.mkdir(mode=0o700, parents=True)
        log = output / "build.log"
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        argv = ["docker", "buildx", "build", "--platform", "linux/amd64", "--network", "none",
                "--provenance=mode=max,version=v0.2", "--attest", f"type=sbom,generator={manifest['builder']['sbom_generator']}",
                "--metadata-file", str(output / "metadata.json"),
                "--output", f"type=oci,oci-artifact=true,dest={output / 'image.oci.tar'}", "-"]
        with os.fdopen(fd, "wb") as log_file:
            run_checked(argv,
                        cwd="/", timeout=timeout, stdout=log_file, stdin=snapshot)
        for p in output.iterdir():
            if p.is_file(): os.chmod(p, 0o600)
        image_path, metadata_path = output / "image.oci.tar", output / "metadata.json"
        if (not image_path.is_file() or not metadata_path.is_file() or
                image_path.is_symlink() or metadata_path.is_symlink()): raise BuildError("missing_build_output")
        if (image_path.stat().st_size > RESOURCE_BOUNDS["oci_archive_bytes"] or
                metadata_path.stat().st_size > RESOURCE_BOUNDS["oci_json_bytes"]): raise BuildError("resource_bound_exceeded")
        build_receipt = sealed({
            "schema_version": "episode1.build-receipt.v1",
            "manifest_sha256": receipt["manifest_sha256"],
            "context_receipt_sha256": receipt["artifact_sha256"],
            "context_snapshot_sha256": snapshot_sha,
            "oci_archive_sha256": hashfile(image_path),
            "metadata_sha256": hashfile(metadata_path),
            "actual_argv_sha256": digest(canonical(argv)),
            "invocation": {**BUILD_INVOCATION, "sbom_generator": manifest["builder"]["sbom_generator"]},
            "builder_identity_sha256": {key: manifest["builder"][key] for key in
                                        ("docker_version_sha256", "buildx_version_sha256", "builder_inspect_sha256")},
            "resource_bounds": RESOURCE_BOUNDS,
            "trust": "unsigned_local_observation",
        })
        private_write(output / "build-receipt.json", canonical(build_receipt))
        return inspect_oci(image_path, receipt["manifest_sha256"], build_receipt)


def validate_cpu_report(report, manifest, image_files):
    closed(report, "schema_version status manifest_sha256 platform python_version materials system_inventory dependencies host_keys_present gpu_validation")
    if (report["schema_version"] != "episode1.cpu-smoke.v1" or report["status"] != "pass" or
            report["manifest_sha256"] != digest(canonical(manifest)) or report["platform"] != "linux/amd64" or
            not re.fullmatch(r"3\.12\.[0-9]+", str(report["python_version"])) or
            report["host_keys_present"] is not False or report["gpu_validation"] != "not_run"):
        raise BuildError("invalid_cpu_report")
    if report["materials"] != manifest["materials"]: raise BuildError("cpu_material_inventory_mismatch")
    inventory = report["system_inventory"]
    if not isinstance(inventory, list): raise BuildError("invalid_system_inventory")
    identities = set()
    for package in inventory:
        closed(package, "name version architecture")
        if not all(isinstance(v, str) and v for v in package.values()): raise BuildError("invalid_system_inventory")
        ident = (package["name"], package["architecture"])
        if ident in identities: raise BuildError("duplicate_system_inventory")
        identities.add(ident)
    for package in manifest["system_packages"]:
        if {k: package[k] for k in ("name", "version", "architecture")} not in inventory:
            raise BuildError("system_package_mismatch")
    dependencies = report["dependencies"]
    if not isinstance(dependencies, list) or len(dependencies) != 2: raise BuildError("missing_dependency_reports")
    by_runtime = {}
    for dep in dependencies:
        closed(dep, "schema_version status runtime lock_sha256 lock_package_count installed_package_count bootstrap_allowlist inventory active_dependency_checks allowed_dependency_mismatches errors python_version platform bootstrap_manifest_sha256")
        if (dep["runtime"] in by_runtime or dep["runtime"] not in {"vllm", "sglang"} or
                dep["schema_version"] != "episode1.dependency-validation.v1" or dep["status"] != "pass" or
                dep["errors"] != [] or dep["bootstrap_allowlist"] != [] or dep["bootstrap_manifest_sha256"] is not None or
                dep["platform"] != "linux-x86_64" or dep["python_version"] != report["python_version"] or
                type(dep["active_dependency_checks"]) is not int or dep["active_dependency_checks"] <= 0):
            raise BuildError("invalid_dependency_report")
        by_runtime[dep["runtime"]] = dep
    for runtime in manifest["runtimes"]:
        rt = runtime["runtime"]; dep = by_runtime[rt]
        lock_raw = image_files.get(f"locks/{rt}.lock", {}).get("raw")
        if lock_raw is None or digest(lock_raw) != runtime["lock_sha256"]: raise BuildError("installed_lock_mismatch")
        locked = lock_packages(lock_raw)
        validate_runtime_lock(rt, lock_raw, locked)
        expected = [{"name": name, "version": item["version"]} for name, item in sorted(locked.items())]
        if (dep["lock_sha256"] != runtime["lock_sha256"] or dep["inventory"] != expected or
                type(dep["lock_package_count"]) is not int or dep["lock_package_count"] != len(locked) or
                type(dep["installed_package_count"]) is not int or dep["installed_package_count"] != len(locked)):
            raise BuildError("dependency_inventory_mismatch")
        mismatches = dep["allowed_dependency_mismatches"]
        expected_mismatch = ([] if rt == "vllm" else [{"package": "torch", "dependency": "nvidia-nccl-cu13", "required": "==2.29.7", "marker": 'sys_platform == "linux"', "installed": "2.30.7"}])
        if mismatches != expected_mismatch: raise BuildError("dependency_exception_mismatch")
    expected_files = {"opt/episode1/cpu_smoke.py": manifest["tooling"]["cpu_smoke_sha256"],
                      "usr/local/bin/uv": manifest["installer"]["sha256"]}
    for item in manifest["materials"]:
        expected_files["opt/episode1/materials/" + rel(item["path"])] = item["sha256"]
        if item["path"].startswith("src/runpod_benchmark/"):
            expected_files["opt/episode1/" + item["path"].removeprefix("src/")] = item["sha256"]
        if item["path"] == "runtime/episode1/entrypoint.sh": expected_files["usr/local/bin/episode1-entrypoint"] = item["sha256"]
        if item["path"] == "runtime/episode1/control.sh": expected_files["usr/local/bin/episode1-control"] = item["sha256"]
    expected_files["opt/episode1/build-spec/Dockerfile"] = digest(
        dockerfile_bytes(manifest, digest(canonical(manifest)))
    )
    for path, expected in expected_files.items():
        if image_files.get(path, {}).get("sha256") != expected: raise BuildError("final_image_material_mismatch")


def _remove_subtree(tree, path, *, descendants=True):
    for old in list(tree):
        if old == path or (descendants and old.startswith(path + "/")):
            del tree[old]


def _apply_layer(tree, nodes, whiteouts, opaque):
    # Whiteouts apply only to the lower filesystem; same-layer additions are
    # installed afterwards regardless of tar member order.
    for path in whiteouts: _remove_subtree(tree, path)
    for path in opaque:
        for old in list(tree):
            if not path or old.startswith(path + "/"): del tree[old]
    for path, node in nodes:
        parts = path.split("/")
        for n in range(1, len(parts)):
            ancestor = "/".join(parts[:n])
            existing = tree.get(ancestor)
            if existing is not None and existing["type"] != "directory":
                raise BuildError("non_directory_image_ancestor")
            if existing is None:
                tree[ancestor] = {"type": "directory", "mode": 0o755, "uid": 0, "gid": 0,
                                  "implicit": True}
        existing = tree.get(path)
        if node["type"] != "directory":
            _remove_subtree(tree, path)
        elif existing is not None and existing["type"] != "directory":
            del tree[path]
        tree[path] = node


def _tree_digest(tree):
    records = [{"path": path, **{k: v for k, v in tree[path].items() if k not in {"raw", "implicit"}}}
               for path in sorted(tree)]
    return digest(canonical(records))


def _node_metadata(member):
    try:
        finite_mtime = math.isfinite(float(member.mtime))
    except (TypeError, ValueError, OverflowError) as exc:
        raise BuildError("invalid_image_node_metadata") from exc
    if not finite_mtime:
        raise BuildError("invalid_image_node_metadata")
    pax = member.pax_headers
    if not isinstance(pax, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in pax.items()):
        raise BuildError("invalid_image_node_metadata")
    # Path/linkpath/size/ownership/time are reflected in the normalized TarInfo.
    # Preserve xattrs in the final tree digest. ACLs, file flags and sparse data
    # have extraction semantics this verifier does not model and fail closed.
    if any(k.startswith(("SCHILY.acl.", "SCHILY.fflags", "GNU.sparse")) or
           k in {"atime", "ctime"} for k in pax):
        raise BuildError("unsupported_image_node_metadata")
    xattrs = {k: v for k, v in sorted(pax.items())
              if k.startswith(("SCHILY.xattr.", "LIBARCHIVE.xattr."))}
    result = {"mode": member.mode & 0o7777, "uid": member.uid, "gid": member.gid,
              "mtime": str(member.mtime)}
    if xattrs: result["xattrs"] = xattrs
    return result


def _validate_build_receipt(receipt, archive_sha, manifest_sha, manifest):
    if receipt is None: return None
    closed(receipt, "schema_version manifest_sha256 context_receipt_sha256 context_snapshot_sha256 oci_archive_sha256 metadata_sha256 actual_argv_sha256 invocation builder_identity_sha256 resource_bounds trust artifact_sha256")
    verify_seal(receipt)
    for field in ("manifest_sha256", "context_receipt_sha256", "context_snapshot_sha256",
                  "oci_archive_sha256", "metadata_sha256", "actual_argv_sha256"):
        sha(receipt[field])
    expected_invocation = {**BUILD_INVOCATION, "sbom_generator": manifest["builder"]["sbom_generator"]}
    expected_builder = {key: manifest["builder"][key] for key in
                        ("docker_version_sha256", "buildx_version_sha256", "builder_inspect_sha256")}
    if (receipt["schema_version"] != "episode1.build-receipt.v1" or
            receipt["manifest_sha256"] != manifest_sha or receipt["oci_archive_sha256"] != archive_sha or
            receipt["invocation"] != expected_invocation or receipt["builder_identity_sha256"] != expected_builder or
            receipt["resource_bounds"] != RESOURCE_BOUNDS or receipt["trust"] != "unsigned_local_observation"):
        raise BuildError("build_receipt_binding_mismatch")
    return receipt["artifact_sha256"]


def inspect_oci(archive_path, expected_manifest_sha, build_receipt=None):
    """Verify a bounded OCI archive and its complete final filesystem tree.

    An optional sealed local receipt binds the immutable context snapshot and
    exact argv generated by :func:`build`. It is an unsigned local observation;
    BuildKit provenance is only checked for fields its v0.2 dialect emits.
    """
    sha(expected_manifest_sha)
    archive_path = Path(archive_path)
    archive_size = archive_path.stat().st_size
    if archive_size > RESOURCE_BOUNDS["oci_archive_bytes"]: raise BuildError("resource_bound_exceeded")
    archive_sha = hashfile(archive_path)
    with tarfile.open(archive_path, "r:*", tarinfo=BoundedTarInfo) as archive:
        members, outer_total = {}, 0
        for count, member in enumerate(archive, 1):
            outer_total += member.size; check_budget("outer", count, outer_total, member.size)
            name = tar_name(member.name, directory=member.isdir(), allow_root=True)
            if not name: continue
            if member.isdir(): continue
            if not member.isfile() or name in members: raise BuildError("unsafe_oci_archive")
            members[name] = member
            if name.startswith("blobs/sha256/"):
                claimed = sha(name.removeprefix("blobs/sha256/"))
                f = archive.extractfile(member); h = hashlib.sha256()
                for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
                if h.hexdigest() != claimed: raise BuildError("oci_blob_hash_mismatch")
        def raw(name, limit=None):
            limit = RESOURCE_BOUNDS["oci_json_bytes"] if limit is None else limit
            m = members.get(name)
            if m is None or m.size > limit: raise BuildError("missing_or_oversized_oci_object")
            return archive.extractfile(m).read()
        descriptor_count = 0
        def descriptor(desc):
            nonlocal descriptor_count
            descriptor_count += 1
            if descriptor_count > RESOURCE_BOUNDS["oci_descriptors"]: raise BuildError("resource_bound_exceeded")
            if not isinstance(desc, dict): raise BuildError("invalid_oci_descriptor")
            d = desc.get("digest", "")
            if not isinstance(d, str) or not d.startswith("sha256:"): raise BuildError("invalid_oci_descriptor")
            path = "blobs/sha256/" + sha(d[7:])
            if type(desc.get("size")) is not int or path not in members or members[path].size != desc["size"]:
                raise BuildError("oci_descriptor_size_mismatch")
            return path
        if strict_json(raw("oci-layout")) != {"imageLayoutVersion": "1.0.0"}: raise BuildError("invalid_oci_layout")
        index = strict_json(raw("index.json"))
        if index.get("schemaVersion") != 2 or not isinstance(index.get("manifests"), list): raise BuildError("invalid_oci_index")
        candidates, attestations = [], []
        pending = list(index["manifests"]); checked = set()
        while pending:
            desc = pending.pop(); path = descriptor(desc)
            if path in checked: raise BuildError("duplicate_or_cyclic_oci_descriptor")
            checked.add(path); obj = strict_json(raw(path))
            if obj.get("schemaVersion") != 2: raise BuildError("invalid_oci_manifest")
            if "manifests" in obj:
                if not isinstance(obj["manifests"], list): raise BuildError("invalid_oci_manifest")
                pending.extend(obj["manifests"]); continue
            if "config" not in obj or not isinstance(obj.get("layers"), list): raise BuildError("invalid_oci_manifest")
            if len(obj["layers"]) > RESOURCE_BOUNDS["oci_layers"]: raise BuildError("resource_bound_exceeded")
            config = strict_json(raw(descriptor(obj["config"])))
            for layer in obj["layers"]: descriptor(layer)
            if obj.get("artifactType") == "application/vnd.docker.attestation.manifest.v1+json":
                descriptor(obj.get("subject")); attestations.append((desc, obj))
            elif config.get("os") == "linux" and config.get("architecture") == "amd64": candidates.append((desc, obj, config))
        if len(candidates) != 1: raise BuildError("ambiguous_platform_image")
        desc, manifest, config = candidates[0]
        env = config.get("config", {}).get("Env", [])
        if not isinstance(env, list) or not all(isinstance(x, str) and "=" in x for x in env): raise BuildError("invalid_image_environment")
        env_names = [x.split("=", 1)[0] for x in env]
        if len(env_names) != len(set(env_names)): raise BuildError("duplicate_image_environment")
        if (config.get("config", {}).get("Entrypoint") != ["/usr/local/bin/episode1-entrypoint"] or
                not {"PYTHONNOUSERSITE=1", "HUMMING_COMPILER=nvrtc", "PYTHONPATH=/opt/episode1"} <= set(env)):
            raise BuildError("image_config_mismatch")
        rootfs = config.get("rootfs")
        if not isinstance(rootfs, dict) or rootfs.get("type") != "layers" or len(rootfs.get("diff_ids", [])) != len(manifest["layers"]):
            raise BuildError("invalid_rootfs_diff_ids")
        tree, total_uncompressed = {}, 0
        retain = {"opt/episode1/manifest.json", "opt/episode1/build-evidence/cpu-smoke.json", "locks/vllm.lock", "locks/sglang.lock"}
        for layer, diff_id in zip(manifest["layers"], rootfs["diff_ids"]):
            f = archive.extractfile(members[descriptor(layer)])
            media = layer.get("mediaType")
            if media == "application/vnd.oci.image.layer.v1.tar+gzip": stream = gzip.GzipFile(fileobj=f)
            elif media == "application/vnd.oci.image.layer.v1.tar": stream = f
            else: raise BuildError("unsupported_layer_compression")
            h, layer_bytes = hashlib.sha256(), 0
            class HashedReader:
                def read(self, count=-1):
                    nonlocal layer_bytes, total_uncompressed
                    data = stream.read(count); layer_bytes += len(data); total_uncompressed += len(data)
                    if (layer_bytes > RESOURCE_BOUNDS["oci_layer_uncompressed_bytes"] or
                            total_uncompressed > RESOURCE_BOUNDS["oci_total_uncompressed_bytes"]):
                        raise BuildError("resource_bound_exceeded")
                    h.update(data); return data
            reader = HashedReader(); nodes, whiteouts, opaque, seen = [], [], [], set(); member_total = 0
            with tarfile.open(fileobj=reader, mode="r|", tarinfo=BoundedTarInfo) as layer_tar:
                for member_count, member in enumerate(layer_tar, 1):
                    member_total += member.size; check_budget("layer", member_count, member_total, member.size)
                    name = tar_name(member.name, directory=member.isdir(), allow_root=True)
                    if not name: continue
                    if name in seen: raise BuildError("duplicate_image_layer_path")
                    seen.add(name)
                    parent, base = str(PurePosixPath(name).parent), PurePosixPath(name).name
                    parent = "" if parent == "." else parent
                    if base.startswith(".wh."):
                        if base == ".wh..wh..opq": opaque.append(parent)
                        else:
                            target = base[4:]
                            if not target: raise BuildError("unsafe_image_layer")
                            whiteouts.append(target if not parent else parent + "/" + target)
                        continue
                    common = _node_metadata(member)
                    if member.isdir(): node = {"type": "directory", **common}
                    elif member.isfile():
                        if name in retain and member.size > RESOURCE_BOUNDS["oci_evidence_bytes"]:
                            raise BuildError("oversized_image_evidence")
                        source = layer_tar.extractfile(member); fh = hashlib.sha256(); chunks = []
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            fh.update(chunk)
                            if name in retain: chunks.append(chunk)
                        node = {"type": "file", "sha256": fh.hexdigest(), **common}
                        if name in retain:
                            node["raw"] = b"".join(chunks)
                    elif member.issym(): node = {"type": "symlink", "linkname": member.linkname, **common}
                    elif member.islnk(): node = {"type": "hardlink", "linkname": tar_name(member.linkname), **common}
                    elif member.ischr(): node = {"type": "character", "devmajor": member.devmajor, "devminor": member.devminor, **common}
                    elif member.isblk(): node = {"type": "block", "devmajor": member.devmajor, "devminor": member.devminor, **common}
                    elif member.isfifo(): node = {"type": "fifo", **common}
                    else: raise BuildError("unsupported_image_node")
                    nodes.append((name, node))
            for _ in iter(lambda: reader.read(1024 * 1024), b""): pass
            if diff_id != "sha256:" + h.hexdigest(): raise BuildError("rootfs_diff_id_mismatch")
            stream.close(); _apply_layer(tree, nodes, whiteouts, opaque)
        for path in tree:
            if (path.startswith("etc/ssh/ssh_host_") or path == "root/.ssh/authorized_keys" or
                    path == "root/.cache/uv" or path.startswith("root/.cache/uv/")):
                raise BuildError("forbidden_final_image_artifact")
        image_files = tree
        report_raw = image_files.get("opt/episode1/build-evidence/cpu-smoke.json", {}).get("raw")
        manifest_raw = image_files.get("opt/episode1/manifest.json", {}).get("raw")
        if report_raw is None or manifest_raw is None: raise BuildError("missing_or_unbound_cpu_report")
        build_manifest = strict_json(manifest_raw); report = strict_json(report_raw)
        if digest(canonical(build_manifest)) != expected_manifest_sha: raise BuildError("missing_or_unbound_cpu_report")
        validate_cpu_report(report, build_manifest, image_files)
        receipt_sha = _validate_build_receipt(build_receipt, archive_sha, expected_manifest_sha, build_manifest)
        predicates = {}
        for att_desc, att in attestations:
            subject = att.get("subject")
            layers = att.get("layers")
            if not isinstance(subject, dict) or not isinstance(layers, list): raise BuildError("invalid_build_attestation")
            if subject.get("digest") != desc["digest"]: continue
            for layer in layers:
                if not isinstance(layer, dict): raise BuildError("invalid_build_attestation")
                if layer.get("mediaType") != "application/vnd.in-toto+json": continue
                statement = strict_json(raw(descriptor(layer), RESOURCE_BOUNDS["oci_attestation_bytes"]))
                kind = statement.get("predicateType")
                if kind not in {"https://slsa.dev/provenance/v0.2", "https://spdx.dev/Document"}: continue
                if kind in predicates: raise BuildError("duplicate_build_attestation")
                subjects = statement.get("subject")
                if (statement.get("_type") not in {"https://in-toto.io/Statement/v0.1", "https://in-toto.io/Statement/v1"} or
                        not isinstance(subjects, list) or
                        not any(isinstance(x, dict) and isinstance(x.get("digest"), dict) and
                                x["digest"].get("sha256") == desc["digest"][7:] for x in subjects)):
                    raise BuildError("unbound_build_attestation")
                predicate = statement.get("predicate")
                if not isinstance(predicate, dict): raise BuildError("invalid_build_attestation")
                if kind.endswith("/v0.2"):
                    materials = predicate.get("materials")
                    if (predicate.get("buildType") != "https://mobyproject.org/buildkit@v1" or
                            predicate.get("metadata", {}).get("completeness", {}).get("parameters") is not True or
                            not isinstance(materials, list) or
                            not any(isinstance(x, dict) and isinstance(x.get("digest"), dict) and
                                    x["digest"].get("sha256") == BASE.split("sha256:")[1] for x in materials)):
                        raise BuildError("incomplete_build_provenance")
                elif (predicate.get("SPDXID") != "SPDXRef-DOCUMENT" or
                      not str(predicate.get("spdxVersion", "")).startswith("SPDX-2.") or
                      not isinstance(predicate.get("packages"), list) or not predicate["packages"]):
                    raise BuildError("incomplete_build_sbom")
                predicates[kind] = layer["digest"]
        if len(predicates) != 2: raise BuildError("missing_build_attestations")
        return {"schema_version": "episode1.image-attestation.v2", "classification": "cpu_build_evidence" if receipt_sha else "unbound_cpu_build_inspection",
                "build_manifest_sha256": expected_manifest_sha, "image_manifest_digest": desc["digest"],
                "config_digest": manifest["config"]["digest"], "layer_digests": [x["digest"] for x in manifest["layers"]],
                "oci_archive_sha256": archive_sha, "final_filesystem_sha256": _tree_digest(tree),
                "local_build_receipt_sha256": receipt_sha, "resource_bounds": RESOURCE_BOUNDS,
                "cpu_report_sha256": digest(canonical(report)), "attestation_digests": predicates, "cpu_report": report,
                "gpu_validation": "not_run", "registry_publication": "not_performed"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "prepare"):
        p = sub.add_parser(command); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--root", type=Path, required=True)
        if command == "prepare": p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("build"); p.add_argument("--context", type=Path, required=True); p.add_argument("--output", type=Path, required=True); p.add_argument("--timeout-seconds", type=int, default=7200)
    p = sub.add_parser("inspect"); p.add_argument("--oci", type=Path, required=True); p.add_argument("--manifest-sha256", required=True); p.add_argument("--build-receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command in {"validate", "prepare"}:
            manifest = strict_json(args.manifest.read_bytes())
            result = ({"manifest_sha256": validate_manifest(manifest, args.root.resolve())} if args.command == "validate"
                      else prepare(manifest, args.root.resolve(), args.output.absolute()))
        elif args.command == "build":
            if not 1 <= args.timeout_seconds <= 14400: raise BuildError("invalid_build_timeout")
            result = build(args.context.resolve(), args.output.absolute(), args.timeout_seconds)
            private_write(args.output / "attestation.json", canonical(result))
        else:
            if args.build_receipt.stat().st_size > RESOURCE_BOUNDS["oci_json_bytes"]: raise BuildError("resource_bound_exceeded")
            result = inspect_oci(args.oci, args.manifest_sha256, strict_json(args.build_receipt.read_bytes()))
        print(canonical(result).decode(), end="")
    except (BuildError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, tarfile.TarError):
        print("Episode 1 build validation failed; inspect private inputs and logs.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__": raise SystemExit(main())
