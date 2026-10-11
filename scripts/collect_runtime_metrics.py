#!/usr/bin/env python3
"""Periodically capture selected runtime-native Prometheus metrics as JSONL."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpod_benchmark.runtime_metrics import snapshot_from_prometheus  # noqa: E402


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
STOP = False


def _wall_time() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def collect_once(
    runtime: str,
    url: str,
    *,
    opener=urllib.request.urlopen,
    monotonic_ns=time.monotonic_ns,
    wall_time=_wall_time,
) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("runtime metrics URL must use HTTP loopback")
    request = urllib.request.Request(url, headers={"Accept": "text/plain"})
    with opener(request, timeout=2) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("runtime metrics response exceeds byte cap")
    snapshot = snapshot_from_prometheus(
        runtime, body.decode("utf-8", "strict"), monotonic_ns()
    )
    snapshot["observed_at_utc"] = wall_time()
    return snapshot


def _stop(_signum, _frame) -> None:
    global STOP
    STOP = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("vllm", "sglang"), required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000/metrics")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval_seconds < 0.2:
        parser.error("--interval-seconds must be at least 0.2")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8", buffering=1) as handle:
        while not STOP:
            started = time.monotonic()
            try:
                handle.write(json.dumps(collect_once(args.runtime, args.url), sort_keys=True) + "\n")
            except (OSError, UnicodeError, ValueError) as exc:
                print(f"runtime metrics scrape skipped: {type(exc).__name__}", file=sys.stderr)
            delay = args.interval_seconds - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
