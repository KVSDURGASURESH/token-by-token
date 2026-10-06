#!/usr/bin/env python3
"""Build the closed, deterministic public benchmark evidence document."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
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
        "synchronized_series": [],
        "limitations": limitations,
    }
    return document


def validate_public_document(document: Mapping[str, object], schema: Mapping[str, object]) -> None:
    """Validate a public document without echoing candidate values in errors."""

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: tuple(str(item) for item in error.path))
    if errors:
        location = ".".join(str(item) for item in errors[0].absolute_path) or "root"
        raise ValueError(f"public evidence schema validation failed at {location}")


def serialize_public_document(document: Mapping[str, object]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_if_valid(document: Mapping[str, object], schema_path: Path, output_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate_public_document(document, schema)
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
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    source = json.loads(args.source.read_text(encoding="utf-8"))
    document = build_public_document(source)
    write_if_valid(document, args.schema, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
