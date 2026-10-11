"""Episode 1 measurement contract, validation, and fixture-only summaries.

This module is deliberately provider-free.  It cannot create resources or turn a
planning artifact into an approved execution plan.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "episode1.v1"
SEED = 20260923
MODEL_REVISION = "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd"
PROMPT_EVIDENCE_SHA256 = "7a677a21e56e28ab2ca054c3018b3d23a9023395a5f2c085ffcf9ed055a69307"
CHAT_TEMPLATE_SHA256 = "cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f"
TOKENIZER_ASSET_MANIFEST_SHA256 = "5445d56028bf2d1a14c566e10b0fce155c370a0691e774e03a03feb560e58c84"
RUNTIMES = ("vllm-0.29.0", "sglang-0.5.20")
CELLS: tuple[dict[str, Any], ...] = (
    {
        "id": "fixed-short",
        "mode": "fixed_output",
        "input_tokens": 512,
        "output_tokens": 128,
        "requests": 32,
        "warmups": 4,
        "concurrency": 1,
        "cell_deadline_seconds": 180,
        "request_deadline_seconds": 30,
        "slos_ms": {"ttft": 1000, "e2e": 10000},
    },
    {
        "id": "fixed-medium",
        "mode": "fixed_output",
        "input_tokens": 2048,
        "output_tokens": 128,
        "requests": 32,
        "warmups": 4,
        "concurrency": 4,
        "cell_deadline_seconds": 120,
        "request_deadline_seconds": 30,
        "slos_ms": {"ttft": 2000, "e2e": 10000},
    },
    {
        "id": "natural-quality",
        "mode": "natural_stop",
        "input_tokens": None,
        "output_tokens": 128,
        "requests": 24,
        "warmups": 4,
        "concurrency": 1,
        "cell_deadline_seconds": 120,
        "request_deadline_seconds": 20,
        "slos_ms": {"ttft": 1000, "e2e": 5000},
    },
)
_FROZEN_CELLS_JSON = json.dumps(CELLS, sort_keys=True, separators=(",", ":"))


def _fresh_cells() -> list[dict[str, Any]]:
    """Return cells from an immutable serialized baseline, not public objects."""

    return json.loads(_FROZEN_CELLS_JSON)

_OBSERVATION_KEYS = {
    "schema_version", "evidence_class", "request_id", "block_id", "pair_id",
    "runtime", "cell_id", "mode", "warmup", "scheduled_order", "clock_domain",
    "a_ns", "b_ns", "s_ns", "f_ns", "l_ns", "d_ns", "end_ns",
    "content_event_count", "interchunk_gaps_ns", "input_tokens", "output_tokens",
    "streamed_usage_output_tokens", "tokenizer_output_tokens", "stop_reason",
    "status", "reason_code", "fixed_length_valid", "schema_valid",
    "semantic_correct", "nontruncated", "quality_task_id",
}
_STATUSES = {"success", "transport_failure", "http_failure", "sse_failure", "timeout", "cancelled", "unsent"}
_REASON_CODES = {
    "none", "transport", "http_status", "malformed_sse", "missing_usage",
    "token_mismatch", "request_deadline", "cell_deadline", "cancelled_on_drain",
    "tunnel_lost", "not_dispatched", "invalid_stop_reason", "truncated", "quality_invalid",
}
_STOP_REASONS = {"length", "stop", "eos", "cancelled", "timeout", "error", "not_started"}
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def authored_quality_corpus() -> list[dict[str, str]]:
    """Return 24 public, synthetic service-note tasks with frozen gold labels."""

    services = ("billing", "identity", "storage", "network", "compute", "support")
    priorities = ("low", "normal", "high", "urgent")
    tasks: list[dict[str, str]] = []
    for index in range(24):
        service = services[index % len(services)]
        priority = priorities[index // len(services)]
        ticket = f"LAB-{index + 1:03d}"
        note = (
            f"Synthetic learner note {ticket}: service={service}; priority={priority}. "
            "Return one JSON object with exactly the string fields ticket, service, and priority; "
            "emit no prose, markdown, or code fences."
        )
        tasks.append({
            "task_id": f"quality-{index + 1:02d}",
            "note": note,
            "gold_json": canonical_json({"priority": priority, "service": service, "ticket": ticket}),
        })
    return tasks


def evaluate_quality(response_text: str, gold_json: str, stop_reason: str | None) -> dict[str, bool | None]:
    """Apply the frozen strict parser and exact-field semantic evaluator."""

    if not isinstance(response_text, str) or not isinstance(gold_json, str):
        raise ValueError("quality evaluator inputs must be strings")
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    try:
        expected = json.loads(gold_json, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("gold label is invalid JSON") from exc
    if not isinstance(expected, dict) or set(expected) != {"ticket", "service", "priority"}:
        raise ValueError("gold label must use the frozen three-field schema")
    nontruncated = None if stop_reason is None else stop_reason in {"stop", "eos"}
    try:
        parsed = json.loads(response_text, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, ValueError):
        return {"schema_valid": False, "semantic_correct": False, "nontruncated": nontruncated}
    schema_valid = (
        isinstance(parsed, dict)
        and set(parsed) == {"ticket", "service", "priority"}
        and all(isinstance(parsed[field], str) and parsed[field] for field in expected)
    )
    return {
        "schema_valid": schema_valid,
        "semantic_correct": schema_valid and parsed == expected,
        "nontruncated": nontruncated,
    }


def paired_block_schedule() -> list[dict[str, Any]]:
    """Freeze the three imperfectly balanced paired runtime orders."""

    pair_orders = ((RUNTIMES[0], RUNTIMES[1]), (RUNTIMES[1], RUNTIMES[0]), (RUNTIMES[0], RUNTIMES[1]))
    blocks: list[dict[str, Any]] = []
    ordinal = 0
    for pair_index, runtimes in enumerate(pair_orders, 1):
        fixed = ["fixed-short", "fixed-medium"] if pair_index % 2 else ["fixed-medium", "fixed-short"]
        for position, runtime in enumerate(runtimes, 1):
            ordinal += 1
            blocks.append({
                "block_id": f"block-{ordinal:02d}",
                "pair_id": f"pair-{pair_index}",
                "position": position,
                "runtime": runtime,
                "fresh_process_required": True,
                "cell_order": [*fixed, "natural-quality"],
            })
    return blocks


def protocol(corpus_sha256: str, harness_sha256: str) -> dict[str, Any]:
    """Build the complete, non-authorizing Episode 1 protocol."""

    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in (corpus_sha256, harness_sha256)):
        raise ValueError("protocol hashes must be SHA-256 hex digests")
    value = {
        "schema_version": SCHEMA_VERSION,
        "classification": "planning_only",
        "execution_ready": False,
        "approval_phrase": None,
        "question": "Can two serving runtimes execute declared work while preserving a small quality contract and auditable latency/goodput measurements?",
        "scope_limit": "measurement pilot; not capacity, significance, or winner evidence",
        "seed": SEED,
        "model": {
            "repository": "Qwen/Qwen2.5-32B-Instruct",
            "revision": MODEL_REVISION,
            "precision": "bf16",
            "max_context_tokens": 4096,
        },
        "candidate_hardware": {"gpu": "NVIDIA H100 80GB HBM3", "count": 1, "provider_verified": False},
        "runtimes": [
            {
                "id": RUNTIMES[0],
                "upstream_linux_amd64_digest": "sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b",
                "derived_image_digest": None,
                "gpu_compatibility_verified": False,
                "launch_flags": [
                    "--revision=5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
                    "--tokenizer-revision=5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
                    "--dtype=bfloat16", "--kv-cache-dtype=bfloat16",
                    "--gpu-memory-utilization=0.90", "--generation-config=vllm",
                    "--max-model-len=4096", "--max-num-seqs=4",
                    "--no-enable-prefix-caching", "--host=127.0.0.1", "--port=8000",
                ],
                "request_dialect": {"max_tokens_field": "max_completion_tokens", "disabled_top_k": 0},
            },
            {
                "id": RUNTIMES[1],
                "upstream_linux_amd64_digest": "sha256:4bf342cb756a7105e6df9ae81abeb62e891ff70d34b83fdd7a891fa46a494eca",
                "derived_image_digest": None,
                "gpu_compatibility_verified": False,
                "launch_flags": [
                    "--revision=5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
                    "--dtype=bfloat16", "--kv-cache-dtype=bfloat16",
                    "--mem-fraction-static=0.90", "--sampling-defaults=openai",
                    "--context-length=4096", "--max-running-requests=4",
                    "--disable-radix-cache", "--enable-metrics",
                    "--host=127.0.0.1", "--port=8000",
                ],
                "request_dialect": {"max_tokens_field": "max_completion_tokens", "disabled_top_k": -1},
            },
        ],
        "controls": {
            "prefix_reuse": False, "quantization": False, "speculation": False,
            "adapters": False, "constrained_decoding": False, "max_active_requests": 4,
            "temperature": 0, "top_p": 1, "top_k": "disabled_by_validated_runtime_dialect",
            "repetition_penalty": 1, "kv_memory_fraction": 0.90,
        },
        "cells": _fresh_cells(),
        "blocks": paired_block_schedule(),
        "totals": {"measured_requests": 528, "fixed_requests": 384, "natural_requests": 144, "warmups": 72},
        "quality": {"schema_valid_required": 24, "semantic_correct_minimum": 23, "tasks_per_block": 24},
        "hashes": {
            "corpus_sha256": corpus_sha256,
            "harness_sha256": harness_sha256,
            "prompt_evidence_sha256": PROMPT_EVIDENCE_SHA256,
            "chat_template_sha256": CHAT_TEMPLATE_SHA256,
            "tokenizer_asset_manifest_sha256": TOKENIZER_ASSET_MANIFEST_SHA256,
        },
        "provider_inputs": {
            "stock": "unknown", "price_per_hour": None, "account_balance": None,
            "container_digests": "unknown", "supported_flags": "unknown",
        },
        "operator_policy_proposal": {
            "approved": False, "maximum_resource_lifetime_minutes": 120,
            "maximum_spend_usd": 15, "minimum_final_balance_usd": 5,
        },
        "same_device_pairing": "conditional; otherwise comparisons must be labeled unpaired",
    }
    value["protocol_sha256"] = sha256_json(value)
    return value


def verify_protocol(value: Mapping[str, object]) -> None:
    """Reject a changed, executable, or approval-bearing planning protocol."""

    if value.get("schema_version") != SCHEMA_VERSION or value.get("classification") != "planning_only":
        raise ValueError("not an Episode 1 planning protocol")
    if value.get("execution_ready") is not False or value.get("approval_phrase") is not None:
        raise ValueError("Episode 1 preparation cannot authorize execution")
    body = dict(value)
    claimed = body.pop("protocol_sha256", None)
    if not isinstance(claimed, str) or claimed != sha256_json(body):
        raise ValueError("protocol digest mismatch")
    hashes = value.get("hashes")
    if not isinstance(hashes, dict) or set(hashes) != {
        "corpus_sha256", "harness_sha256", "prompt_evidence_sha256",
        "chat_template_sha256", "tokenizer_asset_manifest_sha256",
    }:
        raise ValueError("protocol hashes are not closed")
    if hashes["prompt_evidence_sha256"] != PROMPT_EVIDENCE_SHA256 or hashes["chat_template_sha256"] != CHAT_TEMPLATE_SHA256 or hashes["tokenizer_asset_manifest_sha256"] != TOKENIZER_ASSET_MANIFEST_SHA256:
        raise ValueError("protocol tokenizer or prompt evidence differs from reviewed evidence")
    expected = protocol(hashes["corpus_sha256"], hashes["harness_sha256"])
    if canonical_json(value) != canonical_json(expected):
        raise ValueError("protocol differs from the canonical Episode 1 contract")


def exact_token_filler(prefix: str, target: int, encode: Callable[[str], Sequence[int]]) -> str:
    """Add deterministic filler until a rendered prompt is exactly ``target`` tokens."""

    if target <= 0:
        raise ValueError("target must be positive")
    text = prefix
    previous = -1
    for index in range(target * 4):
        length = len(encode(text))
        if length == target:
            return text
        if length > target or length == previous:
            raise ValueError(f"deterministic filler cannot reach exactly {target} tokens")
        previous = length
        text += f" z{index}"
    raise ValueError(f"deterministic filler did not reach exactly {target} tokens")


def validate_observation(record: Mapping[str, object]) -> dict[str, Any]:
    """Validate a closed raw request observation and derive client metrics."""

    unknown = set(record) - _OBSERVATION_KEYS
    missing = _OBSERVATION_KEYS - set(record)
    if unknown or missing:
        raise ValueError(f"observation fields are closed; missing={sorted(missing)}, unknown={sorted(unknown)}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported observation schema")
    if record["evidence_class"] not in {"local_fixture", "provider_candidate", "provider_measurement"}:
        raise ValueError("invalid evidence class")
    if record["status"] not in _STATUSES or record["reason_code"] not in _REASON_CODES:
        raise ValueError("invalid status or reason code")
    if (record["status"] == "success") != (record["reason_code"] == "none"):
        raise ValueError("success and reason_code must agree")
    if record["stop_reason"] not in _STOP_REASONS:
        raise ValueError("invalid stop reason")
    if record["mode"] not in {"fixed_output", "natural_stop"}:
        raise ValueError("invalid request mode")
    if record["runtime"] not in RUNTIMES or record["cell_id"] not in {cell["id"] for cell in _fresh_cells()}:
        raise ValueError("observation runtime or cell is outside the protocol")
    for field in ("request_id", "block_id", "pair_id"):
        value = record[field]
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"{field} must be an opaque identifier")
    quality_task_id = record["quality_task_id"]
    if quality_task_id is not None and (
        not isinstance(quality_task_id, str) or _IDENTIFIER.fullmatch(quality_task_id) is None
    ):
        raise ValueError("quality_task_id must be null or an opaque identifier")
    if not isinstance(record["scheduled_order"], int) or isinstance(record["scheduled_order"], bool) or record["scheduled_order"] < 1:
        raise ValueError("scheduled_order must be a positive integer")
    if not isinstance(record["warmup"], bool):
        raise ValueError("warmup must be boolean")
    for field in ("fixed_length_valid", "schema_valid", "semantic_correct", "nontruncated"):
        if record[field] is not None and not isinstance(record[field], bool):
            raise ValueError(f"{field} must be boolean or null")
    if record["clock_domain"] != "client_monotonic_ns":
        raise ValueError("all request timestamps must share client_monotonic_ns")
    for field in ("content_event_count", "input_tokens", "output_tokens", "streamed_usage_output_tokens", "tokenizer_output_tokens"):
        value = record[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"{field} must be a nonnegative integer or null")
    gaps = record["interchunk_gaps_ns"]
    if not isinstance(gaps, list) or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in gaps):
        raise ValueError("interchunk_gaps_ns must contain nonnegative integers")

    fields = ("a_ns", "b_ns", "s_ns", "f_ns", "l_ns", "d_ns")
    stamps: list[int | None] = []
    for field in fields:
        value = record[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"{field} must be a nonnegative integer or null")
        stamps.append(value)  # type: ignore[arg-type]
    if stamps[0] is None:
        raise ValueError("every scheduled attempt requires a_ns")
    present = [value for value in stamps if value is not None]
    if present != sorted(present):
        raise ValueError("timestamps must obey a<=b<=s<=f<=l<=d")
    seen_null = False
    for value in stamps:
        if value is None:
            seen_null = True
        elif seen_null:
            raise ValueError("request event timestamps cannot contain gaps")
    if record["status"] == "success" and any(value is None for value in stamps):
        raise ValueError("successful requests require all event timestamps")
    if record["status"] == "unsent" and any(value is not None for value in stamps[1:]):
        raise ValueError("unsent requests cannot contain dispatch or stream events")
    end_ns = record["end_ns"]
    if isinstance(end_ns, bool) or not isinstance(end_ns, int) or end_ns < max(present):
        raise ValueError("end_ns must close the scheduled attempt")
    events = record["content_event_count"]
    if len(gaps) != max(0, events - 1):
        raise ValueError("interchunk gap count must be content_event_count minus one")
    if record["status"] == "success" and events < 1:
        raise ValueError("successful output requires a content event")
    if record["status"] != "success" and events and record["f_ns"] is None:
        raise ValueError("content events require a first-content timestamp")

    usage = record["streamed_usage_output_tokens"]
    tokenizer = record["tokenizer_output_tokens"]
    output = record["output_tokens"]
    if record["status"] == "success" and (usage is None or tokenizer is None or output is None):
        raise ValueError("successful requests require exact usage and tokenizer token counts")
    if usage is not None and tokenizer is not None and usage != tokenizer and record["reason_code"] != "token_mismatch":
        raise ValueError("unexplained output-token disagreement")
    if output is not None and usage is not None and output != usage:
        raise ValueError("output_tokens must match streamed usage")
    if record["reason_code"] == "token_mismatch" and (
        record["status"] == "success" or usage is None or tokenizer is None or usage == tokenizer
    ):
        raise ValueError("token_mismatch requires a failed attempt with two disagreeing counts")
    if record["mode"] == "fixed_output" and record["status"] == "success":
        if record["fixed_length_valid"] is not (output == 128 and record["stop_reason"] == "length"):
            raise ValueError("fixed-output qualification disagrees with length/stop evidence")
    if record["mode"] == "fixed_output":
        expected_input = next(cell["input_tokens"] for cell in _fresh_cells() if cell["id"] == record["cell_id"])
        if record["input_tokens"] is not None and record["input_tokens"] != expected_input:
            raise ValueError("fixed-output input token count differs from the frozen cell")
        if any(record[field] is not None for field in ("schema_valid", "semantic_correct", "nontruncated", "quality_task_id")):
            raise ValueError("fixed-output observations cannot contain quality evidence")
    if record["mode"] == "natural_stop" and record["status"] == "success":
        if record["quality_task_id"] is None:
            raise ValueError("successful natural outputs require a quality task identity")
        if record["stop_reason"] == "length" and record["nontruncated"] is True:
            raise ValueError("length-stopped natural output cannot be nontruncated")

    def delta(later: str, earlier: str) -> float | None:
        left, right = record[later], record[earlier]
        return None if left is None or right is None else (left - right) / 1_000_000  # type: ignore[operator]

    metrics = {
        "scheduling_lag_ms": delta("b_ns", "a_ns"),
        "send_preparation_ms": delta("s_ns", "b_ns"),
        "send_lag_ms": delta("s_ns", "a_ns"),
        "ttft_ms": delta("f_ns", "s_ns"),
        "e2e_ms": delta("d_ns", "s_ns"),
        "user_elapsed_ms": delta("d_ns", "a_ns"),
        "terminal_overhead_ms": delta("d_ns", "l_ns"),
        "content_span_ms": delta("l_ns", "f_ns"),
    }
    if output is not None and output >= 2 and metrics["content_span_ms"] is not None:
        metrics["tpot_ms"] = metrics["content_span_ms"] / (output - 1)
    else:
        metrics["tpot_ms"] = None
    metrics["coalesced_content"] = bool(output and output > 1 and record["content_event_count"] == 1)
    return {**record, "derived": metrics}


def summarize_cell(records: Iterable[Mapping[str, object]], window_start_ns: int, window_end_ns: int, cell: Mapping[str, object]) -> dict[str, Any]:
    """Summarize one cell with one wall-time denominator including failure/drain."""

    observations = [validate_observation(record) for record in records]
    if not observations:
        raise ValueError("cell requires at least one scheduled observation")
    identities = ("evidence_class", "runtime", "block_id", "pair_id", "cell_id", "mode")
    if any(len({record[field] for record in observations}) != 1 for field in identities):
        raise ValueError("cell observations cannot mix provenance or identities")
    if len({record["request_id"] for record in observations}) != len(observations):
        raise ValueError("duplicate request identifiers")
    if any(record["warmup"] for record in observations):
        raise ValueError("warmups must be excluded from measured cell summaries")
    if observations[0]["cell_id"] != cell.get("id") or observations[0]["mode"] != cell.get("mode"):
        raise ValueError("observations do not match the declared cell")
    if window_start_ns != min(record["a_ns"] for record in observations) or window_end_ns != max(record["end_ns"] for record in observations):
        raise ValueError("cell wall interval must equal first eligibility through final completion/drain")
    seconds = (window_end_ns - window_start_ns) / 1_000_000_000
    if seconds <= 0:
        raise ValueError("cell wall interval must be positive")
    expected = int(cell["requests"])
    if len(observations) != expected:
        raise ValueError(f"expected {expected} scheduled attempts, received {len(observations)}")
    success = [record for record in observations if record["status"] == "success"]
    dispatched = [record for record in observations if record["b_ns"] is not None]
    exact_tokens = [record["output_tokens"] for record in success]
    token_complete = all(isinstance(value, int) for value in exact_tokens)
    slos = cell["slos_ms"]

    def latency_ok(record: Mapping[str, Any]) -> bool | None:
        ttft, e2e = record["derived"]["ttft_ms"], record["derived"]["e2e_ms"]
        if ttft is None or e2e is None:
            return None
        return ttft <= slos["ttft"] and e2e <= slos["e2e"]

    qualification: list[bool | None] = []
    for record in success:
        latency = latency_ok(record)
        if cell["mode"] == "fixed_output":
            evidence = record["fixed_length_valid"]
            qualification.append(None if latency is None or evidence is None else latency and evidence)
        else:
            evidence = (record["schema_valid"], record["semantic_correct"], record["nontruncated"])
            qualification.append(None if latency is None or any(value is None for value in evidence) else latency and all(evidence))
    qualified_available = all(value is not None for value in qualification)
    qualified_count = sum(value is True for value in qualification) if qualified_available else None
    qualified_tokens = (
        sum(record["output_tokens"] for record, qualified in zip(success, qualification) if qualified)
        if qualified_available and token_complete else None
    )

    def rate(value: int | None, unit: str, unavailable_reason: str | None = None) -> dict[str, Any]:
        available = value is not None and unavailable_reason is None
        return {"available": available, "value": value / seconds if available else None, "unit": unit, "wall_seconds": seconds, "unavailable_reason": None if available else unavailable_reason}

    counts = {name: sum(record["status"] == status for record in observations) for name, status in (
        ("failed", "transport_failure"), ("http_failed", "http_failure"), ("sse_failed", "sse_failure"),
        ("timeout", "timeout"), ("cancelled", "cancelled"), ("unsent", "unsent"),
    )}
    counts.update({
        "scheduled": len(observations), "dispatched": len(dispatched), "transport_success": len(success),
        "fixed_length_valid": sum(record["fixed_length_valid"] is True for record in success),
        "schema_valid": sum(record["schema_valid"] is True for record in success),
        "semantic_correct": sum(record["semantic_correct"] is True for record in success),
        "nontruncated": sum(record["nontruncated"] is True for record in success),
        "quality_valid": sum(record["schema_valid"] is True and record["semantic_correct"] is True and record["nontruncated"] is True for record in success),
        "slo_qualified": qualified_count,
        "successful_output_tokens": sum(exact_tokens) if token_complete else None,
        "qualified_output_tokens": qualified_tokens,
    })
    latencies: dict[str, Any] = {}
    for name in ("scheduling_lag_ms", "send_preparation_ms", "ttft_ms", "e2e_ms", "terminal_overhead_ms", "tpot_ms"):
        values = sorted(record["derived"][name] for record in success if record["derived"][name] is not None)
        latencies[name] = _distribution(values)
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": observations[0]["evidence_class"],
        "runtime": observations[0]["runtime"], "block_id": observations[0]["block_id"],
        "pair_id": observations[0]["pair_id"], "cell_id": observations[0]["cell_id"],
        "mode": cell["mode"], "counts": counts, "latency": latencies,
        "throughput": {
            "requests": rate(len(success), "requests/s"),
            "output_tokens": rate(sum(exact_tokens) if token_complete else None, "tokens/s", None if token_complete else "missing exact successful output-token evidence"),
            "request_goodput": rate(qualified_count, "requests/s", None if qualified_available else "missing SLO or quality evidence"),
            "token_goodput": rate(qualified_tokens, "tokens/s", None if qualified_available and token_complete else "missing SLO, quality, or token evidence"),
        },
        "stop_reasons": {reason: sum(record["stop_reason"] == reason for record in observations) for reason in sorted(_STOP_REASONS)},
        "coalesced_content_requests": sum(record["derived"]["coalesced_content"] for record in success),
        "notes": ["per-block primary summary", "p95 is descriptive", "p99 intentionally omitted"],
    }


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"available": False, "count": 0, "p50": None, "p95": None, "unavailable_reason": "no applicable observations"}
    def percentile(q: float) -> float:
        rank = (len(values) - 1) * q
        low, high = math.floor(rank), math.ceil(rank)
        return values[low] if low == high else values[low] + (values[high] - values[low]) * (rank - low)
    return {"available": True, "count": len(values), "p50": percentile(.5), "p95": percentile(.95), "unavailable_reason": None}


def export_public_fixture(protocol_value: Mapping[str, object], summaries: Sequence[Mapping[str, object]], telemetry: Sequence[Mapping[str, object]], *, transport_exercised: bool = False) -> dict[str, Any]:
    """Export aggregates through a fixed allowlist; raw request data cannot pass."""

    verify_protocol(protocol_value)
    allowed_summary = {"schema_version", "classification", "runtime", "block_id", "pair_id", "cell_id", "mode", "counts", "latency", "throughput", "stop_reasons", "coalesced_content_requests", "notes"}
    declared_blocks = {block["block_id"]: block for block in paired_block_schedule()}
    frozen_cells = _fresh_cells()
    expected_keys = {(block_id, cell["id"]) for block_id in declared_blocks for cell in frozen_cells}
    exported: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for summary in summaries:
        if summary.get("classification") != "local_fixture" or set(summary) != allowed_summary:
            raise ValueError("only allowlisted local-fixture aggregates may be exported")
        if summary.get("schema_version") != SCHEMA_VERSION or summary.get("mode") not in {"fixed_output", "natural_stop"}:
            raise ValueError("summary schema or mode is invalid")
        if summary.get("runtime") not in RUNTIMES or summary.get("cell_id") not in {cell["id"] for cell in frozen_cells}:
            raise ValueError("summary identity is outside the protocol")
        block = declared_blocks.get(summary.get("block_id"))
        if block is None or summary.get("pair_id") != block["pair_id"] or summary.get("runtime") != block["runtime"]:
            raise ValueError("summary identity does not match the frozen schedule")
        cell = next(item for item in frozen_cells if item["id"] == summary["cell_id"])
        if summary.get("mode") != cell["mode"]:
            raise ValueError("summary mode does not match the frozen cell")
        key = (summary["block_id"], summary["cell_id"])
        if key in seen_keys:
            raise ValueError("duplicate block/cell summary")
        seen_keys.add(key)
        counts = summary.get("counts")
        expected_counts = {"failed", "http_failed", "sse_failed", "timeout", "cancelled", "unsent", "scheduled", "dispatched", "transport_success", "fixed_length_valid", "schema_valid", "semantic_correct", "nontruncated", "quality_valid", "slo_qualified", "successful_output_tokens", "qualified_output_tokens"}
        if not isinstance(counts, dict) or set(counts) != expected_counts or any(value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0) for value in counts.values()):
            raise ValueError("summary counts are not closed nonnegative integers")
        failures = sum(counts[name] for name in ("failed", "http_failed", "sse_failed", "timeout", "cancelled", "unsent"))
        if counts["scheduled"] != cell["requests"] or counts["scheduled"] != counts["transport_success"] + failures or counts["dispatched"] != counts["scheduled"] - counts["unsent"]:
            raise ValueError("summary attempt counts do not reconcile")
        if any(counts[name] > counts["transport_success"] for name in ("fixed_length_valid", "schema_valid", "semantic_correct", "nontruncated", "quality_valid")) or (counts["slo_qualified"] is not None and counts["slo_qualified"] > counts["transport_success"]):
            raise ValueError("qualification counts exceed successful requests")
        qualifying_evidence = counts["fixed_length_valid"] if cell["mode"] == "fixed_output" else counts["quality_valid"]
        if counts["slo_qualified"] is not None and counts["slo_qualified"] > qualifying_evidence:
            raise ValueError("SLO qualification exceeds mode-specific valid evidence")
        if (cell["mode"] == "fixed_output" and any(counts[name] != 0 for name in ("schema_valid", "semantic_correct", "nontruncated", "quality_valid"))) or (cell["mode"] == "natural_stop" and counts["fixed_length_valid"] != 0):
            raise ValueError("mode-inapplicable qualification count is nonzero")
        latency = summary.get("latency")
        if not isinstance(latency, dict) or set(latency) != {"scheduling_lag_ms", "send_preparation_ms", "ttft_ms", "e2e_ms", "terminal_overhead_ms", "tpot_ms"}:
            raise ValueError("summary latency is not closed")
        for metric in latency.values():
            _validate_distribution(metric)
        for name in ("scheduling_lag_ms", "send_preparation_ms", "ttft_ms", "e2e_ms", "terminal_overhead_ms"):
            if latency[name]["count"] != counts["transport_success"]:
                raise ValueError("successful request latency coverage is incomplete")
        if latency["tpot_ms"]["count"] > counts["transport_success"]:
            raise ValueError("TPOT coverage exceeds successful requests")
        throughput = summary.get("throughput")
        expected_rates = {"requests": "requests/s", "output_tokens": "tokens/s", "request_goodput": "requests/s", "token_goodput": "tokens/s"}
        if not isinstance(throughput, dict) or set(throughput) != set(expected_rates):
            raise ValueError("summary throughput is not closed")
        for name, unit in expected_rates.items():
            _validate_rate(throughput[name], unit)
        walls = {throughput[name]["wall_seconds"] for name in expected_rates}
        if len(walls) != 1 or not math.isclose(throughput["requests"]["value"], counts["transport_success"] / next(iter(walls))):
            raise ValueError("rates do not share the declared wall denominator")
        rate_bindings = (("output_tokens", "successful_output_tokens"), ("request_goodput", "slo_qualified"), ("token_goodput", "qualified_output_tokens"))
        for rate_name, count_name in rate_bindings:
            rate, count_value = throughput[rate_name], counts[count_name]
            if (count_value is None) != (not rate["available"]):
                raise ValueError("rate availability does not match its bound count")
            if count_value is not None and not math.isclose(rate["value"], count_value / next(iter(walls))):
                raise ValueError("rate does not reconcile with its count and wall")
        stops = summary.get("stop_reasons")
        if not isinstance(stops, dict) or set(stops) != _STOP_REASONS or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in stops.values()):
            raise ValueError("stop reasons are invalid")
        if sum(stops.values()) != counts["scheduled"]:
            raise ValueError("stop reasons do not cover every scheduled attempt")
        if summary.get("notes") != ["per-block primary summary", "p95 is descriptive", "p99 intentionally omitted"]:
            raise ValueError("summary notes are not from the closed vocabulary")
        if not isinstance(summary.get("coalesced_content_requests"), int) or isinstance(summary.get("coalesced_content_requests"), bool) or not 0 <= summary["coalesced_content_requests"] <= counts["transport_success"]:
            raise ValueError("invalid coalescing count")
        exported.append(json.loads(canonical_json(summary)))
    if seen_keys != expected_keys:
        raise ValueError("public fixture must contain each frozen block/cell exactly once")
    telemetry_keys: set[tuple[str, str, str]] = set()
    metric_contract = {
        "gpu_power_watts": ("W", "gpu_sampler"), "gpu_utilization_percent": ("%", "gpu_sampler"),
        "gpu_memory_mib": ("MiB", "gpu_sampler"), "runtime_queue_requests": ("requests", "runtime_native"),
        "kv_cache_utilization": ("fraction", "runtime_native"),
    }
    for entry in telemetry:
        if set(entry) != {"runtime", "block_id", "cell_id", "metric", "available", "unit", "source", "window", "value", "unavailable_reason"}:
            raise ValueError("telemetry export is closed and allowlisted")
        if entry["runtime"] not in RUNTIMES or entry["cell_id"] not in {cell["id"] for cell in frozen_cells} or not isinstance(entry["block_id"], str) or _IDENTIFIER.fullmatch(entry["block_id"]) is None:
            raise ValueError("telemetry identity is invalid")
        block = declared_blocks.get(entry["block_id"])
        if block is None or block["runtime"] != entry["runtime"]:
            raise ValueError("telemetry runtime does not match its frozen block")
        if entry["metric"] not in metric_contract:
            raise ValueError("telemetry metric is not allowlisted")
        if (entry["unit"], entry["source"]) != metric_contract[entry["metric"]] or entry["window"] not in {"cell", "block"}:
            raise ValueError("telemetry metadata is invalid")
        telemetry_key = (entry["block_id"], entry["cell_id"], entry["metric"])
        if telemetry_key in telemetry_keys:
            raise ValueError("duplicate telemetry entry")
        telemetry_keys.add(telemetry_key)
        if not isinstance(entry["available"], bool):
            raise ValueError("telemetry availability must be boolean")
        if entry["available"]:
            value = _finite(entry["value"], "telemetry value")
            if value < 0 or (entry["metric"] == "gpu_utilization_percent" and value > 100) or (entry["metric"] == "kv_cache_utilization" and value > 1):
                raise ValueError("telemetry value is outside its physical range")
            if entry["unavailable_reason"] is not None:
                raise ValueError("available telemetry cannot have an unavailable reason")
        elif entry["value"] is not None or entry["unavailable_reason"] not in {"local fixture has no GPU telemetry", "unsupported by runtime", "capture gap", "counter reset"}:
            raise ValueError("unavailable telemetry requires a fixed reason and null value")
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": "local_fixture_not_provider_measurement",
        "execution_ready": False,
        "provider_charges": "not_applicable",
        "protocol_sha256": protocol_value["protocol_sha256"],
        "summaries": exported,
        "telemetry": [json.loads(canonical_json(entry)) for entry in telemetry],
        "limitations": [
            (
                "loopback HTTP/SSE transport was exercised; no serving runtime was exercised"
                if transport_exercised else "synthetic contract timings; no transport was exercised"
            ), "no GPU was used", "no runtime image or flag was verified",
            "not paid evidence and not approval evidence",
        ],
    }


def _validate_distribution(metric: object) -> None:
    if not isinstance(metric, dict) or set(metric) != {"available", "count", "p50", "p95", "unavailable_reason"}:
        raise ValueError("distribution shape is invalid")
    if not isinstance(metric["available"], bool) or isinstance(metric["count"], bool) or not isinstance(metric["count"], int) or metric["count"] < 0:
        raise ValueError("distribution availability/count is invalid")
    if metric["available"]:
        p50 = _finite(metric["p50"], "p50")
        p95 = _finite(metric["p95"], "p95")
        if metric["count"] < 1 or p50 < 0 or p95 < p50:
            raise ValueError("distribution count/percentiles are inconsistent")
        if metric["unavailable_reason"] is not None:
            raise ValueError("available distribution cannot have a reason")
    elif metric["p50"] is not None or metric["p95"] is not None or metric["unavailable_reason"] != "no applicable observations":
        raise ValueError("unavailable distribution is invalid")


def _validate_rate(metric: object, unit: str) -> None:
    if not isinstance(metric, dict) or set(metric) != {"available", "value", "unit", "wall_seconds", "unavailable_reason"} or metric["unit"] != unit:
        raise ValueError("rate shape or unit is invalid")
    wall = _finite(metric["wall_seconds"], "wall_seconds")
    if wall <= 0 or not isinstance(metric["available"], bool):
        raise ValueError("rate wall/availability is invalid")
    if metric["available"]:
        if _finite(metric["value"], "rate value") < 0 or metric["unavailable_reason"] is not None:
            raise ValueError("available rate is invalid")
    elif metric["value"] is not None or metric["unavailable_reason"] not in {"missing exact successful output-token evidence", "missing SLO or quality evidence", "missing SLO, quality, or token evidence"}:
        raise ValueError("unavailable rate is invalid")


def append_phase(ledger: list[dict[str, Any]], phase: str, start_ns: int, end_ns: int, start_utc: str, end_utc: str, accounting_class: str, amount_usd: float | None, source_artifact_sha256: str) -> dict[str, Any]:
    """Append an immutable, hash-chained phase record."""

    allowed = {"preflight", "startup", "warmup", "measurement", "export", "teardown", "settlement"}
    if phase not in allowed or accounting_class not in {"observed", "estimated", "not_available", "not_applicable_fixture"}:
        raise ValueError("invalid phase or accounting class")
    if isinstance(start_ns, bool) or isinstance(end_ns, bool) or not isinstance(start_ns, int) or not isinstance(end_ns, int) or start_ns < 0 or end_ns < start_ns:
        raise ValueError("phase end precedes start")
    if ledger and start_ns < ledger[-1]["end_ns"]:
        raise ValueError("phase intervals cannot overlap")
    if re.fullmatch(r"[0-9a-f]{64}", source_artifact_sha256) is None:
        raise ValueError("phase source artifact digest is invalid")
    start_time, end_time = _utc(start_utc), _utc(end_utc)
    if end_time < start_time:
        raise ValueError("phase UTC end precedes start")
    if abs((end_time - start_time).total_seconds() - (end_ns - start_ns) / 1_000_000_000) > .001:
        raise ValueError("UTC and monotonic phase durations disagree")
    if amount_usd is not None and (_finite(amount_usd, "amount_usd") < 0):
        raise ValueError("amount_usd must be nonnegative and finite")
    if accounting_class == "not_applicable_fixture" and amount_usd is not None:
        raise ValueError("fixture phases cannot contain provider charge amounts")
    previous = ledger[-1]["record_sha256"] if ledger else "0" * 64
    body = {
        "schema_version": SCHEMA_VERSION, "evidence_class": "local_fixture", "clock_domain": "fixture_monotonic_ns",
        "sequence": len(ledger) + 1, "phase": phase, "start_ns": start_ns, "end_ns": end_ns,
        "start_utc": start_utc, "end_utc": end_utc, "accounting_class": accounting_class,
        "amount_usd": amount_usd, "source_artifact_sha256": source_artifact_sha256,
        "previous_sha256": previous,
    }
    body["record_sha256"] = sha256_json(body)
    ledger.append(body)
    return body


def verify_phase_ledger(ledger: Sequence[Mapping[str, object]]) -> None:
    previous = "0" * 64
    previous_end = 0
    allowed_fields = {"schema_version", "evidence_class", "clock_domain", "sequence", "phase", "start_ns", "end_ns", "start_utc", "end_utc", "accounting_class", "amount_usd", "source_artifact_sha256", "previous_sha256", "record_sha256"}
    expected_phases = ["preflight", "startup", "warmup", "measurement", "export", "teardown", "settlement"]
    for index, record in enumerate(ledger, 1):
        if set(record) != allowed_fields or record.get("schema_version") != SCHEMA_VERSION or record.get("evidence_class") != "local_fixture" or record.get("clock_domain") != "fixture_monotonic_ns":
            raise ValueError("phase ledger record is not closed fixture evidence")
        if record.get("sequence") != index or record.get("previous_sha256") != previous:
            raise ValueError("phase ledger sequence or chain is invalid")
        if index > len(expected_phases) or record.get("phase") != expected_phases[index - 1]:
            raise ValueError("phase ledger order is invalid")
        if not isinstance(record.get("start_ns"), int) or not isinstance(record.get("end_ns"), int) or record["start_ns"] < previous_end or record["end_ns"] < record["start_ns"]:
            raise ValueError("phase ledger monotonic intervals are invalid")
        start_time, end_time = _utc(record["start_utc"]), _utc(record["end_utc"])
        if abs((end_time - start_time).total_seconds() - (record["end_ns"] - record["start_ns"]) / 1_000_000_000) > .001:
            raise ValueError("phase ledger clock durations disagree")
        if re.fullmatch(r"[0-9a-f]{64}", record["source_artifact_sha256"]) is None:
            raise ValueError("phase source artifact digest is invalid")
        if record["accounting_class"] != "not_applicable_fixture" or record["amount_usd"] is not None:
            raise ValueError("fixture ledger cannot represent provider charges")
        body = dict(record)
        claimed = body.pop("record_sha256", None)
        if claimed != sha256_json(body):
            raise ValueError("phase ledger digest mismatch")
        previous = str(claimed)
        previous_end = record["end_ns"]
    if len(ledger) != len(expected_phases):
        raise ValueError("fixture phase ledger is incomplete")


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC timestamps must be ISO-8601 strings ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc
