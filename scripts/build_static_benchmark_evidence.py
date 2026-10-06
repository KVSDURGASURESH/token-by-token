#!/usr/bin/env python3
"""Build the closed, deterministic public benchmark evidence document."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from collections import defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


SCHEMA_VERSION = "public-inference-evidence.v1"
PUBLIC_ENGINES = ("vLLM", "SGLang")
PUBLIC_LEVELS = (12, 16, 24)
PROVENANCE = "Aggregated from aligned client, engine, and GPU measurements; static publication bundle."
UNAVAILABLE_REASON = "Not available with a comparable public definition."

METRICS: tuple[dict[str, str], ...] = (
    {"id": "output_tps", "label": "Output throughput", "unit": "tok/s", "direction": "higher", "explanation": "Successful output tokens per measured second."},
    {"id": "ttft_p50_ms", "label": "TTFT p50", "unit": "ms", "direction": "lower", "explanation": "Median client-visible time to first token."},
    {"id": "ttft_p95_ms", "label": "TTFT p95", "unit": "ms", "direction": "lower", "explanation": "95th-percentile client-visible time to first token."},
    {"id": "tpot_p50_ms", "label": "TPOT p50", "unit": "ms/token", "direction": "lower", "explanation": "Median time per output token after the first token."},
    {"id": "decode_p10_tps", "label": "Decode p10", "unit": "tok/s", "direction": "higher", "explanation": "Ten-percentile per-request decode speed; 90% of valid requests are at least this fast."},
    {"id": "error_rate_pct", "label": "Error rate", "unit": "%", "direction": "lower", "explanation": "Share of measured requests that did not satisfy the validity contract."},
    {"id": "running_requests_mean", "label": "Running requests", "unit": "requests", "direction": "contextual", "explanation": "Mean runtime-native running-request gauge in the measured window."},
    {"id": "waiting_requests_mean", "label": "Waiting requests", "unit": "requests", "direction": "contextual", "explanation": "Mean runtime-native waiting-request gauge in the measured window."},
    {"id": "cache_context", "label": "Cache context", "unit": "%", "direction": "contextual", "explanation": "Available cache context retained without cross-engine normalization."},
    {"id": "gpu_utilization_pct", "label": "GPU utilization", "unit": "%", "direction": "contextual", "explanation": "Mean sampled device utilization in the measured window."},
    {"id": "gpu_memory_gib", "label": "GPU memory", "unit": "GiB", "direction": "contextual", "explanation": "Mean sampled device memory use in the measured window."},
    {"id": "gpu_power_w", "label": "GPU power", "unit": "W", "direction": "contextual", "explanation": "Mean sampled board power in the measured window."},
)
METRIC_BY_ID = {metric["id"]: metric for metric in METRICS}
PUBLIC_SERIES = {
    ("client", "Request completion rate", "req/s"),
    ("engine", "Running requests", "requests"),
    ("engine", "Waiting requests", "requests"),
    ("gpu", "GPU utilization", "%"),
    ("gpu", "GPU power", "W"),
}
PRIVATE_SERIES_METRICS = {
    "agentbench_requests_total",
    "agentbench_gpu_utilization_percent",
    "agentbench_gpu_power_watts",
    "vllm_num_requests_running",
    "vllm_num_requests_waiting",
    "sglang_num_running_reqs",
    "sglang_num_queue_reqs",
}


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _count(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be a nonnegative integer" if minimum == 0 else f"{label} is invalid")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if result < 0:
        raise ValueError(f"{label} must be nonnegative")
    return result


def _reading(metric_id: str, value: object, *, threshold: float, level_valid: bool) -> dict[str, object]:
    unit = METRIC_BY_ID[metric_id]["unit"]
    if value is None:
        return {
            "available": False,
            "value": None,
            "unit": unit,
            "reason": UNAVAILABLE_REASON,
            "evidence_state": "unavailable",
        }
    measured = _number(value, metric_id)
    if not level_valid:
        evidence_state = "invalid_level"
    elif metric_id == "decode_p10_tps":
        evidence_state = "threshold_met" if measured >= threshold else "threshold_missed"
    else:
        evidence_state = "measured"
    return {
        "available": True,
        "value": measured,
        "unit": unit,
        "reason": None,
        "evidence_state": evidence_state,
    }


def _public_point(raw: object, *, threshold: float, seen_loads: set[int]) -> dict[str, object]:
    point = _mapping(raw, "point")
    users = _count(point.get("users"), "load", minimum=1)
    if users not in PUBLIC_LEVELS:
        raise ValueError("load is outside the public study")
    if users in seen_loads:
        raise ValueError("duplicate engine/load pair")
    seen_loads.add(users)
    if point.get("percentile_origin") != "direct":
        raise ValueError("percentile must come from a direct measured distribution")
    total = _count(point.get("total_requests"), "total_requests")
    valid = _count(point.get("valid_requests"), "valid_requests")
    if valid > total:
        raise ValueError("valid_requests cannot exceed total_requests")
    level_valid = point.get("level_valid")
    if not isinstance(level_valid, bool):
        raise ValueError("level_valid must be boolean")
    if not level_valid:
        raise ValueError("invalid level cannot be published")
    metrics = _mapping(point.get("metrics"), "metrics")
    missing = set(METRIC_BY_ID).difference(metrics)
    if missing:
        raise ValueError("metrics are incomplete")
    error_rate = _number(metrics.get("error_rate_pct"), "error rate")
    if error_rate > 1 and level_valid:
        raise ValueError("error rate above 1% cannot be presented as a valid level")
    readings = {
        metric_id: _reading(metric_id, metrics.get(metric_id), threshold=threshold, level_valid=level_valid)
        for metric_id in METRIC_BY_ID
    }
    return {
        "users": users,
        "active_sessions": _count(point.get("active_sessions"), "active_sessions"),
        "total_requests": total,
        "valid_requests": valid,
        "level_valid": level_valid,
        "readings": readings,
    }


def _public_series(raw: object) -> dict[str, object]:
    series = _mapping(raw, "series")
    lane = _text(series.get("lane"), "series.lane")
    metric = _text(series.get("metric"), "series.metric")
    unit = _text(series.get("unit"), "series.unit")
    if (lane, metric, unit) not in PUBLIC_SERIES:
        raise ValueError("series definition is outside the public allowlist")
    engine = _text(series.get("engine"), "series.engine")
    if engine not in PUBLIC_ENGINES:
        raise ValueError("series engine is outside the public allowlist")
    users = _count(series.get("users"), "series.users", minimum=1)
    if users not in PUBLIC_LEVELS:
        raise ValueError("series load is outside the public study")
    samples: list[list[float | int]] = []
    previous_offset = -1
    for raw_sample in _sequence(series.get("samples"), "series.samples"):
        sample = _sequence(raw_sample, "series.sample")
        if len(sample) != 2:
            raise ValueError("series sample must contain offset and value")
        offset = _count(sample[0], "series offset")
        value = _number(sample[1], "series value")
        if offset > 300 or offset <= previous_offset:
            raise ValueError("series offsets must be ordered within the measured window")
        previous_offset = offset
        samples.append([offset, value])
    if len(samples) < 2:
        raise ValueError("series requires at least two samples")
    return {
        "lane": lane,
        "metric": metric,
        "engine": engine,
        "users": users,
        "unit": unit,
        "samples": samples,
    }
def build_public_document(source: Mapping[str, object]) -> dict[str, object]:
    """Select public facts from a private source using a positive allowlist."""

    root = _mapping(source, "source")
    study = _mapping(root.get("study"), "study")
    methodology = _mapping(root.get("methodology"), "methodology")
    threshold = _number(methodology.get("decode_threshold_tps"), "decode_threshold_tps")
    source_arms = _sequence(root.get("source_arms"), "source_arms")
    selected: dict[str, Mapping[str, Any]] = {}
    for raw_arm in source_arms:
        arm = _mapping(raw_arm, "arm")
        if arm.get("publishable") is not True:
            continue
        engine = arm.get("engine")
        if engine not in PUBLIC_ENGINES:
            raise ValueError("engine is outside the public allowlist")
        if engine in selected:
            raise ValueError("duplicate public engine")
        selected[str(engine)] = arm
    if set(selected) != set(PUBLIC_ENGINES):
        raise ValueError("both public engines are required")

    arms: list[dict[str, object]] = []
    for engine in PUBLIC_ENGINES:
        arm = selected[engine]
        seen_loads: set[int] = set()
        points = [
            _public_point(point, threshold=threshold, seen_loads=seen_loads)
            for point in _sequence(arm.get("points"), f"{engine} points")
        ]
        points.sort(key=lambda point: int(point["users"]))
        if tuple(int(point["users"]) for point in points) != PUBLIC_LEVELS:
            raise ValueError("public arm must contain exactly the approved loads")
        arms.append(
            {
                "engine": engine,
                "marker": _text(arm.get("marker"), "marker"),
                "line_style": _text(arm.get("line_style"), "line_style"),
                "points": points,
            }
        )

    limitations = [_text(item, "limitation") for item in _sequence(root.get("limitations"), "limitations")]
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "study": {
            "title": _text(study.get("title"), "study.title"),
            "model_family": _text(study.get("model_family"), "study.model_family"),
            "precision": _text(study.get("precision"), "study.precision"),
            "hardware": _text(study.get("hardware"), "study.hardware"),
            "hardware_count": _count(study.get("hardware_count"), "study.hardware_count", minimum=1),
            "evidence_state": "recorded_deployment_comparison",
            "provenance": PROVENANCE,
        },
        "methodology": {
            "warmup_seconds": _count(methodology.get("warmup_seconds"), "warmup_seconds"),
            "measurement_seconds": _count(methodology.get("measurement_seconds"), "measurement_seconds", minimum=1),
            "sessions_per_user": _count(methodology.get("sessions_per_user"), "sessions_per_user", minimum=1),
            "decode_threshold_tps": threshold,
            "ttft_gated": False,
            "capacity_state": "not_established",
        },
        "metric_definitions": [dict(metric) for metric in METRICS],
        "levels": list(PUBLIC_LEVELS),
        "arms": arms,
        "synchronized_series": [
            _public_series(series)
            for series in _sequence(root.get("synchronized_series", []), "synchronized_series")
        ],
        "limitations": limitations,
    }
    return document


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError as exc:
        raise ValueError("private aggregate table is unreadable") from exc


def _rows_by_level(path: Path) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    for row in _read_csv(path):
        try:
            level = int(row["level"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("private aggregate table has an invalid level") from exc
        rows[level] = row
    return rows


def _float_field(row: Mapping[str, str], field: str) -> float:
    try:
        return _number(float(row[field]), field)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("private aggregate table is incomplete") from exc


def _int_field(row: Mapping[str, str], field: str) -> int:
    try:
        value = int(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("private aggregate table is incomplete") from exc
    return _count(value, field)


def _downsample(samples: list[list[float | int]], maximum: int = 61) -> list[list[float | int]]:
    if len(samples) <= maximum:
        return samples
    indices = {round(index * (len(samples) - 1) / (maximum - 1)) for index in range(maximum)}
    return [samples[index] for index in sorted(indices)]


def _telemetry_rows(path: Path) -> list[tuple[str, float, float, Mapping[str, object]]]:
    rows: list[tuple[str, float, float, Mapping[str, object]]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("metric") not in PRIVATE_SERIES_METRICS or not row.get("value"):
                    continue
                labels = _mapping(json.loads(row["labels"]), "telemetry labels")
                rows.append(
                    (
                        row["metric"],
                        _number(float(row["timestamp_ms"]), "telemetry timestamp") / 1000,
                        _number(float(row["value"]), "telemetry value"),
                        labels,
                    )
                )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("telemetry"):
            raise
        raise ValueError("private telemetry table is invalid") from exc
    return rows


def _gauge_samples(
    rows: Sequence[tuple[str, float, float, Mapping[str, object]]],
    metric_name: str,
    start: float,
    end: float,
) -> list[list[float | int]]:
    buckets: dict[int, list[float]] = defaultdict(list)
    for metric, timestamp, value, _labels in rows:
        if metric != metric_name or timestamp < start or timestamp > end:
            continue
        offset = max(0, min(300, round(timestamp - start)))
        buckets[offset].append(value)
    samples = [[offset, round(sum(values) / len(values), 6)] for offset, values in sorted(buckets.items())]
    return _downsample(samples)


def _counter_rate_samples(
    rows: Sequence[tuple[str, float, float, Mapping[str, object]]],
    level: int,
    start: float,
    end: float,
) -> list[list[float | int]]:
    identities: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for metric, timestamp, value, labels in rows:
        if metric != "agentbench_requests_total" or timestamp < start or timestamp > end:
            continue
        if str(labels.get("level", "")) != str(level):
            continue
        identity = json.dumps(labels, sort_keys=True, separators=(",", ":"))
        identities[identity].append((timestamp, value))
    buckets: dict[int, float] = defaultdict(float)
    for values in identities.values():
        previous: tuple[float, float] | None = None
        for timestamp, value in sorted(values):
            if previous is not None and timestamp > previous[0] and value >= previous[1]:
                offset = max(0, min(300, round(timestamp - start)))
                buckets[offset] += (value - previous[1]) / (timestamp - previous[0])
            previous = (timestamp, value)
    samples = [[offset, round(value, 6)] for offset, value in sorted(buckets.items())]
    return _downsample(samples)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError("private source archive is unreadable") from exc
    return digest.hexdigest()


def _assert_receipts(receipts: Sequence[Path], run_roots: Sequence[Path]) -> None:
    if not receipts:
        raise ValueError("validated private receipts are required")
    expected_hashes = {_file_sha256(root / "metrics" / "metrics.csv.gz") for root in run_roots}
    receipt_hashes: set[str] = set()
    for path in receipts:
        try:
            receipt = _mapping(json.loads(path.read_text(encoding="utf-8")), "receipt")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("private validation receipt is unreadable") from exc
        checks = receipt.get("dashboard_checks")
        window = receipt.get("window")
        archive_sha256 = receipt.get("archive_sha256")
        if (
            not isinstance(checks, Mapping)
            or set(checks) != {"client", "engine", "gpu"}
            or any(state not in {"passed", "passed_with_declared_gaps"} for state in checks.values())
        ):
            raise ValueError("private validation receipt dashboard checks failed")
        if (
            receipt.get("schema") != "private-metrics-validation.v1"
            or receipt.get("status") != "passed"
            or not isinstance(window, Mapping)
            or not isinstance(window.get("start_epoch"), (int, float))
            or not isinstance(window.get("end_epoch"), (int, float))
            or window["start_epoch"] >= window["end_epoch"]
            or not isinstance(archive_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", archive_sha256)
        ):
            raise ValueError("private validation receipt is incomplete")
        receipt_hashes.add(archive_sha256)
    if receipt_hashes != expected_hashes:
        raise ValueError("private validation receipts do not bind the supplied source archives")


def build_private_source_from_runs(
    vllm_12_run: Path,
    vllm_16_24_run: Path,
    sglang_run: Path,
    receipts: Sequence[Path],
) -> dict[str, object]:
    """Extract only approved aggregates and chart samples from private run directories."""

    _assert_receipts(receipts, (vllm_12_run, vllm_16_24_run, sglang_run))
    run_map = {
        ("vLLM", 12): vllm_12_run,
        ("vLLM", 16): vllm_16_24_run,
        ("vLLM", 24): vllm_16_24_run,
        ("SGLang", 12): sglang_run,
        ("SGLang", 16): sglang_run,
        ("SGLang", 24): sglang_run,
    }
    cached: dict[Path, tuple[dict[int, dict[str, str]], dict[int, dict[str, str]], list[tuple[str, float, float, Mapping[str, object]]]]] = {}
    for root in set(run_map.values()):
        cached[root] = (
            _rows_by_level(root / "agents_levels.csv"),
            _rows_by_level(root / "agents" / "server_levels.csv"),
            _telemetry_rows(root / "metrics" / "metrics.csv.gz"),
        )

    arms: dict[str, list[dict[str, object]]] = {engine: [] for engine in PUBLIC_ENGINES}
    synchronized: list[dict[str, object]] = []
    for engine in PUBLIC_ENGINES:
        for users in PUBLIC_LEVELS:
            root = run_map[(engine, users)]
            aggregate_rows, server_rows, telemetry = cached[root]
            aggregate = aggregate_rows[users]
            server = server_rows[users]
            start = _float_field(aggregate, "measure_start_wall")
            end = _float_field(aggregate, "measure_end_wall")
            metrics = {
                "output_tps": _float_field(aggregate, "successful_output_tokens_per_s"),
                "ttft_p50_ms": _float_field(aggregate, "ttft_visible_p50"),
                "ttft_p95_ms": _float_field(aggregate, "ttft_visible_p95"),
                "tpot_p50_ms": _float_field(aggregate, "tpot_p50"),
                "decode_p10_tps": _float_field(aggregate, "decode_tps_p10"),
                "error_rate_pct": _float_field(aggregate, "error_rate") * 100,
                "running_requests_mean": _float_field(server, "running_reqs_avg"),
                "waiting_requests_mean": _float_field(server, "queue_reqs_avg"),
                "cache_context": None,
                "gpu_utilization_pct": _float_field(server, "gpu_util_avg"),
                "gpu_memory_gib": _float_field(server, "gpu_mem_max") / (1024**3),
                "gpu_power_w": _float_field(server, "power_avg"),
            }
            arms[engine].append(
                {
                    "users": users,
                    "active_sessions": _int_field(aggregate, "active_streams"),
                    "total_requests": _int_field(aggregate, "sample_count"),
                    "valid_requests": _int_field(aggregate, "valid_sample_count"),
                    "level_valid": aggregate.get("valid") == "True",
                    "percentile_origin": "direct",
                    "metrics": metrics,
                }
            )
            engine_metrics = (
                ("Running requests", "requests", "vllm_num_requests_running" if engine == "vLLM" else "sglang_num_running_reqs"),
                ("Waiting requests", "requests", "vllm_num_requests_waiting" if engine == "vLLM" else "sglang_num_queue_reqs"),
            )
            extracted = [
                ("client", "Request completion rate", "req/s", _counter_rate_samples(telemetry, users, start, end)),
                *(('engine', label, unit, _gauge_samples(telemetry, metric, start, end)) for label, unit, metric in engine_metrics),
                ("gpu", "GPU utilization", "%", _gauge_samples(telemetry, "agentbench_gpu_utilization_percent", start, end)),
                ("gpu", "GPU power", "W", _gauge_samples(telemetry, "agentbench_gpu_power_watts", start, end)),
            ]
            for lane, metric, unit, samples in extracted:
                if len(samples) < 2:
                    raise ValueError("private telemetry is incomplete for a public series")
                synchronized.append(
                    {"lane": lane, "metric": metric, "engine": engine, "users": users, "unit": unit, "samples": samples}
                )

    return {
        "study": {
            "title": "Episode 01 — The queue changes the winner",
            "model_family": "Qwen3.8 27B",
            "precision": "FP8 weights and KV cache",
            "hardware": "NVIDIA H200",
            "hardware_count": 1,
        },
        "methodology": {
            "warmup_seconds": 120,
            "measurement_seconds": 300,
            "sessions_per_user": 2,
            "decode_threshold_tps": 20,
        },
        "source_arms": [
            {"engine": "vLLM", "publishable": True, "marker": "circle", "line_style": "solid", "points": arms["vLLM"]},
            {"engine": "SGLang", "publishable": True, "marker": "diamond", "line_style": "dashed", "points": arms["SGLang"]},
        ],
        "synchronized_series": synchronized,
        "limitations": [
            "Capacity was not established under the declared service objectives.",
            "This is a recorded deployment comparison, not an engine-only benchmark.",
            "TTFT is reported for experience analysis but is not a capacity gate.",
            "Runtime-native cache gauges use incompatible definitions and are not ranked.",
        ],
    }


def validate_public_document(document: Mapping[str, object], schema: Mapping[str, object]) -> None:
    """Validate a public document without echoing candidate values in errors."""

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: tuple(str(item) for item in error.path))
    if errors:
        location = ".".join(str(item) for item in errors[0].absolute_path) or "root"
        raise ValueError(f"public evidence schema validation failed at {location}")


def validate_public_privacy(document: Mapping[str, object]) -> None:
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True)
    forbidden = (
        re.compile(r"(?:vllm|sglang)\s*:?\s*v?\d+\.\d+", re.IGNORECASE),
        re.compile(r"/(?:Users|home|srv|var|tmp)/"),
        re.compile(r"\b(?:agentbench|mirastacklabs)\b", re.IGNORECASE),
        re.compile(r"\b(?:flashattention|prefix caching|chunked prefill|triton attention|pytorch sampling)\b", re.IGNORECASE),
        re.compile(r"https?://", re.IGNORECASE),
    )
    if any(pattern.search(payload) for pattern in forbidden):
        raise ValueError("public evidence privacy validation failed")


def serialize_public_document(document: Mapping[str, object]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_if_valid(document: Mapping[str, object], schema_path: Path, output_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate_public_document(document, schema)
    validate_public_privacy(document)
    payload = serialize_public_document(document)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--vllm-12-run", type=Path)
    parser.add_argument("--vllm-16-24-run", type=Path)
    parser.add_argument("--sglang-run", type=Path)
    parser.add_argument("--receipt", type=Path, action="append", default=[])
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    run_paths = (args.vllm_12_run, args.vllm_16_24_run, args.sglang_run)
    if args.source is not None and any(run_paths):
        parser.error("--source cannot be combined with private run directories")
    if args.source is not None:
        source = json.loads(args.source.read_text(encoding="utf-8"))
    elif all(run_paths):
        source = build_private_source_from_runs(
            args.vllm_12_run,
            args.vllm_16_24_run,
            args.sglang_run,
            args.receipt,
        )
    else:
        parser.error("provide --source or all three private run directories")
    document = build_public_document(source)
    write_if_valid(document, args.schema, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
