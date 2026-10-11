#!/usr/bin/env python3
"""Run a bounded, runtime-neutral OpenAI-compatible streaming benchmark cell."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.metadata
import json
import math
import pathlib
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
for import_root in (SOURCE_ROOT, SCRIPT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from runpod_benchmark import metrics, streaming  # noqa: E402
from validated_plan import load_compiled_plan  # noqa: E402


PROMPT_GENERATOR_CONTRACT = {
    "schema_version": 1,
    "source": "inference-lab-deterministic-filler-v1",
    "algorithm": "largest chat-template token count at or below target via binary search",
    "filler": " benchmark",
    "measured_prefix": (
        "Repetition {repetition:03d} cell {input_tokens:05d}-{concurrency:03d} "
        "request {request_index:08d}. Measure inference latency."
    ),
    "warmup_prefix": "Warmup request {request_index:08d}. Prepare inference runtime.",
}


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def workload_contract(
    *,
    model: str,
    model_revision: str,
    matrix: list[tuple[int, int]],
    request_count: int,
    repetitions: int,
    seed: int,
) -> dict[str, Any]:
    """Return the exact generator and per-cell hashes enforced by the runner."""

    generator_sha256 = _canonical_sha256(PROMPT_GENERATOR_CONTRACT)
    generator_revision = hashlib.sha1(
        json.dumps(
            PROMPT_GENERATOR_CONTRACT, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    prompt_cells = []
    for input_tokens, concurrency in matrix:
        descriptor = {
            "generator_sha256": generator_sha256,
            "model": model,
            "model_revision": model_revision,
            "input_tokens": input_tokens,
            "concurrency": concurrency,
            "requests": request_count,
            "repetitions": repetitions,
            "seed": seed,
        }
        prompt_cells.append({
            "id": f"input-{input_tokens}-concurrency-{concurrency}",
            "prompt_sha256": _canonical_sha256(descriptor),
        })
    return {
        "dataset": {
            "source": PROMPT_GENERATOR_CONTRACT["source"],
            "revision": generator_revision,
            "sha256": generator_sha256,
        },
        "prompt_cells": prompt_cells,
    }


def validate_tokenizer_contract(plan: Mapping[str, Any], tokenizer: Any) -> None:
    """Bind the loaded tokenizer's exact chat template to the approved plan."""

    execution_model = plan["manifest"]["execution"]["model"]
    get_template = getattr(tokenizer, "get_chat_template", None)
    template = get_template() if callable(get_template) else getattr(tokenizer, "chat_template", None)
    if not isinstance(template, str) or not template:
        raise RuntimeError("loaded tokenizer has no concrete chat template")
    observed = hashlib.sha256(template.encode("utf-8")).hexdigest()
    if execution_model["chat_template"]["sha256"] != observed:
        raise RuntimeError("loaded tokenizer chat template does not match the plan")


def _token_count(tokenizer: Any, text: str) -> int:
    tokens = tokenizer.apply_chat_template(
        [{"role": "user", "content": text}],
        tokenize=True,
        add_generation_prompt=True,
    )
    if isinstance(tokens, Mapping):
        tokens = tokens.get("input_ids")
    shape = getattr(tokens, "shape", None)
    if shape is not None and len(shape):
        return int(shape[-1])
    if (
        isinstance(tokens, (list, tuple))
        and tokens
        and isinstance(tokens[0], (list, tuple))
    ):
        return len(tokens[0])
    return len(tokens)


def build_prompt(
    tokenizer: Any,
    target_input_tokens: int,
    *,
    prefix: str = "Measure inference latency.",
) -> dict[str, Any]:
    """Build deterministic text at or just below a chat-template token target."""

    if target_input_tokens < 8:
        raise ValueError("target_input_tokens must be at least 8")
    low, high = 0, max(1, target_input_tokens * 2)
    best_text = prefix
    best_count = _token_count(tokenizer, best_text)
    if best_count > target_input_tokens:
        raise ValueError("target is smaller than the model chat-template overhead")
    while low <= high:
        middle = (low + high) // 2
        candidate = prefix + (" benchmark" * middle)
        count = _token_count(tokenizer, candidate)
        if count <= target_input_tokens:
            best_text, best_count = candidate, count
            low = middle + 1
        else:
            high = middle - 1
    return {
        "text": best_text,
        "input_tokens": best_count,
        "target_input_tokens": target_input_tokens,
        "sha256": hashlib.sha256(best_text.encode("utf-8")).hexdigest(),
    }


