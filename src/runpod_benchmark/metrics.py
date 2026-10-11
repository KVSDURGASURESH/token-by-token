"""Client-derived request metrics for exploratory benchmark cells."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


_PERCENTILE_METHOD = "linear_rank_n_minus_1"
_REQUEST_LATENCY_SLOS = {
    "ttft_ms",
    "tpot_ms",
    "client_inter_chunk_ms",
    "e2e_ms",
}


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _finite_values(values: Iterable[object]) -> list[float]:
    normalized: list[float] = []
    for value in values:
        number = _finite_number(value)
        if number is None:
            raise ValueError("distribution values must be finite numbers")
        normalized.append(number)
    return normalized


def linear_percentile(values: Iterable[object], quantile: float) -> float | None:
    """Return the linearly interpolated percentile at rank ``(n - 1) * q``."""

    q = _finite_number(quantile)
    if q is None or not 0 <= q <= 1:
        raise ValueError("quantile must be a finite number between 0 and 1")
    ordered = sorted(_finite_values(values))
    if not ordered:
        return None

    rank = (len(ordered) - 1) * q
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = rank - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def unavailable_metric(name: str, unit: str, source: str, reason: str) -> dict[str, Any]:
    """Build the common envelope for a metric that could not be observed."""

    return {
        "name": name,
        "unit": unit,
        "source": source,
        "count": 0,
        "statistics": None,
        "percentile_method": _PERCENTILE_METHOD,
        "warnings": [],
        "available": False,
        "unavailable_reason": reason,
    }


def summarize_distribution(
    name: str,
    unit: str,
    source: str,
    values: Iterable[object],
) -> dict[str, Any]:
    """Summarize raw samples without averaging precomputed percentiles."""

    ordered = sorted(_finite_values(values))
    if not ordered:
        return unavailable_metric(name, unit, source, "no applicable observations")

    count = len(ordered)
    warnings: list[str] = []
    if count < 1000:
        warnings.append(
            f"p99 is based on {count} applicable observations; fewer than 1000 "
            "observations is a statistically weak p99 sample"
        )
    return {
        "name": name,
        "unit": unit,
        "source": source,
        "count": count,
        "statistics": {
            "minimum": ordered[0],
            "mean": sum(ordered) / count,
            "p50": linear_percentile(ordered, 0.50),
            "p95": linear_percentile(ordered, 0.95),
            "p99": linear_percentile(ordered, 0.99),
            "maximum": ordered[-1],
            "percentile_method": _PERCENTILE_METHOD,
        },
        "percentile_method": _PERCENTILE_METHOD,
        "warnings": warnings,
        "available": True,
        "unavailable_reason": None,
    }


def _is_success(record: Mapping[str, object]) -> bool:
    return record.get("success") is True


def _actual_output_tokens(record: Mapping[str, object]) -> int | None:
    value = record.get("output_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _actual_input_tokens(record: Mapping[str, object]) -> int | None:
    value = record.get("input_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _tpot_ms(record: Mapping[str, object]) -> float | None:
    if not _is_success(record):
        return None
    output_tokens = _actual_output_tokens(record)
    content_span_ms = _finite_number(record.get("content_span_ms"))
    if output_tokens is None or output_tokens < 2 or content_span_ms is None:
        return None
    if content_span_ms < 0:
        return None
    return content_span_ms / (output_tokens - 1)


def _inter_chunk_values(record: Mapping[str, object]) -> list[float]:
    raw = record.get("inter_chunk_ms")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    values: list[float] = []
    for value in raw:
        number = _finite_number(value)
        if number is not None and number >= 0:
            values.append(number)
    return values


def _request_meets_slos(
    record: Mapping[str, object],
    slos: Mapping[str, object],
) -> bool:
    """Evaluate applicable latency SLOs on one successful request."""

    for name in _REQUEST_LATENCY_SLOS:
        threshold = _finite_number(slos.get(name))
        if threshold is None:
            continue
        if name == "tpot_ms":
            observed = _tpot_ms(record)
            if observed is None or observed > threshold:
                return False
        elif name == "client_inter_chunk_ms":
            gaps = _inter_chunk_values(record)
            if not gaps or any(gap > threshold for gap in gaps):
                return False
        else:
            observed = _finite_number(record.get(name))
            if observed is None or observed > threshold:
                return False
    return True


def _present_nonnegative(records: Sequence[Mapping[str, object]], field: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = _finite_number(record.get(field))
        if value is not None and value >= 0:
            values.append(value)
    return values


def _rate_metric(
    name: str,
    value: float | None,
    count: int,
    unavailable_reason: str | None,
) -> dict[str, Any]:
    if unavailable_reason is not None:
        metric = unavailable_metric(name, "tokens/s", "client_derived", unavailable_reason)
        metric["count"] = count
        metric["percentile_method"] = None
        return metric
    return {
        "name": name,
        "unit": "tokens/s",
        "source": "client_derived",
        "count": count,
        "statistics": {"value": value},
        "percentile_method": None,
        "warnings": [],
        "available": True,
        "unavailable_reason": None,
    }


def summarize_requests(
    records: Iterable[Mapping[str, object]],
    measured_wall_seconds: float,
    slos: Mapping[str, object],
) -> dict[str, Any]:
    """Calculate latency distributions, token rates, errors, and goodput."""

    observations = list(records)
    successful = [record for record in observations if _is_success(record)]
    failed_count = len(observations) - len(successful)

    tpot_values = [value for record in successful if (value := _tpot_ms(record)) is not None]
    inter_chunk_values = [
        value for record in observations for value in _inter_chunk_values(record)
    ]
    tpot_metric = summarize_distribution(
        "tpot_ms", "ms", "client_derived", tpot_values
    )
    if not tpot_values and successful and all(
        (tokens := _actual_output_tokens(record)) is not None and tokens < 2
        for record in successful
    ):
        tpot_metric = unavailable_metric(
            "tpot_ms",
            "ms",
            "client_derived",
            "fewer than two exact output tokens; no post-first-token interval exists",
        )
    metrics = {
        "ttft_ms": summarize_distribution(
            "ttft_ms", "ms", "client_raw", _present_nonnegative(observations, "ttft_ms")
        ),
        "tpot_ms": tpot_metric,
        "client_inter_chunk_ms": summarize_distribution(
            "client_inter_chunk_ms", "ms", "client_stream_events", inter_chunk_values
        ),
        "e2e_ms": summarize_distribution(
            "e2e_ms", "ms", "client_raw", _present_nonnegative(successful, "e2e_ms")
        ),
        "send_lag_ms": summarize_distribution(
            "send_lag_ms", "ms", "client_schedule", _present_nonnegative(observations, "send_lag_ms")
        ),
    }

    valid_slos = {
        name: threshold
        for name in _REQUEST_LATENCY_SLOS
        if (threshold := _finite_number(slos.get(name))) is not None
        and threshold >= 0
    }
    goodput_records = (
        [record for record in successful if _request_meets_slos(record, valid_slos)]
        if valid_slos
        else []
    )
    successful_token_counts = [_actual_output_tokens(record) for record in successful]
    attempted_input_token_counts = [_actual_input_tokens(record) for record in observations]
    successful_input_token_counts = [_actual_input_tokens(record) for record in successful]
    goodput_token_counts = [_actual_output_tokens(record) for record in goodput_records]
    throughput_tokens_known = all(value is not None for value in successful_token_counts)
    goodput_tokens_known = all(value is not None for value in goodput_token_counts)
    successful_tokens = (
        sum(value for value in successful_token_counts if value is not None)
        if throughput_tokens_known
        else None
    )
    attempted_input_tokens = (
        sum(value for value in attempted_input_token_counts if value is not None)
        if all(value is not None for value in attempted_input_token_counts)
        else None
    )
    successful_input_tokens = (
        sum(value for value in successful_input_token_counts if value is not None)
        if all(value is not None for value in successful_input_token_counts)
        else None
    )
    stop_reasons: dict[str, int] = {}
    for record in successful:
        reason = record.get("stop_reason")
        if isinstance(reason, str) and reason:
            stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
    goodput_tokens = (
        sum(value for value in goodput_token_counts if value is not None)
        if goodput_tokens_known and valid_slos
        else None
    )
    wall_seconds = _finite_number(measured_wall_seconds)
    usable_wall_time = wall_seconds is not None and wall_seconds > 0
    wall_time_reason = (
        None if usable_wall_time else "measured wall time must be a positive finite number"
    )
    throughput_reason = wall_time_reason
    if throughput_reason is None and not throughput_tokens_known:
        throughput_reason = "one or more successful requests have output token count unavailable"
    goodput_reason = (
        wall_time_reason if valid_slos else "nonempty latency SLO contract required for goodput"
    )
    if goodput_reason is None and not goodput_tokens_known:
        goodput_reason = (
            "one or more SLO-qualifying successful requests have output token count unavailable"
        )
    throughput = (
        successful_tokens / wall_seconds
        if throughput_reason is None and successful_tokens is not None
        else None
    )
    goodput = (
        goodput_tokens / wall_seconds
        if goodput_reason is None and goodput_tokens is not None
        else None
    )
    metrics["throughput_tokens_per_second"] = _rate_metric(
        "throughput_tokens_per_second", throughput, len(successful), throughput_reason
    )
    metrics["goodput_tokens_per_second"] = _rate_metric(
        "goodput_tokens_per_second", goodput, len(goodput_records), goodput_reason
    )

    return {
        "request_count": len(observations),
        "successful_requests": len(successful),
        "failed_requests": failed_count,
        "error_rate": failed_count / len(observations) if observations else None,
        "successful_output_tokens": successful_tokens,
        "attempted_input_tokens": attempted_input_tokens,
        "successful_input_tokens": successful_input_tokens,
        "stop_reasons": stop_reasons,
        "goodput_output_tokens": goodput_tokens,
        "goodput_requests": len(goodput_records) if valid_slos else None,
        "throughput_tokens_per_second": throughput,
        "goodput_tokens_per_second": goodput,
        "throughput_output_tokens_per_second": throughput,
        "goodput_output_tokens_per_second": goodput,
        "slo_contract": valid_slos,
        "metrics": metrics,
    }
