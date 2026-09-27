#!/usr/bin/env python3
"""Preflight or run one fully authorized Episode 1 production candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from episode1_build import RESOURCE_BOUNDS, dockerfile_bytes, strict_json, validate_manifest
from episode1_watchdog import observe_clock_domain
from runpod_benchmark.bounded_runpod_transport import BoundedRunpodTransport  # noqa: F401
from runpod_benchmark.episode1_authorization import _strict_json
from runpod_benchmark.episode1_guard import FileReceiptGuard  # noqa: F401
from runpod_benchmark.episode1_material_closure import (
    PRODUCTION_PROFILE,
    read_repository_file,
)
from runpod_benchmark.episode1_production import (
    PRODUCTION_TELEMETRY_SERIES,
    execute_prepared_production,
    prepare_production_execution,
)
from runpod_benchmark.episode1_remote import (  # noqa: F401
    Episode1CellDriver,
    SshRemoteExecutor,
    SshTunnel,
)
from runpod_benchmark.episode1_runtime_control import SshRuntimeControl  # noqa: F401
from runpod_benchmark.episode1_telemetry import (  # noqa: F401
    Episode1BlockTelemetry,
    LazyNativeSamplerSource,
)
from runpod_benchmark.runpod_v2 import RunpodV2Provider  # noqa: F401


MAX_JSON = 16 * 1024 * 1024
PROVIDER_ADAPTER = "src/runpod_benchmark/episode1_runpod_adapter.py"


def _json(root: Path, relative: str, label: str):
    return _strict_json(read_repository_file(root, relative, maximum=MAX_JSON), label)


def _head(root: Path) -> str:
    raw = subprocess.run(
        ["/usr/bin/git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        },
        check=True,
        timeout=5,
    ).stdout.decode("ascii", errors="strict").strip()
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", raw) is None:
        raise ValueError("Git HEAD is invalid")
    return raw


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"))
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--build-manifest", required=True)
    parser.add_argument("--prompt-evidence", required=True)
    parser.add_argument("--provider-adapter", default=PROVIDER_ADAPTER)
    parser.add_argument("--build-attestation", required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--authorization-receipt", required=True)
    parser.add_argument("--authorization-source", required=True)
    parser.add_argument("--unique-name", required=True)
    parser.add_argument("--private-evidence-directory", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--attempt-id", default="attempt-01")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.repository_root.resolve(strict=True)
    build_raw = read_repository_file(root, args.build_manifest, maximum=MAX_JSON)
    build_manifest = strict_json(build_raw)
    build_manifest_sha256 = validate_manifest(build_manifest, root, bind_source=True)
    if args.provider_adapter != PROVIDER_ADAPTER:
        raise ValueError("provider adapter must be the repository-owned Episode 1 adapter")
    plan_bytes = read_repository_file(root, args.plan, maximum=MAX_JSON)
    material_bytes = read_repository_file(root, args.material, maximum=MAX_JSON)
    source_bytes = read_repository_file(root, args.authorization_source, maximum=MAX_JSON)
    plan = _strict_json(plan_bytes, "execution plan")
    material = _strict_json(material_bytes, "material manifest")
    receipt = _json(root, args.authorization_receipt, "authorization receipt")
    prompt = _json(root, args.prompt_evidence, "prompt evidence")
    if not all(isinstance(item, dict) for item in (build_manifest, plan, material, receipt, prompt)):
        raise ValueError("production JSON roots must be objects")
    explicit = {
        "build_manifest": args.build_manifest,
        "prompt_evidence": args.prompt_evidence,
        "provider_adapter": args.provider_adapter,
        "build_attestation": args.build_attestation,
    }
    clock_identity = observe_clock_domain()
    context_options = {
        "attempt_id": args.attempt_id,
        "clock_domain": clock_identity,
        "boot_id": clock_identity,
    }
    if args.run_id is not None:
        context_options["run_id"] = args.run_id
    prepared = prepare_production_execution(
        repository_root=root,
        profile=PRODUCTION_PROFILE,
        build_manifest=build_manifest,
        explicit_inputs=explicit,
        dockerfile_builder=dockerfile_bytes,
        supplied_material_manifest=material,
        material_file_bytes=material_bytes,
        plan=plan,
        authorization_receipt=receipt,
        plan_file_bytes=plan_bytes,
        authorization_source_bytes=source_bytes,
        observed_source_commit=_head(root),
        prompt_evidence=prompt,
        unique_name=args.unique_name,
        telemetry_series=PRODUCTION_TELEMETRY_SERIES,
        build_manifest_sha256=build_manifest_sha256,
        build_resource_bounds=RESOURCE_BOUNDS,
        **context_options,
    )
    result = {
        "plan_sha256": prepared.context.plan_sha256,
        "closure_receipt_sha256": prepared.closure_receipt["receipt_sha256"],
        "mode": args.command,
    }
    if args.command == "run":
        execution = execute_prepared_production(
            prepared, private_evidence_directory=args.private_evidence_directory
        )
        result["status"] = execution.summary.get("status")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Episode 1 production command rejected ({type(exc).__name__})") from None