def _observe(
    index: int,
    request_source: Mapping[str, Any] | Callable[[int], Mapping[str, Any]],
    stream: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    input_tokens = None
    try:
        raw_request = request_source(index) if callable(request_source) else request_source
        request = dict(raw_request)
        input_tokens = request.pop("_benchmark_input_tokens", None)
        if input_tokens is not None and (
            isinstance(input_tokens, bool)
            or not isinstance(input_tokens, int)
            or input_tokens < 1
        ):
            raise ValueError("benchmark input token count must be a positive integer")
        result = stream(request)
        if result.get("success") is not True:
            raise ValueError("exact streaming evidence reports failure")
        if not isinstance(result.get("text"), str) or not result["text"]:
            raise ValueError("exact streaming evidence requires nonempty content and TTFT")
        if not isinstance(result.get("ttft_ms"), (int, float)):
            raise ValueError("exact streaming evidence requires nonempty content and TTFT")
        output_tokens = result.get("output_tokens")
        if isinstance(output_tokens, bool) or not isinstance(output_tokens, int) or output_tokens < 1:
            raise ValueError("exact streaming evidence requires streamed output-token usage")
        return {
            "request_index": index,
            "input_tokens": input_tokens,
            "started_at_utc": started,
            **result,
            "response_characters": len(result.get("text", "")),
            "text": None,
            "completed_at_utc": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:  # each failure is evidence; the cell must drain
        return {
            "request_index": index,
            "input_tokens": input_tokens,
            "started_at_utc": started,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "success": False,
            "text": None,
            "response_characters": 0,
            "ttft_ms": None,
            "content_span_ms": None,
            "inter_chunk_ms": [],
            "e2e_ms": None,
            "output_tokens": None,
            "stop_reason": None,
            "actual_send_ns": None,
            "error": str(exc)[:1024],
        }


def run_cell(
    *,
    request_count: int,
    concurrency: int,
    cell_timeout_seconds: float,
    request: Mapping[str, Any] | Callable[[int], Mapping[str, Any]],
    stream: Callable[..., dict[str, Any]] = streaming.stream_chat,
) -> dict[str, Any]:
    """Run a fixed-count closed-loop cell and summarize raw observations."""

    if request_count < 1:
        raise ValueError("request_count must be positive")
    if concurrency < 1 or concurrency > request_count:
        raise ValueError("concurrency must be between 1 and request_count")
    if not math.isfinite(cell_timeout_seconds) or cell_timeout_seconds <= 0:
        raise ValueError("cell_timeout_seconds must be positive")
    start = time.monotonic()
    absolute_deadline_ns = time.monotonic_ns() + int(cell_timeout_seconds * 1_000_000_000)

    def deadline_bound_request(index: int) -> Mapping[str, Any]:
        raw = request(index) if callable(request) else request
        bounded = dict(raw)
        bounded["absolute_deadline_ns"] = absolute_deadline_ns
        return bounded

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_observe, index, deadline_bound_request, stream)
            for index in range(request_count)
        ]
        observations = [future.result() for future in concurrent.futures.as_completed(futures)]
    wall_seconds = time.monotonic() - start
    observations.sort(key=lambda row: row["request_index"])
    return {
        "measured_wall_seconds": wall_seconds,
        "summary": metrics.summarize_requests(observations, wall_seconds, {}),
        "requests": observations,
    }


def parse_matrix(value: str) -> list[tuple[int, int]]:
    """Parse ``input_tokens:concurrency`` cells in execution order."""

    cells: list[tuple[int, int]] = []
    for raw_cell in value.split(","):
        pieces = raw_cell.strip().split(":")
        if len(pieces) != 2:
            raise ValueError("matrix cells must use input_tokens:concurrency")
        try:
            target, concurrency = (int(piece) for piece in pieces)
        except ValueError as exc:
            raise ValueError("matrix cells must contain integers") from exc
        if target < 8 or concurrency < 1:
            raise ValueError("matrix values must be positive and input tokens at least 8")
        cells.append((target, concurrency))
    if not cells:
        raise ValueError("matrix must contain at least one cell")
    return cells


