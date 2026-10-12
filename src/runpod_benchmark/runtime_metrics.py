"""Small, dependency-free parser and summarizer for runtime-native metrics."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping


METRIC_MAPS = {
    "vllm": {
        "vllm:kv_cache_usage_perc": "kv_cache_usage",
        "vllm:num_requests_running": "requests_running",
        "vllm:num_requests_waiting": "requests_waiting",
        "vllm:prompt_tokens_total": "prompt_tokens_total",
        "vllm:generation_tokens_total": "generation_tokens_total",
        "vllm:request_prefill_time_seconds_sum": "prefill_seconds_sum",
        "vllm:request_prefill_time_seconds_count": "prefill_seconds_count",
        "vllm:request_decode_time_seconds_sum": "decode_seconds_sum",
        "vllm:request_decode_time_seconds_count": "decode_seconds_count",
        "vllm:prefix_cache_queries": "prefix_cache_queries_total",
        "vllm:prefix_cache_hits": "prefix_cache_hits_total",
    },
    "sglang": {
        "sglang:token_usage": "kv_cache_usage",
        "sglang:full_token_usage": "full_kv_cache_usage",
        "sglang:cache_hit_rate": "cache_hit_rate",
        "sglang:num_running_reqs": "requests_running",
        "sglang:num_queue_reqs": "requests_waiting",
        "sglang:prompt_tokens_total": "prompt_tokens_total",
        "sglang:generation_tokens_total": "generation_tokens_total",
        "sglang:request_prefill_time_seconds_sum": "prefill_seconds_sum",
        "sglang:request_prefill_time_seconds_count": "prefill_seconds_count",
        "sglang:request_decode_time_seconds_sum": "decode_seconds_sum",
        "sglang:request_decode_time_seconds_count": "decode_seconds_count",
    },
}


def snapshot_from_prometheus(runtime: str, text: str, monotonic_ns: int) -> dict[str, object]:
    """Map a Prometheus exposition snapshot to stable benchmark metric names."""

    if runtime not in METRIC_MAPS:
        raise ValueError(f"unsupported runtime: {runtime}")
    mapping = METRIC_MAPS[runtime]
    metrics: dict[str, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            identity, raw_value = line.rsplit(None, 1)
            source_name = identity.split("{", 1)[0]
            target_name = mapping.get(source_name)
            if target_name is None:
                continue
            value = float(raw_value)
        except (ValueError, IndexError):
            continue
        if math.isfinite(value):
            if target_name in metrics:
                raise ValueError(
                    f"multiple Prometheus series map to {target_name}; labels must be filtered explicitly"
                )
            metrics[target_name] = value
    return {"runtime": runtime, "monotonic_ns": int(monotonic_ns), "metrics": metrics}


def _series(samples: Iterable[Mapping[str, object]], name: str) -> list[float]:
    values = []
    for sample in samples:
        metrics = sample.get("metrics")
        if isinstance(metrics, Mapping) and name in metrics:
            value = float(metrics[name])
            if math.isfinite(value):
                values.append(value)
    return values


def _delta(samples: list[Mapping[str, object]], name: str) -> float | None:
    values = _series(samples, name)
    if len(values) < 2 or values[-1] < values[0]:
        return None
    return values[-1] - values[0]


def _ratio_delta(samples: list[Mapping[str, object]], numerator: str, denominator: str) -> float | None:
    top = _delta(samples, numerator)
    bottom = _delta(samples, denominator)
    if top is None or bottom is None or bottom <= 0:
        return None
    return top / bottom


def _duration_per_request(samples: list[Mapping[str, object]], phase: str) -> float | None:
    duration = _delta(samples, f"{phase}_seconds_sum")
    count = _delta(samples, f"{phase}_seconds_count")
    if duration is None or count is None or count <= 0:
        return None
    return duration / count


def summarize_window(
    snapshots: Iterable[Mapping[str, object]], start_monotonic_ns: int, end_monotonic_ns: int
) -> dict[str, object]:
    """Summarize native runtime metrics observed inside one benchmark cell."""

    selected = sorted(
        (
            sample
            for sample in snapshots
            if start_monotonic_ns <= int(sample.get("monotonic_ns", -1)) <= end_monotonic_ns
        ),
        key=lambda sample: int(sample["monotonic_ns"]),
    )
    if not selected:
        return {
            "available": False,
            "unavailable_reason": "no runtime metric samples in cell window",
            "sample_count": 0,
        }
    kv = _series(selected, "kv_cache_usage")
    full_kv = _series(selected, "full_kv_cache_usage")
    running = _series(selected, "requests_running")
    waiting = _series(selected, "requests_waiting")
    cache_rate = _series(selected, "cache_hit_rate")
    prefix_rate = _ratio_delta(
        selected, "prefix_cache_hits_total", "prefix_cache_queries_total"
    )
    if prefix_rate is None and cache_rate:
        prefix_rate = statistics.median(cache_rate)
    window_seconds = (
        int(selected[-1]["monotonic_ns"]) - int(selected[0]["monotonic_ns"])
    ) / 1_000_000_000
    prompt_tokens = _delta(selected, "prompt_tokens_total")
    generation_tokens = _delta(selected, "generation_tokens_total")
    return {
        "available": True,
        "unavailable_reason": None,
        "sample_count": len(selected),
        "window_seconds": window_seconds,
        "kv_cache_usage_median": statistics.median(kv) if kv else None,
        "kv_cache_usage_peak": max(kv) if kv else None,
        "full_kv_cache_usage_peak": max(full_kv) if full_kv else None,
        "requests_running_peak": max(running) if running else None,
        "requests_waiting_peak": max(waiting) if waiting else None,
        "prompt_tokens": prompt_tokens,
        "generation_tokens": generation_tokens,
        "prompt_tokens_per_second": (
            prompt_tokens / window_seconds
            if prompt_tokens is not None and window_seconds > 0
            else None
        ),
        "generation_tokens_per_second": (
            generation_tokens / window_seconds
            if generation_tokens is not None and window_seconds > 0
            else None
        ),
        "prefill_seconds_per_request": _duration_per_request(selected, "prefill"),
        "decode_seconds_per_request": _duration_per_request(selected, "decode"),
        "prefix_cache_hit_rate": prefix_rate,
    }
