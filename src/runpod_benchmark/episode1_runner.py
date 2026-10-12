"""Provider-free Episode 1 cell runner for an already-running loopback endpoint.

This module has no provider or resource-creation integration.  Its output is
always local-fixture evidence; a future approved execution adapter must add
provider identity, image, lifecycle, telemetry, and settlement evidence.
"""

from __future__ import annotations

import ipaddress
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

from .episode1 import SCHEMA_VERSION, SEED, evaluate_quality, summarize_cell, validate_observation
from .streaming import StreamingError, stream_chat


_SPEC_KEYS = {"request_id", "messages", "quality_task_id", "gold_json"}
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
_CAPABILITIES = {
    "streaming_sse": True,
    "done_event": True,
    "streamed_usage": True,
    "exact_completion_tokens": True,
}


class _LinkedCancellation:
    """Cell-local cancellation with a read-only upstream teardown signal."""

    def __init__(self, upstream: threading.Event | None) -> None:
        self._local = threading.Event()
        self._upstream = upstream

    def set(self) -> None:
        self._local.set()

    def is_set(self) -> bool:
        return self._local.is_set() or bool(self._upstream and self._upstream.is_set())

    def reason_code(self) -> str | None:
        if self._upstream is not None and self._upstream.is_set():
            source = getattr(self._upstream, "reason_code", None)
            reason = source() if callable(source) else "cancelled_on_drain"
            if reason not in {"cancelled_on_drain", "tunnel_lost"}:
                raise ValueError("upstream cancellation reason is outside the closed schema")
            return reason
        return "cancelled_on_drain" if self._local.is_set() else None


