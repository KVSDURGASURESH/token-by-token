#!/usr/bin/env python3
"""Summarize one runtime collector JSONL file without contacting a server."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from runpod_benchmark.runtime_metrics import METRIC_MAPS  # noqa: E402


def distribution(values: list[float]) -> dict[str, float | int]:
    """Linear interpolation over observed samples; no request-level inference."""
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        rank = (len(ordered) - 1) * fraction
        lower = math.floor(rank)
        upper = math.ceil(rank)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)

    return {
        "sample_count": len(values),
        "min": ordered[0],
        "mean": statistics.mean(values),
        "p50": percentile(0.5),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def read_samples(path: Path, runtime: str) -> list[dict]:
    if runtime not in METRIC_MAPS:
        raise ValueError("unsupported runtime")
    allowed = set(METRIC_MAPS[runtime].values())
    samples = []
    previous_ns = -1
    previous_wall = None
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                sample = json.loads(line)
                if not isinstance(sample, dict) or sample.get("runtime") != runtime:
                    raise ValueError("runtime does not match the requested runtime")
                timestamp = sample.get("monotonic_ns")
                if type(timestamp) is not int or timestamp <= previous_ns:
                    raise ValueError("monotonic_ns must be nonnegative and strictly increasing")
                wall_text = sample.get("observed_at_utc")
                if not isinstance(wall_text, str):
                    raise ValueError("observed_at_utc is required")
                wall = datetime.fromisoformat(wall_text.replace("Z", "+00:00"))
                if wall.tzinfo is None or wall.utcoffset().total_seconds() != 0:
                    raise ValueError("observed_at_utc must have a UTC timezone")
                if previous_wall is not None and wall < previous_wall:
                    raise ValueError("UTC timestamps moved backwards; inspect the capture clock")
                metrics = sample.get("metrics")
                if not isinstance(metrics, dict) or not set(metrics).issubset(allowed):
                    raise ValueError("metrics must contain only this runtime's mapped names")
                for value in metrics.values():
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise ValueError("metric values must be finite nonnegative numbers")
            except (ValueError, TypeError, OverflowError):
                # Do not echo raw collector input: it may contain private labels.
                raise ValueError(f"invalid collector record at line {line_number}") from None
            previous_ns = timestamp
            previous_wall = wall
            samples.append(sample)
    if not samples:
        raise ValueError("collector file has no samples")
    return samples


def _counter_delta(samples: list[dict], name: str) -> float | None:
    values = [row["metrics"][name] for row in samples if name in row["metrics"]]
    if len(values) < 2 or any(b < a for a, b in zip(values, values[1:])):
        return None
    return values[-1] - values[0]


def _ratio(samples: list[dict], numerator: str, denominator: str) -> float | None:
    if _counter_delta(samples, numerator) is None or _counter_delta(samples, denominator) is None:
        return None
    paired = [row for row in samples if numerator in row["metrics"] and denominator in row["metrics"]]
    top = _counter_delta(paired, numerator)
    bottom = _counter_delta(paired, denominator)
    return top / bottom if top is not None and bottom is not None and bottom > 0 else None


def summarize(samples: list[dict], runtime: str, start_ns: int | None = None,
              end_ns: int | None = None) -> dict:
    if (start_ns is None) != (end_ns is None):
        raise ValueError("supply both window bounds or neither")
    if start_ns is not None and (start_ns < 0 or end_ns < start_ns):
        raise ValueError("invalid monotonic window bounds")
    selected = [row for row in samples if start_ns is None or start_ns <= row["monotonic_ns"] <= end_ns]
    if not selected:
        raise ValueError("no collector samples in the selected window")
    names = sorted({name for row in selected for name in row["metrics"]})
    metric_samples = {
        name: distribution([row["metrics"][name] for row in selected if name in row["metrics"]])
        for name in names
    }
    intervals = [(b["monotonic_ns"] - a["monotonic_ns"]) / 1e9 for a, b in zip(selected, selected[1:])]
    reset_names = []
    for name in names:
        if name.endswith(("_total", "_sum", "_count")):
            values = [row["metrics"][name] for row in selected if name in row["metrics"]]
            if any(b < a for a, b in zip(values, values[1:])):
                reset_names.append(name)
    return {
        "schema_version": 1,
        "classification": "runtime_native_telemetry_summary",
        "runtime": runtime,
        "available": bool(names),
        "sample_count": len(selected),
        "first_observed_at_utc": selected[0]["observed_at_utc"],
        "last_observed_at_utc": selected[-1]["observed_at_utc"],
        "start_monotonic_ns": selected[0]["monotonic_ns"],
        "end_monotonic_ns": selected[-1]["monotonic_ns"],
        "window_seconds": (selected[-1]["monotonic_ns"] - selected[0]["monotonic_ns"]) / 1e9,
        "observed_sample_interval_seconds": distribution(intervals) if intervals else None,
        "metric_samples": metric_samples,
        "native_window": {
            "prefill_seconds_per_request": _ratio(selected, "prefill_seconds_sum", "prefill_seconds_count"),
            "decode_seconds_per_request": _ratio(selected, "decode_seconds_sum", "decode_seconds_count"),
            "prefix_cache_hit_rate": _ratio(selected, "prefix_cache_hits_total", "prefix_cache_queries_total"),
            "prompt_tokens": _counter_delta(selected, "prompt_tokens_total"),
            "generation_tokens": _counter_delta(selected, "generation_tokens_total"),
        },
        "counter_resets_detected": reset_names,
        "interpretation": [
            "Metric percentiles describe scrape samples, not request-latency percentiles.",
            "Means are unweighted across samples; observed cadence may differ from configured cadence.",
            "Phase duration is delta(histogram sum)/delta(histogram count) over paired samples.",
            "Unavailable, zero-count, or reset-affected counter results remain null.",
            "A whole-file summary is not a per-cell or per-repetition summary.",
            "Window bounds must originate on the collector's host; monotonic clocks cannot be joined across hosts.",
            "Native KV denominators are not established as equivalent across runtimes.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--runtime", required=True, choices=tuple(METRIC_MAPS))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start-monotonic-ns", type=int)
    parser.add_argument("--end-monotonic-ns", type=int)
    args = parser.parse_args()
    try:
        result = summarize(read_samples(args.input, args.runtime), args.runtime,
                           args.start_monotonic_ns, args.end_monotonic_ns)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"runtime summary failed: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
