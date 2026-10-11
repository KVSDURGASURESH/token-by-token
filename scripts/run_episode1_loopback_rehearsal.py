#!/usr/bin/env python3
"""Run the complete Episode 1 schedule against fresh local HTTP/SSE processes.

This is provider-free harness acceptance.  It never creates a provider resource,
and its output remains local-fixture evidence even though real loopback transport
and SSE parsing are exercised.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpod_benchmark.episode1 import (  # noqa: E402
    CELLS,
    CHAT_TEMPLATE_SHA256,
    PROMPT_EVIDENCE_SHA256,
    TOKENIZER_ASSET_MANIFEST_SHA256,
    export_public_fixture,
    paired_block_schedule,
    validate_observation,
    verify_protocol,
)
from runpod_benchmark.episode1_runner import run_fixture_cell  # noqa: E402


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def atomic_private_json(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def verify_material_manifest(path: Path, plan: dict) -> None:
    manifest = json.loads(path.read_text())
    if set(manifest) != {"classification", "files", "aggregate_sha256"}:
        raise ValueError("material manifest envelope is not closed")
    if manifest["classification"] != "local_fixture_material_hashes":
        raise ValueError("material manifest classification is invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or files != sorted(files, key=lambda item: item.get("path", "")):
        raise ValueError("material manifest entries must be a sorted list")
    for item in files:
        if set(item) != {"path", "sha256"} or Path(item["path"]).is_absolute():
            raise ValueError("material manifest entry is invalid")
        candidate = (ROOT / item["path"]).resolve()
        if ROOT.resolve() not in candidate.parents or hashlib.sha256(candidate.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"material manifest mismatch: {item['path']}")
    aggregate = canonical_sha(files)
    if aggregate != manifest["aggregate_sha256"] or aggregate != plan["hashes"]["harness_sha256"]:
        raise ValueError("material manifest aggregate differs from the frozen plan")


def sse(value: object) -> bytes:
    return f"data: {json.dumps(value, ensure_ascii=False)}\n\n".encode()


def serve(config_path: Path, port_path: Path) -> int:
    config = json.loads(config_path.read_text())
    responses = config["responses"]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(size))
                content = request["messages"][0]["content"]
                response_text = responses[content]
                tokens = int(config["token_counts"][content])
                finish = "stop" if content in config["natural_contents"] else "length"
                chunks = (
                    sse({"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}),
                    sse({"choices": [{"delta": {"content": response_text}, "finish_reason": finish}]}),
                    sse({"choices": [], "usage": {"completion_tokens": tokens}}),
                    b"data: [DONE]\n\n",
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.send_response(400)
                self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port_path.write_text(str(server.server_port))
    os.chmod(port_path, 0o600)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def wait_for_port(path: Path, process: subprocess.Popen[bytes]) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("fresh loopback fixture process exited before readiness")
        if path.exists():
            value = int(path.read_text())
            if 0 < value < 65536:
                return value
        time.sleep(.01)
    raise RuntimeError("fresh loopback fixture process did not become ready")


def prompt_contract(path: Path) -> dict:
    evidence = json.loads(path.read_text())
    if canonical_sha(evidence) != PROMPT_EVIDENCE_SHA256:
        raise ValueError("prompt evidence differs from the reviewed artifact")
    if evidence.get("chat_template_sha256") != CHAT_TEMPLATE_SHA256:
        raise ValueError("chat template evidence differs from the reviewed artifact")
    if canonical_sha(evidence.get("asset_sha256")) != TOKENIZER_ASSET_MANIFEST_SHA256:
        raise ValueError("tokenizer asset manifest differs from the reviewed artifact")
    if [item.get("target_input_tokens") for item in evidence.get("fixed", [])] != [512, 2048]:
        raise ValueError("prompt evidence lacks the two frozen fixed prompts")
    if len(evidence.get("natural_quality", [])) != 24:
        raise ValueError("prompt evidence lacks the 24 frozen quality tasks")
    return evidence


def specs(evidence: dict, block: dict, cell: dict, *, warmup: bool) -> list[dict]:
    count = int(cell["warmups"] if warmup else cell["requests"])
    prefix = "warmup" if warmup else "measured"
    if cell["mode"] == "fixed_output":
        prompt = next(item for item in evidence["fixed"] if item["target_input_tokens"] == cell["input_tokens"])
        return [{
            "request_id": f"{block['block_id']}-{prefix}-{cell['id']}-{index + 1:02d}",
            "messages": prompt["messages"], "quality_task_id": None, "gold_json": None,
        } for index in range(count)]
    tasks = evidence["natural_quality"][:count] if warmup else evidence["natural_quality"]
    return [{
        "request_id": f"{block['block_id']}-{prefix}-{cell['id']}-{index + 1:02d}",
        "messages": task["messages"], "quality_task_id": task["task_id"],
        "gold_json": task["gold_json"],
    } for index, task in enumerate(tasks)]


def run(args: argparse.Namespace) -> int:
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("install the pinned live extra before the loopback rehearsal") from exc

    evidence = prompt_contract(args.prompt_evidence.resolve())
    plan = json.loads(args.plan.resolve().read_text())
    verify_protocol(plan)
    verify_material_manifest(args.material_manifest.resolve(), plan)
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_directory.resolve(), local_files_only=True, trust_remote_code=False
    )
    if hashlib.sha256(tokenizer.chat_template.encode()).hexdigest() != CHAT_TEMPLATE_SHA256:
        raise ValueError("loaded tokenizer chat template differs from the reviewed evidence")

    def input_count(messages: list[dict[str, str]]) -> int:
        values = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
        if hasattr(values, "input_ids"):
            values = values.input_ids
        if values and isinstance(values[0], list):
            values = values[0]
        return len(values)

    def output_count(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False))

    fixed_output = " x" * 128
    if output_count(fixed_output) != 128:
        raise ValueError("deterministic fixture output is not exactly 128 tokens")
    responses: dict[str, str] = {}
    token_counts: dict[str, int] = {}
    natural_contents: list[str] = []
    for item in evidence["fixed"]:
        content = item["messages"][0]["content"]
        responses[content], token_counts[content] = fixed_output, 128
    for item in evidence["natural_quality"]:
        content = item["messages"][0]["content"]
        responses[content] = item["gold_json"]
        token_counts[content] = output_count(item["gold_json"])
        natural_contents.append(content)

    raw_directory = args.raw_directory.resolve()
    if raw_directory.exists() and any(raw_directory.iterdir()):
        raise ValueError("raw rehearsal directory must be new or empty; prior evidence is never overwritten")
    raw_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(raw_directory, 0o700)
    server_config = raw_directory / "loopback-server-config.json"
    atomic_private_json(server_config, {
        "responses": responses, "token_counts": token_counts,
        "natural_contents": natural_contents,
    })
    records: list[dict] = []
    summaries: list[dict] = []
    boundaries: list[dict] = []

    def persist_private() -> None:
        atomic_private_json(raw_directory / "episode1-loopback-requests.json", {
            "classification": "private_local_fixture", "prompt_evidence_sha256": canonical_sha(evidence),
            "record_count": len(records), "warmup_count": sum(record["warmup"] for record in records),
            "records": records,
        })
        atomic_private_json(raw_directory / "episode1-loopback-boundaries.json", {
            "classification": "private_local_fixture_boundaries", "clock_domain": "client_monotonic_ns",
            "fresh_process_count": len(boundaries), "blocks": boundaries,
        })

    try:
        for block in paired_block_schedule():
            port_file = raw_directory / f"{block['block_id']}.port"
            port_file.unlink(missing_ok=True)
            started_ns, started_utc = time.monotonic_ns(), utc_now()
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--serve", "--server-config", str(server_config), "--port-file", str(port_file)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            block_boundary = {
                "block_id": block["block_id"], "runtime": block["runtime"],
                "process_instance": f"local-pid-{process.pid}", "pid": process.pid,
                "started_ns": started_ns, "started_utc": started_utc, "cells": [],
            }
            try:
                port = wait_for_port(port_file, process)
                ready_ns, ready_utc = time.monotonic_ns(), utc_now()
                endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
                block_boundary.update({"ready_ns": ready_ns, "ready_utc": ready_utc})
                warmup_records_by_cell: dict[str, list[dict]] = {}
                for cell_id in block["cell_order"]:
                    cell = next(dict(item) for item in CELLS if item["id"] == cell_id)
                    warm_cell = {**cell, "requests": cell["warmups"]}
                    warm_start = time.monotonic_ns()
                    warm_records, warm_summary = run_fixture_cell(
                        endpoint_url=endpoint, model="episode1-loopback-fixture",
                        block=block, cell=warm_cell, requests=specs(evidence, block, cell, warmup=True),
                        input_token_counter=input_count, output_token_counter=output_count,
                    )
                    warm_records = [{**record, "warmup": True} for record in warm_records]
                    warm_records = [{k: v for k, v in validate_observation(record).items() if k != "derived"} for record in warm_records]
                    records.extend(warm_records)
                    warmup_records_by_cell[cell_id] = warm_records
                    block_boundary["cells"].append({
                        "cell_id": cell_id, "warmup_start_ns": warm_start,
                        "warmup_end_ns": time.monotonic_ns(),
                    })
                    persist_private()
                    if warm_summary["counts"]["transport_success"] != cell["warmups"]:
                        raise RuntimeError("warmup failure aborts the local rehearsal")
                for cell_id in block["cell_order"]:
                    cell = next(dict(item) for item in CELLS if item["id"] == cell_id)
                    measured_start = time.monotonic_ns()
                    measured_records, summary = run_fixture_cell(
                        endpoint_url=endpoint, model="episode1-loopback-fixture",
                        block=block, cell=cell, requests=specs(evidence, block, cell, warmup=False),
                        input_token_counter=input_count, output_token_counter=output_count,
                    )
                    measured_end = time.monotonic_ns()
                    records.extend(measured_records)
                    summaries.append(summary)
                    cell_boundary = next(item for item in block_boundary["cells"] if item["cell_id"] == cell_id)
                    cell_boundary.update({"measurement_start_ns": measured_start, "measurement_end_ns": measured_end})
                    persist_private()
            finally:
                block_boundary["stopping_ns"], block_boundary["stopping_utc"] = time.monotonic_ns(), utc_now()
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                block_boundary["stopped_ns"], block_boundary["stopped_utc"] = time.monotonic_ns(), utc_now()
                block_boundary["exit_code"] = process.returncode
                block_boundary["previous_sha256"] = boundaries[-1]["record_sha256"] if boundaries else "0" * 64
                block_boundary["record_sha256"] = canonical_sha(block_boundary)
                boundaries.append(block_boundary)
                persist_private()
        telemetry = [{
            "runtime": block["runtime"], "block_id": block["block_id"], "cell_id": cell["id"],
            "metric": "gpu_power_watts", "available": False, "unit": "W", "source": "gpu_sampler",
            "window": "cell", "value": None, "unavailable_reason": "local fixture has no GPU telemetry",
        } for block in paired_block_schedule() for cell in CELLS]
        public = export_public_fixture(plan, summaries, telemetry, transport_exercised=True)
        persist_private()
        args.public_output.parent.mkdir(parents=True, exist_ok=True)
        args.public_output.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n")
        print(json.dumps({
            "provider_calls": 0, "fresh_loopback_processes": len(boundaries),
            "warmups_executed": sum(record["warmup"] for record in records),
            "measured_requests": sum(not record["warmup"] for record in records),
            "cell_summaries": len(summaries), "public_output": str(args.public_output),
            "raw_directory": str(raw_directory),
        }))
        return 0
    finally:
        server_config.unlink(missing_ok=True)
        for port_file in raw_directory.glob("block-*.port"):
            port_file.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--server-config", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--prompt-evidence", type=Path)
    parser.add_argument("--material-manifest", type=Path)
    parser.add_argument("--tokenizer-directory", type=Path)
    parser.add_argument("--raw-directory", type=Path)
    parser.add_argument("--public-output", type=Path)
    args = parser.parse_args()
    if args.serve:
        if args.server_config is None or args.port_file is None:
            parser.error("internal server mode requires config and port file")
        return serve(args.server_config, args.port_file)
    required = ("plan", "prompt_evidence", "material_manifest", "tokenizer_directory", "raw_directory", "public_output")
    if any(getattr(args, name) is None for name in required):
        parser.error("rehearsal mode requires plan, prompt evidence, tokenizer directory, raw directory and public output")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
