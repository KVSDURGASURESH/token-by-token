#!/usr/bin/env python3
"""Summarize unit-bearing ``nvidia-smi --format=csv`` telemetry."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO


FIELDS = {
    "utilization_gpu_percent": "utilization.gpu [%]",
    "memory_used_mib": "memory.used [MiB]",
    "power_draw_w": "power.draw [W]",
    "temperature_c": "temperature.gpu",
}


def _number(value: str) -> float:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value)
    if not match:
        raise ValueError(f"telemetry value is not numeric: {value!r}")
    result = float(match.group(0))
    if not math.isfinite(result):
        raise ValueError("telemetry value must be finite")
    return result


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * quantile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _timestamp(value: str) -> datetime:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y/%m/%d %H:%M:%S.%f")
        except ValueError:
            parsed = datetime.strptime(text, "%Y/%m/%d %H:%M:%S")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_bound(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def summarize(
    stream: TextIO,
    *,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
    source: str = "nvidia-smi csv",
) -> dict[str, object]:
    reader = csv.DictReader(stream, skipinitialspace=True)
    all_rows = list(reader)
    if start_utc is not None:
        start_utc = _as_utc(start_utc)
    if end_utc is not None:
        end_utc = _as_utc(end_utc)
    timestamped = sorted(((_timestamp(row["timestamp"]), row) for row in all_rows), key=lambda item: item[0])
    rows = [
        (timestamp, row)
        for timestamp, row in timestamped
        if (start_utc is None or timestamp >= start_utc)
        and (end_utc is None or timestamp <= end_utc)
    ]
    if not rows:
        raise ValueError("telemetry has no samples")
    identities = {
        (
            row.get("uuid", "").strip(),
            row.get("index", "").strip(),
            row.get("name", "").strip(),
        )
        for _, row in rows
    }
    if len(identities) != 1:
        raise ValueError("mixed GPU devices are not allowed in one telemetry summary")
    gpu_uuid, gpu_index, gpu_name = next(iter(identities))
    if not gpu_uuid and (not gpu_index or not gpu_name):
        raise ValueError("stable GPU identity requires uuid or index plus name")
    timestamps = [timestamp for timestamp, _ in rows]
    intervals = [
        (later - earlier).total_seconds()
        for earlier, later in zip(timestamps, timestamps[1:])
    ]
    result: dict[str, object] = {
        "schema_version": 1,
        "sample_count": len(rows),
        "excluded_row_count": len(all_rows) - len(rows),
        "gpu": gpu_name,
        "device": {"uuid": gpu_uuid or None, "index": gpu_index, "name": gpu_name},
        "source": source,
        "requested_window": {
            "start_utc": start_utc.isoformat() if start_utc else None,
            "end_utc": end_utc.isoformat() if end_utc else None,
        },
        "first_timestamp": timestamps[0].isoformat(),
        "last_timestamp": timestamps[-1].isoformat(),
        "sampling_cadence_seconds": (
            _percentile(intervals, 0.50) if intervals else None
        ),
        "percentile_method": "linear_rank_n_minus_1",
    }
    for output_name, input_name in FIELDS.items():
        values = [_number(row[input_name]) for _, row in rows]
        result[output_name] = {
            "minimum": min(values),
            "mean": sum(values) / len(values),
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "maximum": max(values),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start-utc", type=_utc_bound)
    parser.add_argument("--end-utc", type=_utc_bound)
    parser.add_argument("--source", default="nvidia-smi csv")
    args = parser.parse_args()
    with args.input.open(encoding="utf-8", newline="") as stream:
        result = summarize(
            stream,
            start_utc=args.start_utc,
            end_utc=args.end_utc,
            source=args.source,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
