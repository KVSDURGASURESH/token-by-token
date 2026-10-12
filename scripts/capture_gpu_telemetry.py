#!/usr/bin/env python3
"""Capture sanitized NVIDIA GPU telemetry as unit-bearing CSV."""

from __future__ import annotations

import argparse
import csv
import subprocess
import time
from pathlib import Path


FIELDS = (
    "timestamp", "index", "name", "utilization.gpu", "memory.used",
    "memory.total", "power.draw", "temperature.gpu",
)
HEADERS = (
    "timestamp", "index", "name", "utilization.gpu [%]", "memory.used [MiB]",
    "memory.total [MiB]", "power.draw [W]", "temperature.gpu",
)


def sample() -> list[list[str]]:
    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=" + ",".join(FIELDS), "--format=csv,noheader,nounits"],
        check=True, capture_output=True, text=True, timeout=15,
    )
    return list(csv.reader(line for line in completed.stdout.splitlines() if line.strip()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--samples", type=int, default=0, help="zero means until interrupted")
    args = parser.parse_args()
    if args.interval_seconds <= 0 or args.samples < 0:
        raise SystemExit("interval must be positive and samples nonnegative")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        count = 0
        try:
            while args.samples == 0 or count < args.samples:
                for row in sample():
                    if len(row) != len(FIELDS):
                        raise RuntimeError("unexpected nvidia-smi column count")
                    writer.writerow([value.strip() for value in row])
                handle.flush()
                count += 1
                if args.samples == 0 or count < args.samples:
                    time.sleep(args.interval_seconds)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
