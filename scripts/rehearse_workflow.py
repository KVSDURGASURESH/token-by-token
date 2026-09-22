#!/usr/bin/env python3
"""Build and verify a deterministic, zero-cost benchmark workflow rehearsal."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT / "scripts",):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from compile_plan import PlanValidationError, approval_phrase, compile_plan, plan_digest
from verify_bundle import verify_bundle

from build_publication_assets import build_assets


CLASSIFICATION = "fixture_zero_cost"
HISTORICAL_STUDY = ROOT / "data" / "public" / "live-study.json"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _fixture_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "planning_only": True,
        "experiment_id": "zero-cost-workflow-rehearsal",
        "budget": {"max_usd": "0.01", "minimum_final_balance_usd": "0.00"},
        "resource": {
            "gpu_count": 1,
            "cloud": "SECURE",
            "terminate_after_minutes": 1,
        },
        "model": {
            "repository": "Qwen/Qwen2.5-32B-Instruct",
            "revision": "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
        },
        "runtimes": [{"id": "vllm", "version": "0.29.0", "fallbacks": []}],
        "workload": {
            "cells": [
                {
                    "input_tokens": 128,
                    "output_tokens": 64,
                    "concurrency": 1,
                    "requests": 100,
                    "repetitions": 1,
                    "timeout_seconds": 120,
                }
            ]
        },
    }


def _fixture_live_inputs() -> dict[str, Any]:
    return {
        "gpu": {
            "gpu_id": "fixture-local-gpu",
            "hourly_usd": "0.000001",
            "stock": "available",
        },
        "account": {
            "balance_usd": "0.01",
            "auto_recharge_verified_disabled": True,
        },
        "estimate": {"expected_minutes": 1, "maximum_minutes": 1},
        "compatibility": {
            "status": "pass",
            "evidence": ["static fixture contract; no provider was contacted"],
        },
    }


def _classification_mark_assets(output_dir: Path) -> None:
    for name in (
        "ttft-tail-latency.svg",
        "tail-latency-matrix.svg",
        "output-throughput.svg",
    ):
        path = output_dir / name
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                '<svg xmlns="http://www.w3.org/2000/svg" ',
                f'<svg data-classification="{CLASSIFICATION}" ',
                1,
            ),
            encoding="utf-8",
        )

    for name in ("linkedin-post.md", "visual-alt-text.md"):
        path = output_dir / name
        text = path.read_text(encoding="utf-8")
        path.write_text(
            f"Classification: {CLASSIFICATION}\n\n{text}", encoding="utf-8"
        )

    csv_path = output_dir / "benchmark-summary.csv"
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["classification", *rows[0]])
        writer.writerows(([CLASSIFICATION, *row] for row in rows[1:]))


def _write_checksums(output_dir: Path) -> None:
    checksum_path = output_dir / "checksums.sha256"
    entries = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path != checksum_path:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append(f"{digest}  {path.relative_to(output_dir).as_posix()}")
    checksum_path.write_text("\n".join(entries) + "\n", encoding="utf-8")


def _require_empty_directory(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("rehearsal output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)


def rehearse(output_dir: Path) -> dict[str, object]:
    """Generate a fixture-only public bundle using direct Python calls only."""

    output_dir = Path(output_dir)
    _require_empty_directory(output_dir)

    manifest = _fixture_manifest()
    compiled_plan = compile_plan(manifest, _fixture_live_inputs())
    if compiled_plan["execution_ready"] is not False:
        raise AssertionError("fixture plan unexpectedly became executable")
    if compiled_plan["cost"]["expected_usd"] != "0.00" or compiled_plan["cost"][
        "maximum_usd"
    ] != "0.00":
        raise AssertionError("fixture plan is not zero cost")
    digest = plan_digest(compiled_plan)

    study = json.loads(HISTORICAL_STUDY.read_text(encoding="utf-8"))
    study["classification"] = CLASSIFICATION
    study["fixture_source"] = "sanitized_historical_benchmark"
    study["study_facts"]["preflight"] = [
        f"{CLASSIFICATION}: reused sanitized historical measurements; no provider call was made.",
        *study["study_facts"]["preflight"],
    ]

    public_manifest = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "classification": CLASSIFICATION,
        "execution_mode": "planning_only",
        "compiler_input": manifest,
    }
    public_plan = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "classification": CLASSIFICATION,
        "planning_only": True,
        "execution_ready": False,
        "approvable": False,
        "compiled_plan_digest": digest,
        "cost": {"expected_usd": "0.00", "maximum_usd": "0.00"},
        "compiled_plan": compiled_plan,
    }
    runtime_attempts = {
        "schema_version": 1,
        "classification": CLASSIFICATION,
        "provider_calls_made": False,
        "attempts": [],
    }
    teardown = {
        "schema_version": 1,
        "classification": CLASSIFICATION,
        "evidence_scope": "synthetic_non_provider",
        "provider_calls_made": False,
        "created_resources": [],
        "final_balance_observed": True,
    }
    gpu_summary = {
        "schema_version": 1,
        "classification": CLASSIFICATION,
        "evidence_scope": "sanitized_historical_fixture",
        "provider_calls_made": False,
        "samples": 0,
        "runtime_native_metrics_collected": False,
    }

    for name, value in (
        ("manifest.json", public_manifest),
        ("plan.json", public_plan),
        ("runtime-attempts.json", runtime_attempts),
        ("live-study.json", study),
        ("gpu-summary.json", gpu_summary),
        ("teardown.json", teardown),
        ("dashboard/latest.json", study),
    ):
        _write_json(output_dir / name, value)

    build_assets(study, output_dir)
    _classification_mark_assets(output_dir)

    successful = sum(cell["successful_requests"] for cell in study["cells"])
    failed = sum(cell["failed_requests"] for cell in study["cells"])
    (output_dir / "report.md").write_text(
        "# Zero-cost workflow rehearsal\n\n"
        f"Classification: {CLASSIFICATION}\n\n"
        "This bundle replays sanitized historical evidence only. It is not a live result "
        "and authorizes no provider action.\n\n"
        f"successful requests: {successful}\n\nfailed requests: {failed}\n",
        encoding="utf-8",
    )
    (output_dir / "journal.md").write_text(
        "# Rehearsal journal\n\n"
        f"Classification: {CLASSIFICATION}\n\n"
        "Direct Python functions loaded the fixture, compiled a planning-only plan, "
        "built assets, staged dashboard data, and verified the bundle. No shell, "
        "network, provider, rental, or publication action occurred.\n",
        encoding="utf-8",
    )
    (output_dir / "reproduction.md").write_text(
        "# Reproduce locally\n\n"
        f"Classification: {CLASSIFICATION}\n\n"
        "Run the repository rehearsal command against a new empty output directory, "
        "then run the bundle verifier. This fixture workflow has no live mode and the "
        "compiled plan is deliberately nonapprovable.\n",
        encoding="utf-8",
    )

    _write_checksums(output_dir)
    verification = verify_bundle(output_dir)
    if not verification.ok:
        raise ValueError(f"generated bundle failed verification: {verification.errors}")
    return {
        "classification": CLASSIFICATION,
        "paid_resources_created": 0,
        "provider_attempts": 0,
        "plan_digest": digest,
        "verification": verification,
        "output_dir": output_dir,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = rehearse(args.output)
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"verification", "output_dir"}
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
