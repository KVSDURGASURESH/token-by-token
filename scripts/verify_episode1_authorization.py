#!/usr/bin/env python3
"""Verify a separately retained Episode 1 authorization receipt; never create one."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from runpod_benchmark.episode1_authorization import verify_authorization_receipt


MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_MATERIAL_FILE_BYTES = 16 * 1024 * 1024
MAX_MATERIAL_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MATERIAL_FILES = 4096
GIT_TIMEOUT_SECONDS = 5
SAFE_MATERIAL_COMPONENT = re.compile(r"^[A-Za-z0-9._@+-]+$")


def _open_directory_nofollow(path: Path) -> tuple[Path, int]:
    """Open every component of an absolute directory without following links."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in absolute.parts[1:]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current,
            )
            os.close(current)
            current = child
        return absolute, current
    except BaseException:
        os.close(current)
        raise


def _read_regular(path: Path, *, limit: int, directory_fd: int | None = None) -> bytes:
    """Read one unchanged bounded regular file, rejecting links and special files."""
    if type(limit) is not int or limit < 0:
        raise ValueError("file byte limit is invalid")
    parent_fd = None
    if directory_fd is None:
        absolute = Path(os.path.abspath(os.fspath(path)))
        _, parent_fd = _open_directory_nofollow(absolute.parent)
        directory_fd = parent_fd
        name = absolute.name
    else:
        name = os.fspath(path)
        if not name or "/" in name or name in {".", ".."}:
            raise ValueError("file name is not canonical")
    descriptor = None
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError("input is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        result = b"".join(chunks)
        after = os.fstat(descriptor)
        identity_before = (before.st_dev, before.st_ino, before.st_size,
                           before.st_mtime_ns, before.st_ctime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size,
                          after.st_mtime_ns, after.st_ctime_ns)
        if (len(result) > limit or len(result) != before.st_size
                or identity_before != identity_after):
            raise ValueError("input exceeded its bound or changed while reading")
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_fd is not None:
            os.close(parent_fd)


def _strict_json(data: bytes, label: str):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"{label} contains duplicate JSON keys")
            value[key] = item
        return value

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"{label} contains a non-finite JSON number")
        return parsed

    return json.loads(
        data.decode("utf-8", errors="strict"), object_pairs_hook=unique,
        parse_float=finite_float,
        parse_constant=lambda _item: (_ for _ in ()).throw(ValueError()),
    )


def _canonical_material_path(value: object) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or value.startswith("/") or value.endswith("/")):
        raise ValueError("material manifest path is invalid")
    if any(ord(character) < 0x20 or ord(character) == 0x7f for character in value):
        raise ValueError("material manifest path is invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or SAFE_MATERIAL_COMPONENT.fullmatch(part) is None
           for part in parts):
        raise ValueError("material manifest path is invalid")
    return value


def _material_files(root: Path, manifest: object) -> dict[str, bytes]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("material manifest does not contain a file list")
    entries = manifest["files"]
    if not 1 <= len(entries) <= MAX_MATERIAL_FILES:
        raise ValueError("material manifest file count is invalid")
    _root, root_fd = _open_directory_nofollow(root)
    result: dict[str, bytes] = {}
    total = 0
    try:
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("material manifest entry is invalid")
            relative = _canonical_material_path(entry.get("path"))
            if relative in result:
                raise ValueError("material manifest contains duplicate paths")
            parts = relative.split("/")
            current = os.dup(root_fd)
            try:
                for component in parts[:-1]:
                    child = os.open(
                        component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current,
                    )
                    os.close(current)
                    current = child
                remaining = MAX_MATERIAL_TOTAL_BYTES - total
                data = _read_regular(
                    Path(parts[-1]),
                    limit=min(MAX_MATERIAL_FILE_BYTES, remaining),
                    directory_fd=current,
                )
            finally:
                os.close(current)
            total += len(data)
            result[relative] = data
    finally:
        os.close(root_fd)
    return result


def _observed_head(root: Path) -> str:
    canonical_root, root_fd = _open_directory_nofollow(root)
    os.close(root_fd)
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(canonical_root), "rev-parse", "--verify", "HEAD"],
        check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"},
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if len(completed.stdout) > 128:
        raise ValueError("Git HEAD response exceeds its bound")
    head = completed.stdout.decode("ascii", errors="strict").strip()
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", head) is None:
        raise ValueError("Git HEAD response is invalid")
    return head


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--material", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--authorization-source", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()
    plan_bytes = _read_regular(args.plan, limit=MAX_DOCUMENT_BYTES)
    material_bytes = _read_regular(args.material, limit=MAX_DOCUMENT_BYTES)
    plan = _strict_json(plan_bytes, "plan")
    receipt = _strict_json(_read_regular(args.receipt, limit=MAX_DOCUMENT_BYTES), "receipt")
    manifest = _strict_json(material_bytes, "material manifest")
    repository_root, repository_fd = _open_directory_nofollow(args.repository_root)
    os.close(repository_fd)
    observed_head = _observed_head(repository_root)
    digest = verify_authorization_receipt(
        plan, receipt,
        plan_file_bytes=plan_bytes, material_file_bytes=material_bytes,
        material_files=_material_files(repository_root, manifest),
        observed_source_commit=observed_head,
        source_record_bytes=_read_regular(args.authorization_source, limit=MAX_DOCUMENT_BYTES),
        verification_time=datetime.now(timezone.utc),
    )
    print(json.dumps({"authorization_receipt_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
