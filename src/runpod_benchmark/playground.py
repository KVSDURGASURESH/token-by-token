"""Local-only Episode 1 quick-test configuration and request runner.

This module deliberately has no provider lifecycle, promotion, or publication hooks.
Its results are ad-hoc diagnostics and cannot become Episode 1 benchmark evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .streaming import REQUIRED_STREAM_CAPABILITIES, StreamingError, stream_chat


SCHEMA_VERSION = "episode1.quick-test.v1"
RESULT_SCHEMA_VERSION = "episode1.quick-test-result.v1"
MAX_PROMPT_CHARS = 32_768
MAX_CONFIG_BYTES = 128 * 1024
MAX_REPETITIONS = 20
MAX_CONCURRENCY = 4
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_CONFIG_KEYS = {
    "schema_version", "mode", "prompt", "lanes", "sampling",
    "request_timeout_seconds", "repetitions", "concurrency",
}
_PROMPT_KEYS = {"system", "user"}
_LANE_KEYS = {"id", "profile_id", "label"}
_SAMPLING_KEYS = {"maximum_output_tokens", "temperature", "top_p", "top_k", "seed", "stop"}
_PROFILE_KEYS = {
    "id", "label", "url", "runtime_id", "model", "api_key_env",
    "supported_optional_fields", "context_length",
}


class PlaygroundValidationError(ValueError):
    pass


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PlaygroundValidationError(f"{name} must be an object")
    return dict(value)


def _closed(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise PlaygroundValidationError(f"unsupported {name} field: {sorted(unknown)[0]}")


def validate_profiles(raw: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise PlaygroundValidationError("at least one endpoint profile is required")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        profile = _object(item, "endpoint profile")
        _closed(profile, _PROFILE_KEYS, "endpoint profile")
        identifier = profile.get("id")
        if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
            raise PlaygroundValidationError("endpoint profile id is invalid")
        if identifier in result:
            raise PlaygroundValidationError("endpoint profile ids must be unique")
        for field in ("label", "url", "runtime_id", "model"):
            if not isinstance(profile.get(field), str) or not profile[field] or len(profile[field]) > 512:
                raise PlaygroundValidationError(f"endpoint profile {field} is invalid")
        secret_name = profile.get("api_key_env")
        if secret_name is not None and (
            not isinstance(secret_name, str)
            or re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", secret_name) is None
        ):
            raise PlaygroundValidationError("api_key_env must be an environment variable name")
        optional = profile.get("supported_optional_fields", [])
        if (
            not isinstance(optional, list)
            or len(optional) != len(set(optional))
            or any(field not in {"top_k", "seed", "stop"} for field in optional)
        ):
            raise PlaygroundValidationError("supported optional fields are invalid")
        context = profile.get("context_length")
        if context is not None and (
            isinstance(context, bool) or not isinstance(context, int) or not 256 <= context <= 1_000_000
        ):
            raise PlaygroundValidationError("context_length is invalid")
        result[identifier] = {
            **profile,
            "supported_optional_fields": list(optional),
            "context_length": context,
        }
    return result


def public_profiles(profiles: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return browser-safe profile metadata without URL or credential references."""
    return [
        {
            "id": profile["id"],
            "label": profile["label"],
            "runtime_id": profile["runtime_id"],
            "model": profile["model"],
            "supported_optional_fields": profile["supported_optional_fields"],
            "context_length": profile.get("context_length"),
        }
        for profile in profiles.values()
    ]


