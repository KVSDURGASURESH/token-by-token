#!/usr/bin/env python3
"""Compile private Episode 1 candidates from observed local material; no execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_authorization import (
    _canonical_material_path, _material_aggregate, _strict_json,
)
from runpod_benchmark.episode1_execution import (
    compile_execution_candidate, verify_execution_candidate, verify_fresh_for_create,
)

MAX_DOCUMENT = 4 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 4096


def read_regular(path: Path, *, limit: int, directory_fd: int | None = None) -> bytes:
    """Read a regular file without following its final link, at most limit+1 bytes."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('input is not a bounded regular file')
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        result = b''.join(chunks)
        after = os.fstat(descriptor)
        if len(result) > limit or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise ValueError('input exceeded its bound or changed while reading')
        return result
    finally:
        os.close(descriptor)


def read_material(root: Path, manifest_bytes: bytes) -> tuple[str, dict[str, bytes]]:
    manifest = _strict_json(manifest_bytes, 'material manifest')
    if not isinstance(manifest, dict) or set(manifest) != {'classification', 'aggregate_sha256', 'files'}:
        raise ValueError('material manifest schema is invalid')
    entries = manifest['files']
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
        raise ValueError('material file count is invalid')
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    observed = {}
    total = 0
    try:
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}:
                raise ValueError('material entry schema is invalid')
            relative = _canonical_material_path(entry['path'])
            if relative in observed:
                raise ValueError('duplicate material path')
            parts = relative.split('/')
            current = os.dup(root_fd)
            try:
                for component in parts[:-1]:
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                    os.close(current)
                    current = child
                data = read_regular(Path(parts[-1]), limit=min(MAX_FILE, MAX_TOTAL-total), directory_fd=current)
            finally:
                os.close(current)
            total += len(data)
            observed[relative] = data
    finally:
        os.close(root_fd)
    return _material_aggregate(manifest_bytes, observed), observed


def observed_head(root: Path) -> str:
    # rev-parse invokes no repository hooks and produces one fixed-size object ID.
    result = subprocess.run(
        ['/usr/bin/git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
             'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0'},
        check=True, timeout=5,
    ).stdout
    if len(result) > 128:
        raise ValueError('Git HEAD response exceeds its bound')
    head = result.decode('ascii', errors='strict').strip()
    if re.fullmatch(r'[0-9a-f]{40}(?:[0-9a-f]{24})?', head) is None:
        raise ValueError('Git HEAD response is invalid')
    return head


def compile_files(*, protocol_path: Path, inputs_path: Path, material_path: Path,
                  repository_root: Path, head_reader: Callable[[Path], str] = observed_head,
                  now: datetime | None = None) -> dict:
    root = repository_root.resolve(strict=True)
    protocol = _strict_json(read_regular(protocol_path, limit=MAX_DOCUMENT), 'protocol')
    inputs = _strict_json(read_regular(inputs_path, limit=MAX_DOCUMENT), 'inputs')
    material = read_regular(material_path, limit=MAX_DOCUMENT)
    aggregate, _files = read_material(root, material)
    if not isinstance(inputs, dict) or inputs.get('material_sha256') != aggregate:
        raise ValueError('actual material aggregate differs from compiler input')
    if inputs.get('source_commit') != head_reader(root):
        raise ValueError('observed HEAD differs from compiler input')
    plan = compile_execution_candidate(protocol, inputs)
    verify_execution_candidate(plan)
    if plan['execution_ready']:
        verify_fresh_for_create(plan, now=now or datetime.now(timezone.utc))
    return plan


def write_private_exclusive(path: Path, data: bytes) -> None:
    """Durably publish one complete output; never overwrite existing review evidence."""
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('output parent must be a private non-symlink directory')
    descriptor, temporary = tempfile.mkstemp(prefix='.episode1-compile-', dir=parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path, follow_symlinks=False)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--material', type=Path, required=True)
    parser.add_argument('--repository-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = compile_files(protocol_path=args.protocol, inputs_path=args.inputs,
                         material_path=args.material, repository_root=args.repository_root)
    output = (canonical_json(plan) + '\n').encode()
    write_private_exclusive(args.output, output)
    # Report no full operator input, account facts or approval phrase.
    print(json.dumps({'plan_sha256': plan['plan_sha256'],
                      'plan_file_sha256': hashlib.sha256(output).hexdigest(),
                      'execution_ready': plan['execution_ready'],
                      'unresolved_blocker_count': len(plan['unresolved_blockers'])}, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        # Paths and arbitrary JSON parse snippets can contain private data.
        raise SystemExit(f'Episode 1 compilation rejected ({type(exc).__name__})') from None
