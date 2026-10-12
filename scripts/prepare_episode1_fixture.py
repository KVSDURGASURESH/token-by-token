#!/usr/bin/env python3
"""Build deterministic, provider-free Episode 1 planning and fixture artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpod_benchmark.episode1 import (  # noqa: E402
    CELLS,
    SCHEMA_VERSION,
    append_phase,
    authored_quality_corpus,
    export_public_fixture,
    paired_block_schedule,
    protocol,
    summarize_cell,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _material_manifest() -> list[dict[str, str]]:
    """Bind all code and authored inputs that can change Episode 1 evidence."""

    relative_paths = (
        "src/runpod_benchmark/episode1.py",
        "src/runpod_benchmark/episode1_runner.py",
        "src/runpod_benchmark/streaming.py",
        "scripts/build_episode1_prompts.py",
        "scripts/prepare_episode1_fixture.py",
        "scripts/run_episode1_loopback_rehearsal.py",
        "schemas/episode1-observation.schema.json",
        "schemas/episode1-phase-ledger.schema.json",
        "schemas/episode1-protocol.schema.json",
        "schemas/episode1-public-aggregate.schema.json",
    )
    return [
        {"path": relative, "sha256": _digest(ROOT / relative)}
        for relative in sorted(relative_paths)
    ]


def _material_digest() -> str:
    manifest = _material_manifest()
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _observation(block, cell, index: int, base_ns: int) -> dict:
    success = index != int(cell["requests"]) - 1
    mode = cell["mode"]
    a = base_ns + index * 250_000_000
    if not success:
        end = a + 30_000_000
        return {
            "schema_version": SCHEMA_VERSION, "evidence_class": "local_fixture",
            "request_id": f"{block['block_id']}-{cell['id']}-{index + 1:02d}",
            "block_id": block["block_id"], "pair_id": block["pair_id"], "runtime": block["runtime"],
            "cell_id": cell["id"], "mode": mode, "warmup": False, "scheduled_order": index + 1,
            "clock_domain": "client_monotonic_ns", "a_ns": a, "b_ns": None, "s_ns": None,
            "f_ns": None, "l_ns": None, "d_ns": None, "end_ns": end,
            "content_event_count": 0, "interchunk_gaps_ns": [], "input_tokens": cell["input_tokens"],
            "output_tokens": None, "streamed_usage_output_tokens": None, "tokenizer_output_tokens": None,
            "stop_reason": "not_started", "status": "unsent", "reason_code": "not_dispatched",
            "fixed_length_valid": None, "schema_valid": None, "semantic_correct": None,
            "nontruncated": None, "quality_task_id": None,
        }
    b, s = a + 1_000_000, a + 2_000_000
    f = s + (110_000_000 if cell["id"] == "fixed-medium" else 70_000_000)
    output_tokens = 128 if mode == "fixed_output" else 24 + index % 12
    # Some streams deliberately coalesce multiple tokens per content event.
    event_count = 1 if index == 0 else output_tokens
    l = f if event_count == 1 else f + (event_count - 1) * 4_000_000
    d = l + 3_000_000
    return {
        "schema_version": SCHEMA_VERSION, "evidence_class": "local_fixture",
        "request_id": f"{block['block_id']}-{cell['id']}-{index + 1:02d}",
        "block_id": block["block_id"], "pair_id": block["pair_id"], "runtime": block["runtime"],
        "cell_id": cell["id"], "mode": mode, "warmup": False, "scheduled_order": index + 1,
        "clock_domain": "client_monotonic_ns", "a_ns": a, "b_ns": b, "s_ns": s,
        "f_ns": f, "l_ns": l, "d_ns": d, "end_ns": d,
        "content_event_count": event_count,
        "interchunk_gaps_ns": [] if event_count == 1 else [4_000_000] * (event_count - 1),
        "input_tokens": cell["input_tokens"] if cell["input_tokens"] is not None else 64 + index,
        "output_tokens": output_tokens, "streamed_usage_output_tokens": output_tokens,
        "tokenizer_output_tokens": output_tokens,
        "stop_reason": "length" if mode == "fixed_output" else "eos",
        "status": "success", "reason_code": "none",
        "fixed_length_valid": True if mode == "fixed_output" else None,
        "schema_valid": True if mode == "natural_stop" else None,
        "semantic_correct": (index != 22) if mode == "natural_stop" else None,
        "nontruncated": True if mode == "natural_stop" else None,
        "quality_task_id": f"quality-{index + 1:02d}" if mode == "natural_stop" else None,
    }


def build(raw_directory: Path) -> tuple[dict, list[dict], list[dict], dict]:
    project = ROOT.resolve()
    raw = raw_directory.resolve()
    if raw == project or project in raw.parents:
        raise ValueError("raw Episode 1 request evidence must be outside the repository")
    raw.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(raw, 0o700)
    corpus = authored_quality_corpus()
    corpus_sha = hashlib.sha256(json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    protocol_value = protocol(corpus_sha, _material_digest())
    summaries: list[dict] = []
    base = 1_000_000_000
    raw_records: list[dict] = []
    for block in paired_block_schedule():
        for cell_id in block["cell_order"]:
            cell = next(item for item in CELLS if item["id"] == cell_id)
            stride = 750_000_000 if int(cell["concurrency"]) == 1 and cell["mode"] == "fixed_output" else 250_000_000
            records = [_observation(block, cell, index, base + index * (stride - 250_000_000)) for index in range(int(cell["requests"]))]
            start = records[0]["a_ns"]
            end = max(record["end_ns"] for record in records)
            summaries.append(summarize_cell(records, start, end, cell))
            raw_records.extend(records)
            base = end + 1_000_000_000
    raw_path = raw / "episode1-local-fixture-requests.json"
    raw_path.write_text(json.dumps(raw_records, indent=2) + "\n")
    os.chmod(raw_path, 0o600)
    telemetry = [{
        "runtime": runtime, "block_id": block["block_id"], "cell_id": cell["id"],
        "metric": "gpu_power_watts", "available": False, "unit": "W", "source": "gpu_sampler",
        "window": "cell", "value": None, "unavailable_reason": "local fixture has no GPU telemetry",
    } for block in paired_block_schedule() for runtime in [block["runtime"]] for cell in CELLS]
    exported = export_public_fixture(protocol_value, summaries, telemetry)
    ledger: list[dict] = []
    phases = ("preflight", "startup", "warmup", "measurement", "export", "teardown", "settlement")
    for index, phase in enumerate(phases):
        append_phase(ledger, phase, index * 10_000_000, index * 10_000_000 + 5_000_000,
                     f"2026-09-22T00:00:{index:02d}Z", f"2026-09-22T00:00:{index:02d}.005Z",
                     "not_applicable_fixture", None, protocol_value["protocol_sha256"])
    return protocol_value, ledger, corpus, exported


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-directory", type=Path, required=True)
    args = parser.parse_args()
    protocol_value, ledger, corpus, exported = build(args.raw_directory)
    args.output.mkdir(parents=True, exist_ok=True)
    files = {
        "episode1-planning.json": protocol_value,
        "phase-ledger.fixture.json": {"classification": "local_fixture", "records": ledger},
        "quality-corpus.json": {"schema_version": SCHEMA_VERSION, "classification": "public_authored_synthetic", "tasks": corpus},
        "public-aggregate.fixture.json": exported,
        "material-manifest.fixture.json": {
            "classification": "local_fixture_material_hashes",
            "files": _material_manifest(),
            "aggregate_sha256": _material_digest(),
        },
    }
    for name, value in files.items():
        (args.output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"provider_calls": 0, "execution_ready": False, "measured_requests": 528, "warmups_declared": 72, "files": sorted(files)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