def validate_config(raw: Mapping[str, Any], profiles: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    try:
        size = len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode())
    except (TypeError, ValueError) as exc:
        raise PlaygroundValidationError(f"configuration must be JSON-safe: {exc}") from exc
    if size > MAX_CONFIG_BYTES:
        raise PlaygroundValidationError("configuration exceeds the 128 KiB limit")
    config = _object(raw, "configuration")
    _closed(config, _CONFIG_KEYS, "configuration")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise PlaygroundValidationError(f"schema_version must be {SCHEMA_VERSION}")
    mode = config.get("mode")
    if mode not in {"single", "compare"}:
        raise PlaygroundValidationError("mode must be single or compare")
    prompt = _object(config.get("prompt"), "prompt")
    _closed(prompt, _PROMPT_KEYS, "prompt")
    system = prompt.get("system", "")
    user = prompt.get("user")
    if not isinstance(system, str) or not isinstance(user, str) or not user.strip():
        raise PlaygroundValidationError("prompt.user must be nonempty and prompt.system must be text")
    if len(system) + len(user) > MAX_PROMPT_CHARS:
        raise PlaygroundValidationError("combined prompt exceeds 32,768 characters")
    lanes_raw = config.get("lanes")
    required_lanes = 1 if mode == "single" else 2
    if not isinstance(lanes_raw, list) or len(lanes_raw) != required_lanes:
        raise PlaygroundValidationError(f"{mode} mode requires exactly {required_lanes} lane(s)")
    lanes: list[dict[str, str]] = []
    for item in lanes_raw:
        lane = _object(item, "lane")
        _closed(lane, _LANE_KEYS, "lane")
        identifier, profile_id, label = lane.get("id"), lane.get("profile_id"), lane.get("label")
        if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
            raise PlaygroundValidationError("lane id is invalid")
        if not isinstance(profile_id, str) or _ID.fullmatch(profile_id) is None:
            raise PlaygroundValidationError("lane profile_id is invalid")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise PlaygroundValidationError("lane label is invalid")
        if profiles is not None and profile_id not in profiles:
            raise PlaygroundValidationError(f"unknown endpoint profile: {profile_id}")
        lanes.append({"id": identifier, "profile_id": profile_id, "label": label.strip()})
    if len({lane["id"] for lane in lanes}) != len(lanes):
        raise PlaygroundValidationError("lane ids must be unique")
    sampling = _object(config.get("sampling"), "sampling")
    _closed(sampling, _SAMPLING_KEYS, "sampling")
    maximum = sampling.get("maximum_output_tokens")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 4096:
        raise PlaygroundValidationError("maximum_output_tokens must be between 1 and 4096")
    for field, low, high in (("temperature", 0.0, 2.0), ("top_p", 0.0, 1.0)):
        value = sampling.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise PlaygroundValidationError(f"{field} must be between {low:g} and {high:g}")
    optional = {key: sampling[key] for key in ("top_k", "seed", "stop") if key in sampling and sampling[key] is not None}
    if "top_k" in optional and (isinstance(optional["top_k"], bool) or not isinstance(optional["top_k"], int)):
        raise PlaygroundValidationError("top_k must be an integer")
    if "seed" in optional and (
        isinstance(optional["seed"], bool) or not isinstance(optional["seed"], int) or optional["seed"] < 0
    ):
        raise PlaygroundValidationError("seed must be a nonnegative integer")
    if "stop" in optional and not (
        isinstance(optional["stop"], str) and optional["stop"] and len(optional["stop"]) <= 256
    ):
        raise PlaygroundValidationError("stop must be a nonempty string of at most 256 characters")
    if profiles is not None:
        for lane in lanes:
            supported = set(profiles[lane["profile_id"]]["supported_optional_fields"])
            unsupported = set(optional) - supported
            if unsupported:
                raise PlaygroundValidationError(
                    f"profile {lane['profile_id']} does not support {sorted(unsupported)[0]}"
                )
            context = profiles[lane["profile_id"]].get("context_length")
            if context is not None and maximum >= context:
                raise PlaygroundValidationError(
                    f"maximum_output_tokens leaves no room in profile {lane['profile_id']} context"
                )
    timeout = config.get("request_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise PlaygroundValidationError("request_timeout_seconds must be between 1 and 600")
    repetitions = config.get("repetitions", 1)
    concurrency = config.get("concurrency", 1)
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= MAX_REPETITIONS:
        raise PlaygroundValidationError(f"repetitions must be between 1 and {MAX_REPETITIONS}")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= MAX_CONCURRENCY:
        raise PlaygroundValidationError(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "prompt": {"system": system, "user": user},
        "lanes": lanes,
        "sampling": {"maximum_output_tokens": maximum, "temperature": float(sampling["temperature"]), "top_p": float(sampling["top_p"]), **optional},
        "request_timeout_seconds": float(timeout),
        "repetitions": repetitions,
        "concurrency": concurrency,
    }


def sanitized_config(config: Mapping[str, Any]) -> dict[str, Any]:
    checked = validate_config(config)
    prompt = checked.pop("prompt")
    checked["prompt"] = {
        "system_characters": len(prompt["system"]),
        "user_characters": len(prompt["user"]),
        "sha256": canonical_sha256(prompt),
        "input_tokens": None,
        "input_tokens_reason": "no reviewed matching tokenizer configured",
    }
    return checked


def _attempt(
    *,
    lane: Mapping[str, str],
    repetition: int,
    config: Mapping[str, Any],
    profile: Mapping[str, Any],
    cancel_event: threading.Event,
    emit: Callable[[Mapping[str, Any]], None],
    stream: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    messages = []
    if config["prompt"]["system"]:
        messages.append({"role": "system", "content": config["prompt"]["system"]})
    messages.append({"role": "user", "content": config["prompt"]["user"]})
    sampling = config["sampling"]
    request: dict[str, Any] = {
        "url": profile["url"],
        "runtime_id": profile["runtime_id"],
        "runtime_capabilities": {name: True for name in REQUIRED_STREAM_CAPABILITIES},
        "model": profile["model"],
        "messages": messages,
        "maximum_output_tokens": sampling["maximum_output_tokens"],
        "temperature": sampling["temperature"],
        "top_p": sampling["top_p"],
        "timeout_seconds": config["request_timeout_seconds"],
        "cancel_event": cancel_event,
        "content_callback": lambda text, at_ns: emit({
            "type": "content", "lane_id": lane["id"], "repetition": repetition,
            "text": text, "runner_monotonic_ns": at_ns,
        }),
    }
    for field in ("top_k", "seed", "stop"):
        if field in sampling:
            request[field] = sampling[field]
    secret_name = profile.get("api_key_env")
    if secret_name:
        secret = os.environ.get(secret_name)
        if not secret:
            raise PlaygroundValidationError(f"credential environment variable {secret_name} is not set")
        request["api_key"] = secret
    emit({"type": "state", "lane_id": lane["id"], "repetition": repetition, "state": "waiting"})
    try:
        result = dict(stream(request))
        count = result.get("output_tokens")
        span = result.get("content_span_ms")
        rate = (
            (count - 1) / (span / 1000)
            if isinstance(count, int) and count >= 2 and isinstance(span, (int, float)) and span > 0
            else None
        )
        attempt = {
            "repetition": repetition,
            "status": "completed",
            "ttft_ms": result.get("ttft_ms"),
            "e2e_ms": result.get("e2e_ms"),
            "output_tokens": count,
            "generation_tokens_per_second": rate,
            "content_event_count": result.get("content_event_count"),
            "token_count_provenance": "server_streamed_usage",
            "timing_provenance": "runner_monotonic_clock",
            "stop_reason": result.get("stop_reason"),
            "response_text": result.get("text", ""),
        }
    except (StreamingError, PlaygroundValidationError) as exc:
        cancelled = cancel_event.is_set() or "cancel" in str(exc).lower()
        attempt = {
            "repetition": repetition,
            "status": "cancelled" if cancelled else "error",
            "error": "request cancelled" if cancelled else str(exc)[:1024],
            "ttft_ms": None, "e2e_ms": None, "output_tokens": None,
            "generation_tokens_per_second": None, "content_event_count": 0,
            "token_count_provenance": "unavailable",
            "timing_provenance": "runner_monotonic_clock",
            "response_text": "",
        }
    emit({"type": "attempt", "lane_id": lane["id"], **{k: v for k, v in attempt.items() if k != "response_text"}})
    return attempt


def run_config(
    raw_config: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    emit: Callable[[Mapping[str, Any]], None] = lambda _event: None,
    cancel_event: threading.Event | None = None,
    stream: Callable[[Mapping[str, Any]], Mapping[str, Any]] = stream_chat,
) -> dict[str, Any]:
    config = validate_config(raw_config, profiles)
    cancellation = cancel_event or threading.Event()
    config_digest = canonical_sha256(config)
    emit({"type": "run", "state": "preparing", "config_sha256": config_digest})
    work = [
        (lane, repetition)
        for repetition in range(1, config["repetitions"] + 1)
        for lane in config["lanes"]
    ]
    attempts: dict[str, list[dict[str, Any]]] = {lane["id"]: [] for lane in config["lanes"]}
    workers = min(len(work), max(len(config["lanes"]), config["concurrency"] * len(config["lanes"])))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0, len(work), workers):
            if cancellation.is_set():
                break
            future_map = {}
            for lane, repetition in work[offset:offset + workers]:
                if cancellation.is_set():
                    break
                future = pool.submit(
                    _attempt, lane=lane, repetition=repetition, config=config,
                    profile=profiles[lane["profile_id"]], cancel_event=cancellation,
                    emit=emit, stream=stream,
                )
                future_map[future] = lane["id"]
            for future in as_completed(future_map):
                attempts[future_map[future]].append(future.result())
    lane_results = []
    for lane in config["lanes"]:
        rows = sorted(attempts[lane["id"]], key=lambda item: item["repetition"])
        successes = [row for row in rows if row["status"] == "completed"]
        def mean(field: str) -> float | None:
            values = [float(row[field]) for row in successes if isinstance(row.get(field), (int, float))]
            return sum(values) / len(values) if values else None
        lane_results.append({
            "lane_id": lane["id"], "label": lane["label"], "profile_id": lane["profile_id"],
            "attempted": len(rows), "successful": len(successes),
            "failed": sum(row["status"] == "error" for row in rows),
            "cancelled": sum(row["status"] == "cancelled" for row in rows),
            "mean_ttft_ms": mean("ttft_ms"), "mean_e2e_ms": mean("e2e_ms"),
            "mean_generation_tokens_per_second": mean("generation_tokens_per_second"),
            "attempts": rows,
        })
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "classification": "interactive_ad_hoc_not_benchmark_evidence",
        "config_sha256": config_digest,
        "effective_config": sanitized_config(config),
        "metric_definitions": {
            "ttft_ms": "first nonempty content event minus actual runner send time",
            "e2e_ms": "terminal [DONE] event minus actual runner send time",
            "generation_tokens_per_second": "(server completion tokens - 1) / first-to-last content span; unavailable for fewer than two tokens or a nonpositive span",
        },
        "lanes": lane_results,
    }
    emit({"type": "complete", "result": without_raw_text(result)})
    return result


def without_raw_text(result: Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(result))
    for lane in value.get("lanes", []):
        for attempt in lane.get("attempts", []):
            attempt.pop("response_text", None)
    return value
