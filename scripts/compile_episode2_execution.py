#!/usr/bin/env python3
"""Compile private Episode 02 preparation without contacting a provider."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from runpod_benchmark.episode2_contract import loads_strict_json
from runpod_benchmark.episode2_preflight import compile_episode2, open_contained, open_directory
from compile_plan import approval_phrase, canonical_bytes, plan_digest

MAX_INPUT_BYTES = 20 * 1024 * 1024


def read_private(path: Path, root: Path):
    if path.is_symlink():
        raise ValueError("private input symlink")
    target = path.absolute()
    if not target.is_relative_to(root):
        raise ValueError("private input escapes root")
    descriptor = open_contained(root, target.relative_to(root))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > MAX_INPUT_BYTES:
            raise ValueError("private input is not a bounded private regular file")
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("private input exceeds byte bound")
    return loads_strict_json(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("protocol", "inputs", "material", "cleanup", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--planning-only", action="store_true")
    args = parser.parse_args()
    try:
        private_root = args.inputs.parent.absolute()
        if not private_root.is_dir() or private_root.stat().st_mode & 0o077:
            raise ValueError("input root must be private")
        documents = {name: read_private(getattr(args, name), private_root) for name in ("protocol", "inputs", "material", "cleanup")}
        artifact_root = documents["material"].get("artifact_root")
        if artifact_root is not None and not Path(artifact_root).resolve(strict=True).is_relative_to(private_root):
            raise ValueError("material artifact root escapes private input root")
        parent = args.output.parent.absolute()
        if not parent.is_relative_to(private_root) or parent.stat().st_mode & 0o077:
            raise ValueError("output parent must be contained and private")
        output = parent / args.output.name
        plan = compile_episode2(documents["protocol"], documents["inputs"], documents["material"], documents["cleanup"], planning_only=args.planning_only)
        digest = plan_digest(plan)
        envelope = {"plan_sha256": digest, "execution_ready": plan["execution_ready"], "approval_phrase": approval_phrase(plan) if plan["execution_ready"] else None, "plan": plan}
        raw = json.dumps(envelope, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2).encode() + b"\n"
        directory = open_directory(parent)
        try:
            descriptor = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory)
        finally:
            os.close(directory)
        print(json.dumps({"plan_sha256": digest, "execution_ready": plan["execution_ready"], "provider_calls": 0, "blockers": plan["manifest"]["episode2"]["preflight"]["blockers"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print("Episode 02 compilation failed; inspect private inputs locally.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