def _require_loopback(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username is not None or parsed.password is not None:
        raise ValueError("fixture runner requires an unauthenticated HTTP loopback endpoint")
    host = parsed.hostname
    if host == "localhost":
        return
    try:
        if host is not None and ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError("fixture runner refuses non-loopback endpoints")


def _failure(exc: StreamingError, cancel_event: _LinkedCancellation) -> tuple[str, str, str]:
    message = str(exc).lower()
    if exc.deadline_exceeded or exc.request_timed_out or "timed out" in message:
        return "timeout", "cell_deadline" if exc.deadline_exceeded else "request_deadline", "timeout"
    if "cancel" in message:
        return "cancelled", cancel_event.reason_code() or "cancelled_on_drain", "cancelled"
    if "http error" in message or "http status" in message:
        return "http_failure", "http_status", "error"
    if "usage" in message:
        return "sse_failure", "missing_usage", "error"
    if "stream" in message or "sse" in message or "malformed" in message or "[done]" in message:
        return "sse_failure", "malformed_sse", "error"
    return "transport_failure", "transport", "error"


def _validated_raw(record: Mapping[str, Any]) -> dict[str, Any]:
    checked = validate_observation(record)
    checked.pop("derived")
    return checked


def run_fixture_cell(
    *,
    endpoint_url: str,
    model: str,
    block: Mapping[str, Any],
    cell: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    input_token_counter: Callable[[Sequence[Mapping[str, str]]], int],
    output_token_counter: Callable[[str], int],
    stream: Callable[[Mapping[str, Any]], Mapping[str, Any]] = stream_chat,
    clock: Callable[[], int] = time.monotonic_ns,
    evidence_class: str = "local_fixture",
    warmup: bool = False,
    external_cancel_event: threading.Event | None = None,
    record_callback: Callable[[Mapping[str, Any]], None] | None = None,
    lifecycle_callback: Callable[[Mapping[str, Any]], None] | None = None,
    absolute_deadline_ns: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one frozen cell and retain every scheduled attempt.

    Provider evidence is opt-in and is expected to be selected only after the
    caller has completed allocation/runtime attestation.  The optional callback
    receives each already-schema-validated observation as soon as it is final.
    The lifecycle callback receives closed scheduled/dispatched/finalized facts;
    callers that make it durable can retain proof even if transport code crashes.
    """

    _require_loopback(endpoint_url)
    if len(requests) != cell["requests"]:
        raise ValueError("request list must exactly match the frozen cell size")
    if set(block) < {"block_id", "pair_id", "runtime"}:
        raise ValueError("block identity is incomplete")
    for field in ("block_id", "pair_id"):
        if not isinstance(block[field], str) or _IDENTIFIER.fullmatch(block[field]) is None:
            raise ValueError(f"{field} must be an opaque identifier")
    if not isinstance(model, str) or not model:
        raise ValueError("model identity is required")
    if evidence_class not in {"local_fixture", "provider_candidate", "provider_measurement"}:
        raise ValueError("evidence_class is unsupported")
    if not isinstance(warmup, bool):
        raise ValueError("warmup must be boolean")
    runtime = str(block["runtime"])
    if runtime.startswith("vllm-"):
        dialect, top_k = "vllm", 0
    elif runtime.startswith("sglang-"):
        dialect, top_k = "sglang", -1
    else:
        raise ValueError("runtime is outside the frozen Episode 1 pair")
    for spec in requests:
        if set(spec) != _SPEC_KEYS:
            raise ValueError("request specifications use a closed schema")
        if not isinstance(spec["request_id"], str) or _IDENTIFIER.fullmatch(spec["request_id"]) is None:
            raise ValueError("request_id must be an opaque identifier")
        if not isinstance(spec["messages"], list) or not spec["messages"]:
            raise ValueError("request messages must be non-empty")
        quality_id = spec["quality_task_id"]
        if quality_id is not None and (
            not isinstance(quality_id, str) or _IDENTIFIER.fullmatch(quality_id) is None
        ):
            raise ValueError("quality_task_id must be null or an opaque identifier")
        if cell["mode"] == "fixed_output" and (quality_id is not None or spec["gold_json"] is not None):
            raise ValueError("fixed-output specifications cannot contain quality evidence")
        if cell["mode"] == "natural_stop" and (
            quality_id is None or not isinstance(spec["gold_json"], str)
        ):
            raise ValueError("natural-stop specifications require quality identity and gold JSON")
    if len({spec["request_id"] for spec in requests}) != len(requests):
        raise ValueError("request identifiers must be unique before transport")

    input_counts: list[int] = []
    for spec in requests:
        count_value = input_token_counter(spec["messages"])
        if isinstance(count_value, bool) or not isinstance(count_value, int) or count_value < 1:
            raise ValueError("input token counter returned an invalid count")
        if cell["input_tokens"] is not None and count_value != cell["input_tokens"]:
            raise ValueError("fixed prompt does not match the frozen exact input token count")
        input_counts.append(count_value)

    count = len(requests)
    next_index = 0
    queue_lock = threading.Lock()
    records: list[dict[str, Any] | None] = [None] * count
    cell_start_ns = clock()
    declared_deadline_ns = cell_start_ns + int(cell["cell_deadline_seconds"] * 1_000_000_000)
    if absolute_deadline_ns is not None and (
        isinstance(absolute_deadline_ns, bool) or not isinstance(absolute_deadline_ns, int)
    ):
        raise ValueError("absolute deadline must be monotonic nanoseconds")
    cell_deadline_ns = min(declared_deadline_ns, absolute_deadline_ns or declared_deadline_ns)
    cancel_event = _LinkedCancellation(external_cancel_event)

    def lifecycle(index: int, stage: str, at_ns: int) -> None:
        if lifecycle_callback is not None:
            lifecycle_callback({
                "schema_version": "episode1.request-lifecycle.v1",
                "request_id": requests[index]["request_id"],
                "block_id": block["block_id"],
                "cell_id": cell["id"],
                "scheduled_order": index + 1,
                "clock_domain": "client_monotonic_ns",
                "stage": stage,
                "at_ns": at_ns,
            })

    def retain(index: int, value: Mapping[str, Any]) -> None:
        checked = _validated_raw(value)
        records[index] = checked
        if record_callback is not None:
            record_callback(checked)
        lifecycle(index, "finalized", int(checked["end_ns"]))

    def unsent(index: int, a_ns: int, reason_code: str = "not_dispatched") -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "evidence_class": evidence_class,
            "request_id": requests[index]["request_id"], "block_id": block["block_id"],
            "pair_id": block["pair_id"], "runtime": runtime, "cell_id": cell["id"],
            "mode": cell["mode"], "warmup": warmup, "scheduled_order": index + 1,
            "clock_domain": "client_monotonic_ns", "a_ns": a_ns, "b_ns": None,
            "s_ns": None, "f_ns": None, "l_ns": None, "d_ns": None, "end_ns": a_ns,
            "content_event_count": 0, "interchunk_gaps_ns": [], "input_tokens": None,
            "output_tokens": None, "streamed_usage_output_tokens": None,
            "tokenizer_output_tokens": None, "stop_reason": "not_started", "status": "unsent",
            "reason_code": reason_code, "fixed_length_valid": None, "schema_valid": None,
            "semantic_correct": None, "nontruncated": None,
            "quality_task_id": requests[index]["quality_task_id"],
        }

    def execute(index: int, a_ns: int) -> dict[str, Any]:
        spec = requests[index]
        messages = spec["messages"]
        input_tokens = input_counts[index]
        b_ns = clock()
        request = {
            "url": endpoint_url, "runtime_id": dialect, "runtime_capabilities": _CAPABILITIES,
            "model": model, "messages": messages, "maximum_output_tokens": cell["output_tokens"],
            "temperature": 0, "top_p": 1, "top_k": top_k, "seed": SEED,
            "repetition_penalty": 1,
            "timeout_seconds": cell["request_deadline_seconds"], "absolute_deadline_ns": cell_deadline_ns,
            "cancel_event": cancel_event, "max_response_bytes": 16 * 1024 * 1024,
            "use_max_completion_tokens": True,
        }
        require_server_input_count = evidence_class != "local_fixture"
        if require_server_input_count:
            request["require_exact_prompt_tokens"] = True
            request["expected_prompt_tokens"] = input_tokens
        if cell["mode"] == "fixed_output":
            request["ignore_eos"] = True
        base = {
            "schema_version": SCHEMA_VERSION, "evidence_class": evidence_class,
            "request_id": spec["request_id"], "block_id": block["block_id"],
            "pair_id": block["pair_id"], "runtime": runtime, "cell_id": cell["id"],
            "mode": cell["mode"], "warmup": warmup, "scheduled_order": index + 1,
            "clock_domain": "client_monotonic_ns", "a_ns": a_ns, "b_ns": b_ns,
            "input_tokens": input_tokens, "quality_task_id": spec["quality_task_id"],
        }
        lifecycle(index, "dispatched", b_ns)
        try:
            result = stream(request)
            if require_server_input_count:
                server_input_tokens = result.get("input_tokens")
                if (
                    isinstance(server_input_tokens, bool)
                    or not isinstance(server_input_tokens, int)
                    or server_input_tokens != input_tokens
                ):
                    raise StreamingError(
                        "streamed usage prompt token count does not match the pinned tokenizer count",
                        actual_send_ns=result.get("actual_send_ns"),
                        first_content_ns=result.get("first_content_ns"),
                        last_content_ns=result.get("last_content_ns"),
                        content_event_count=result.get("content_event_count", 0),
                        inter_chunk_gaps_ns=tuple(result.get("inter_chunk_gaps_ns", ())),
                    )
            output_tokens = result["output_tokens"]
            stop_reason = result["stop_reason"]
            invalid_stop = stop_reason not in {"length", "stop", "eos"}
            try:
                tokenizer_tokens = output_token_counter(str(result["text"]))
                counter_failed = False
            except Exception:
                tokenizer_tokens = None
                counter_failed = True
            try:
                quality = (
                    evaluate_quality(str(result["text"]), str(spec["gold_json"]), stop_reason)
                    if cell["mode"] == "natural_stop" and not invalid_stop else
                    {"schema_valid": None, "semantic_correct": None, "nontruncated": None}
                )
                quality_failed = False
            except (TypeError, ValueError):
                quality = {"schema_valid": None, "semantic_correct": None, "nontruncated": None}
                quality_failed = True
            mismatch = tokenizer_tokens is not None and tokenizer_tokens != output_tokens
            if mismatch or counter_failed:
                cancel_event.set()
            failed_reason = (
                "invalid_stop_reason" if invalid_stop else "token_mismatch" if mismatch
                else "malformed_sse" if counter_failed else "quality_invalid" if quality_failed else "none"
            )
            record = {
                **base, "s_ns": result["actual_send_ns"], "f_ns": result["first_content_ns"],
                "l_ns": result["last_content_ns"], "d_ns": result["terminal_ns"],
                "end_ns": max(clock(), result["terminal_ns"]),
                "content_event_count": result["content_event_count"],
                "interchunk_gaps_ns": list(result["inter_chunk_gaps_ns"]),
                "output_tokens": output_tokens, "streamed_usage_output_tokens": output_tokens,
                "tokenizer_output_tokens": tokenizer_tokens,
                "stop_reason": "error" if invalid_stop else stop_reason,
                "status": "sse_failure" if failed_reason != "none" else "success",
                "reason_code": failed_reason,
                "fixed_length_valid": (
                    output_tokens == cell["output_tokens"] and stop_reason == "length"
                    if cell["mode"] == "fixed_output" and failed_reason == "none" else None
                ),
                **quality,
            }
        except StreamingError as exc:
            if require_server_input_count and (
                "prompt token" in str(exc).lower() or "streamed usage" in str(exc).lower()
            ):
                cancel_event.set()
            status, reason, stop = _failure(exc, cancel_event)
            s_ns = exc.actual_send_ns
            first_ns = exc.first_content_ns
            last_ns = exc.last_content_ns
            record = {
                **base, "s_ns": s_ns, "f_ns": first_ns, "l_ns": last_ns, "d_ns": None,
                "end_ns": max(clock(), last_ns or s_ns or b_ns),
                "content_event_count": exc.content_event_count,
                "interchunk_gaps_ns": list(exc.inter_chunk_gaps_ns), "output_tokens": None,
                "streamed_usage_output_tokens": None, "tokenizer_output_tokens": None,
                "stop_reason": stop, "status": status, "reason_code": reason,
                "fixed_length_valid": None, "schema_valid": None, "semantic_correct": None,
                "nontruncated": None,
            }
        return _validated_raw(record)

    def worker() -> None:
        nonlocal next_index
        while True:
            with queue_lock:
                if next_index >= count:
                    return
                index = next_index
                next_index += 1
            a_ns = clock()
            lifecycle(index, "scheduled", a_ns)
            if cancel_event.is_set() or a_ns >= cell_deadline_ns:
                retain(index, unsent(index, a_ns, cancel_event.reason_code() or "not_dispatched"))
                continue
            retain(index, execute(index, a_ns))

    with ThreadPoolExecutor(max_workers=int(cell["concurrency"]), thread_name_prefix="episode1-cell") as pool:
        futures = [pool.submit(worker) for _ in range(int(cell["concurrency"]))]
        for future in futures:
            future.result()
    # An externally owned cancellation event is a teardown signal.  Completing
    # a healthy cell must not set it and accidentally cancel the next cell.
    cancel_event.set()
    complete = [record for record in records if record is not None]
    if len(complete) != count:
        raise RuntimeError("runner lost a scheduled attempt")
    measured_start_ns = min(record["a_ns"] for record in complete)
    cell_end_ns = max(record["end_ns"] for record in complete)
    if warmup:
        return complete, {
            "scheduled": count,
            "failed": sum(record["status"] != "success" for record in complete),
            "window_start_ns": measured_start_ns,
            "window_end_ns": cell_end_ns,
        }
    return complete, summarize_cell(complete, measured_start_ns, cell_end_ns, cell)