def parse_cell_timeouts(value: str) -> dict[tuple[int, int], float]:
    """Parse ``input_tokens:concurrency:seconds`` without duplicate cells."""

    result: dict[tuple[int, int], float] = {}
    for raw_cell in value.split(","):
        pieces = raw_cell.strip().split(":")
        if len(pieces) != 3:
            raise ValueError("cell timeouts must use input_tokens:concurrency:seconds")
        try:
            target, concurrency = (int(piece) for piece in pieces[:2])
            timeout = float(pieces[2])
        except ValueError as exc:
            raise ValueError("cell timeouts must contain numbers") from exc
        key = (target, concurrency)
        if target < 8 or concurrency < 1 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("cell timeout values must be positive")
        if key in result:
            raise ValueError("cell timeouts must not contain duplicate cells")
        result[key] = timeout
    return result


def validate_workload_binding(
    plan: Mapping[str, Any],
    *,
    runtime: str,
    model: str,
    model_revision: str,
    matrix: list[tuple[int, int]],
    request_count: int,
    warmup_requests: int,
    repetitions: int,
    max_output_tokens: int,
    transformers_version: str,
    seed: int,
    cell_timeouts: Mapping[tuple[int, int], float],
) -> None:
    """Fail closed if CLI traffic differs from the digest-bound plan."""

    manifest = plan.get("manifest")
    if not isinstance(manifest, Mapping) or manifest.get("planning_only") is True:
        raise RuntimeError("plan manifest is absent or planning-only")
    model_plan = manifest.get("model")
    runtimes = manifest.get("runtimes")
    workload = manifest.get("workload")
    if not isinstance(model_plan, Mapping) or not isinstance(runtimes, list) or not isinstance(workload, Mapping):
        raise RuntimeError("plan is missing model, runtime, or workload bindings")
    if model_plan.get("repository") != model or model_plan.get("revision") != model_revision:
        raise RuntimeError("model arguments do not match the plan")
    runtime_ids = {item.get("id") for item in runtimes if isinstance(item, Mapping)}
    if len(runtime_ids) != 1:
        raise RuntimeError("a live execution plan must bind exactly one runtime allocation")
    if runtime not in runtime_ids:
        raise RuntimeError("runtime is not bound by the plan")
    cells = workload.get("cells")
    if not isinstance(cells, list):
        raise RuntimeError("plan workload cells are invalid")
    expected_matrix: list[tuple[int, int]] = []
    expected_timeouts: dict[tuple[int, int], float] = {}
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise RuntimeError("plan workload cell is invalid")
        key = (int(cell["input_tokens"]), int(cell["concurrency"]))
        expected_matrix.append(key)
        expected_timeouts[key] = float(cell["timeout_seconds"])
        if (
            int(cell["requests"]) != request_count
            or int(cell["repetitions"]) != repetitions
            or int(cell["output_tokens"]) != max_output_tokens
        ):
            raise RuntimeError("request, repetition, or output settings do not match the plan")
    if matrix != expected_matrix or dict(cell_timeouts) != expected_timeouts:
        raise RuntimeError("matrix or per-cell timeouts do not match the plan")
    execution = manifest.get("execution")
    if not isinstance(execution, Mapping):
        raise RuntimeError("execution-ready plan is missing its execution contract")
    execution_workload = execution.get("workload")
    execution_runtimes = execution.get("runtimes")
    execution_model = execution.get("model")
    if (
        not isinstance(execution_workload, Mapping)
        or not isinstance(execution_runtimes, list)
        or not isinstance(execution_model, Mapping)
    ):
        raise RuntimeError("execution model, workload, or runtimes are invalid")
    if (
        execution_model.get("tokenizer_repository") != model
        or execution_model.get("tokenizer_revision") != model_revision
        or not isinstance(execution_model.get("chat_template"), Mapping)
        or execution_model["chat_template"].get("revision") != model_revision
    ):
        raise RuntimeError("tokenizer identity or chat-template revision does not match the plan")
    selected_runtime = next(
        (
            item
            for item in execution_runtimes
            if isinstance(item, Mapping) and item.get("id") == runtime
        ),
        None,
    )
    dependencies = selected_runtime.get("dependencies") if isinstance(selected_runtime, Mapping) else None
    if not isinstance(dependencies, list):
        raise RuntimeError("runtime dependency bindings are absent")
    transformers_dependencies = [
        item
        for item in dependencies
        if isinstance(item, Mapping) and str(item.get("name", "")).casefold() == "transformers"
    ]
    if len(transformers_dependencies) != 1 or transformers_dependencies[0].get("version") != transformers_version:
        raise RuntimeError("Transformers version does not match the plan")
    sampling = execution_workload.get("sampling")
    if (
        execution_workload.get("seed") != seed
        or execution_workload.get("repetitions") != repetitions
        or execution_workload.get("warmup_requests") != warmup_requests
        or not isinstance(sampling, Mapping)
        or str(sampling.get("temperature")) not in {"0", "0.0"}
        or str(sampling.get("top_p")) not in {"1", "1.0"}
        or sampling.get("top_k") != 0
        or execution_workload.get("load_mode") != "closed-loop"
    ):
        raise RuntimeError(
            "seed, sampling, warmups, repetitions, or load mode do not match the plan"
        )
    expected_contract = workload_contract(
        model=model,
        model_revision=model_revision,
        matrix=matrix,
        request_count=request_count,
        repetitions=repetitions,
        seed=seed,
    )
    if (
        execution_workload.get("dataset") != expected_contract["dataset"]
        or execution_workload.get("prompt_cells") != expected_contract["prompt_cells"]
    ):
        raise RuntimeError("prompt generator or cell contract does not match the plan")


def assert_guard_allows_new_work(
    guard_dir: pathlib.Path, plan: Mapping[str, Any] | None = None
) -> None:
    """Fail closed before starting another arm or measurement cell."""

    if any((directory / "teardown-now").exists() for directory in (guard_dir, guard_dir / "markers")):
        raise RuntimeError("local guard marker teardown-now blocks new work")
    if any((directory / "stop-new-arms").exists() for directory in (guard_dir, guard_dir / "markers")):
        raise RuntimeError("local guard marker stop-new-arms blocks new work")
    if plan is None:
        return
    guards = plan.get("guards")
    if not isinstance(guards, Mapping):
        raise RuntimeError("local guard plan is missing")
    stale_after = guards.get("heartbeat_stale_after_seconds")
    if not isinstance(stale_after, int) or stale_after < 1:
        raise RuntimeError("local guard heartbeat policy is invalid")
    launch_path = guard_dir / "watchdog-launch.json"
    try:
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
        nonce = launch["launch_nonce"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("local guard heartbeat launch record is missing") from exc
    now = time.monotonic()
    for role in ("primary", "secondary"):
        try:
            heartbeat = json.loads(
                (guard_dir / f"watchdog-{role}-heartbeat.json").read_text(
                    encoding="utf-8"
                )
            )
            observed = float(heartbeat["monotonic_seconds"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"local guard {role} heartbeat is missing") from exc
        if heartbeat.get("role") != role or heartbeat.get("launch_nonce") != nonce:
            raise RuntimeError(f"local guard {role} heartbeat identity is invalid")
        if heartbeat.get("provider_poll_ok") is not True:
            raise RuntimeError(f"local guard {role} provider polling is unhealthy")
        if not math.isfinite(observed) or observed > now or now - observed > stale_after:
            raise RuntimeError(f"local guard {role} heartbeat is stale")


def _write_guard_state(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.replace(path)


def claim_runtime_arm(plan: Mapping[str, Any], guard_dir: pathlib.Path, runtime: str) -> None:
    """Atomically checkpoint the next digest-bound runtime before it starts."""

    assert_guard_allows_new_work(guard_dir, plan)
    guards = plan.get("guards")
    if not isinstance(guards, Mapping) or guards.get("mode") != "local_only_acknowledged":
        raise RuntimeError("plan does not bind local-only runtime arm order")
    order = guards.get("arm_order")
    if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
        raise RuntimeError("plan has invalid runtime arm order")
    path = guard_dir / "arm-order-state.json"
    state: dict[str, Any] = {"next_index": 0, "active_runtime": None}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise RuntimeError("runtime arm order checkpoint is invalid")
        state = loaded
    index = state.get("next_index")
    if not isinstance(index, int) or state.get("active_runtime") is not None:
        raise RuntimeError("runtime arm order checkpoint is not ready")
    expected = order[index] if index < len(order) else None
    if runtime != expected:
        raise RuntimeError(f"runtime arm order requires {expected!r}, not {runtime!r}")
    _write_guard_state(path, {"next_index": index, "active_runtime": runtime})


def complete_runtime_arm(plan: Mapping[str, Any], guard_dir: pathlib.Path, runtime: str) -> None:
    guards = plan.get("guards")
    order = guards.get("arm_order") if isinstance(guards, Mapping) else None
    path = guard_dir / "arm-order-state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    index = state.get("next_index")
    if (
        not isinstance(order, list)
        or not isinstance(index, int)
        or index >= len(order)
        or order[index] != runtime
        or state.get("active_runtime") != runtime
    ):
        raise RuntimeError("runtime arm completion does not match checkpoint")
    _write_guard_state(path, {"next_index": index + 1, "active_runtime": None})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--target-input-tokens", type=int)
    parser.add_argument("--max-output-tokens", type=int, default=128)
    parser.add_argument("--request-count", type=int, default=100)
    parser.add_argument("--warmup-requests", type=int, required=True)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--matrix", help="comma-separated input_tokens:concurrency cells")
    parser.add_argument("--cell-timeouts", help="comma-separated input_tokens:concurrency:seconds")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--transformers-version", required=True)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--guard-dir", type=pathlib.Path)
    parser.add_argument("--plan", type=pathlib.Path)
    return parser.parse_args()


def _write_artifact(path: pathlib.Path, artifact: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    args = _parse_args()
    if args.plan is None:
        raise SystemExit("--plan is required for every live benchmark")
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be positive")
    if args.warmup_requests < 0:
        raise SystemExit("--warmup-requests must be nonnegative")
    plan = load_compiled_plan(args.plan)
    if args.matrix:
        matrix = parse_matrix(args.matrix)
    elif args.target_input_tokens is not None and args.concurrency is not None:
        matrix = [(args.target_input_tokens, args.concurrency)]
    else:
        raise SystemExit("provide --matrix or both --target-input-tokens and --concurrency")
    if not args.cell_timeouts:
        raise SystemExit("--cell-timeouts is required")
    cell_timeouts = parse_cell_timeouts(args.cell_timeouts)
    validate_workload_binding(
        plan,
        runtime=args.runtime,
        model=args.model,
        model_revision=args.model_revision,
        matrix=matrix,
        request_count=args.request_count,
        warmup_requests=args.warmup_requests,
        repetitions=args.repetitions,
        max_output_tokens=args.max_output_tokens,
        transformers_version=args.transformers_version,
        seed=args.seed,
        cell_timeouts=cell_timeouts,
    )
    from transformers import AutoTokenizer

    installed_transformers = importlib.metadata.version("transformers")
    if installed_transformers != args.transformers_version:
        raise RuntimeError(
            f"installed Transformers {installed_transformers} does not match "
            f"approved {args.transformers_version}"
        )

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.model_revision)
    validate_tokenizer_contract(plan, tokenizer)
    if args.guard_dir is not None:
        claim_runtime_arm(plan, args.guard_dir, args.runtime)

    shared = {
        "schema_version": 1,
        "classification": "exploratory_noncanonical",
        "runtime": args.runtime,
        "endpoint": args.endpoint,
        "model": args.model,
        "model_revision": args.model_revision,
        "maximum_output_tokens": args.max_output_tokens,
        "request_count_per_cell": args.request_count,
        "warmup_requests": args.warmup_requests,
        "repetitions": args.repetitions,
        "dependencies": {"transformers": installed_transformers},
        "seed": args.seed,
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    warmup: dict[str, Any] = {
        "request_count": args.warmup_requests,
        "construction": "first matrix cell before measured repetitions",
        "summary": None,
    }
    if args.warmup_requests:
        warmup_target, warmup_cell_concurrency = matrix[0]
        warmup_concurrency = min(args.warmup_requests, warmup_cell_concurrency)
        warmup_prompts = [
            build_prompt(
                tokenizer,
                warmup_target,
                prefix=f"Warmup request {index:08d}. Prepare inference runtime.",
            )
            for index in range(args.warmup_requests)
        ]

        def warmup_request(index: int) -> dict[str, Any]:
            return {
                "url": args.endpoint,
                "runtime_id": args.runtime,
                "runtime_capabilities": {
                    name: True for name in streaming.REQUIRED_STREAM_CAPABILITIES
                },
                "model": args.model,
                "messages": [{"role": "user", "content": warmup_prompts[index]["text"]}],
                "maximum_output_tokens": args.max_output_tokens,
                "temperature": 0.0,
                "top_p": 1.0,
                "top_k": 0,
                "seed": args.seed,
                "timeout_seconds": cell_timeouts[(warmup_target, warmup_cell_concurrency)],
                "_benchmark_input_tokens": warmup_prompts[index]["input_tokens"],
            }

        warmed = run_cell(
            request_count=args.warmup_requests,
            concurrency=warmup_concurrency,
            cell_timeout_seconds=cell_timeouts[(warmup_target, warmup_cell_concurrency)],
            request=warmup_request,
        )
        warmup.update({
            "target_input_tokens": warmup_target,
            "concurrency": warmup_concurrency,
            "timeout_seconds": cell_timeouts[(warmup_target, warmup_cell_concurrency)],
            "summary": warmed["summary"],
        })
        if warmed["summary"]["failed_requests"]:
            _write_artifact(args.output, {**shared, "warmup": warmup, "cells": []})
            return 2
    completed_cells: list[dict[str, Any]] = []
    for repetition in range(1, args.repetitions + 1):
        for target_input_tokens, concurrency in matrix:
            if args.guard_dir is not None:
                assert_guard_allows_new_work(args.guard_dir, plan)
            prompts = [
                build_prompt(
                    tokenizer,
                    target_input_tokens,
                    prefix=(
                        f"Repetition {repetition:03d} cell "
                        f"{target_input_tokens:05d}-{concurrency:03d} request "
                        f"{index:08d}. Measure inference latency."
                    ),
                )
                for index in range(args.request_count)
            ]

            def request(index: int) -> dict[str, Any]:
                return {
                    "url": args.endpoint,
                    "runtime_id": args.runtime,
                    "runtime_capabilities": {
                        name: True for name in streaming.REQUIRED_STREAM_CAPABILITIES
                    },
                    "model": args.model,
                    "messages": [{"role": "user", "content": prompts[index]["text"]}],
                    "maximum_output_tokens": args.max_output_tokens,
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "top_k": 0,
                    "seed": args.seed,
                    "timeout_seconds": cell_timeouts[(target_input_tokens, concurrency)],
                    "_benchmark_input_tokens": prompts[index]["input_tokens"],
                }

            measured = run_cell(
                request_count=args.request_count,
                concurrency=concurrency,
                cell_timeout_seconds=cell_timeouts[(target_input_tokens, concurrency)],
                request=request,
            )
            completed_cells.append({
                "cell_id": (
                    f"repetition-{repetition:02d}-input-{target_input_tokens}"
                    f"-concurrency-{concurrency}"
                ),
                "repetition": repetition,
                "timeout_seconds": cell_timeouts[(target_input_tokens, concurrency)],
                "prompt": {
                    "target_input_tokens": target_input_tokens,
                    "actual_input_tokens_min": min(
                        prompt["input_tokens"] for prompt in prompts
                    ),
                    "actual_input_tokens_max": max(
                        prompt["input_tokens"] for prompt in prompts
                    ),
                    "unique_prompt_count": len({prompt["sha256"] for prompt in prompts}),
                    "construction": "unique leading request id plus deterministic filler",
                },
                "concurrency": concurrency,
                **measured,
            })
            artifact = {**shared, "warmup": warmup, "cells": completed_cells}
            _write_artifact(args.output, artifact)
            print(json.dumps({
                "cell_id": completed_cells[-1]["cell_id"],
                "summary": completed_cells[-1]["summary"],
            }, sort_keys=True), flush=True)
    if args.guard_dir is not None:
        complete_runtime_arm(plan, args.guard_dir, args.runtime)
    return 0 if all(cell["summary"]["failed_requests"] == 0 for cell in completed_cells) else 2


if __name__ == "__main__":
    raise SystemExit(main())
