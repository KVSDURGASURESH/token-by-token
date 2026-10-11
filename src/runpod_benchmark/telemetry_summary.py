"""Pure, closed-world summaries for one Episode 1 telemetry series."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


RUNTIMES = frozenset({"vllm", "sglang"})
KINDS = frozenset({"counter", "gauge"})
STATUSES = frozenset({"ok", "missing", "error", "unsupported"})
STATUS_REASONS = frozenset({"not_reported", "scrape_failed", "parse_failed", "unsupported"})


class ContractError(ValueError):
    """The caller supplied data outside the closed sample/window contract."""


@dataclass(frozen=True)
class Window:
    clock_domain: str
    start_monotonic_ns: int
    end_monotonic_ns: int
    max_sampling_gap_ns: int
    process_identity: str
    process_start_identity: str
    runtime: str
    block: str


@dataclass(frozen=True)
class Series:
    kind: str
    metric_name: str
    labels: tuple[tuple[str, str], ...] = ()

    @classmethod
    def create(cls, kind: str, metric_name: str, labels: Mapping[str, str] | None = None) -> "Series":
        if labels is not None and not isinstance(labels, Mapping):
            raise ContractError("invalid_labels")
        try:
            canonical = tuple(sorted((labels or {}).items()))
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid_labels") from exc
        return cls(kind, metric_name, canonical)


_SAMPLE_KEYS = frozenset({
    "clock_domain", "monotonic_ns", "process_identity", "process_start_identity",
    "runtime", "block", "metric_name", "labels", "value", "status", "reason",
})


def _validate_window(window: Window, series: Series) -> None:
    if not isinstance(window, Window) or not isinstance(series, Series):
        raise ContractError("invalid_window_or_series")
    identity_values = (window.clock_domain, window.process_identity, window.process_start_identity,
                       window.runtime, window.block, series.kind, series.metric_name)
    if not all(isinstance(value, str) and value for value in identity_values):
        raise ContractError("empty_or_nonstring_identity")
    if window.runtime not in RUNTIMES or series.kind not in KINDS:
        raise ContractError("unsupported_runtime_or_kind")
    if (isinstance(window.start_monotonic_ns, bool) or not isinstance(window.start_monotonic_ns, int)
            or isinstance(window.end_monotonic_ns, bool) or not isinstance(window.end_monotonic_ns, int)):
        raise ContractError("invalid_window")
    if window.start_monotonic_ns < 0 or window.end_monotonic_ns <= window.start_monotonic_ns:
        raise ContractError("invalid_window")
    if (isinstance(window.max_sampling_gap_ns, bool) or not isinstance(window.max_sampling_gap_ns, int)
            or window.max_sampling_gap_ns <= 0):
        raise ContractError("invalid_max_sampling_gap")
    if not isinstance(series.labels, tuple) or not all(
        isinstance(pair, tuple) and len(pair) == 2 for pair in series.labels
    ):
        raise ContractError("invalid_labels")
    if not all(isinstance(k, str) and isinstance(v, str) and k for k, v in series.labels):
        raise ContractError("invalid_labels")
    try:
        canonical = tuple(sorted(series.labels))
    except TypeError as exc:
        raise ContractError("invalid_labels") from exc
    if len(dict(series.labels)) != len(series.labels) or canonical != series.labels:
        raise ContractError("labels_not_canonical")


def _parse_sample(raw: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ContractError("sample_mapping")
    if set(raw) != _SAMPLE_KEYS:
        raise ContractError("sample_keys")
    labels = raw["labels"]
    if not isinstance(labels, Mapping) or not all(
        isinstance(k, str) and k and isinstance(v, str) for k, v in labels.items()
    ):
        raise ContractError("sample_labels")
    status, reason = raw["status"], raw["reason"]
    if not isinstance(status, str) or status not in STATUSES:
        raise ContractError("sample_status")
    value = raw["value"]
    if status == "ok":
        if reason is not None or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractError("ok_sample_value")
    else:
        if value is not None or not isinstance(reason, str) or reason not in STATUS_REASONS:
            raise ContractError("unavailable_sample_value")
        if status == "missing" and reason != "not_reported":
            raise ContractError("missing_sample_reason")
        if status == "unsupported" and reason != "unsupported":
            raise ContractError("unsupported_sample_reason")
    timestamp = raw["monotonic_ns"]
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        raise ContractError("sample_timestamp")
    for key in ("clock_domain", "process_identity", "process_start_identity", "runtime", "block", "metric_name"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise ContractError("sample_identity")
    if raw["runtime"] not in RUNTIMES:
        raise ContractError("sample_runtime")
    return {**raw, "labels": tuple(sorted(labels.items()))}


def _unavailable(window: Window, series: Series, reason: str, sample_count: int = 0,
                 first_ns: int | None = None, last_ns: int | None = None,
                 max_gap_ns: int | None = None) -> dict[str, object]:
    return {
        "schema_version": "episode1.telemetry-summary.v1",
        "available": False,
        "unavailable_reason": reason,
        "runtime": window.runtime,
        "block": window.block,
        "clock_domain": window.clock_domain,
        "process_identity": window.process_identity,
        "process_start_identity": window.process_start_identity,
        "metric_name": series.metric_name,
        "labels": dict(series.labels),
        "kind": series.kind,
        "requested_start_monotonic_ns": window.start_monotonic_ns,
        "requested_end_monotonic_ns": window.end_monotonic_ns,
        "max_sampling_gap_ns": window.max_sampling_gap_ns,
        "first_sample_monotonic_ns": first_ns,
        "last_sample_monotonic_ns": last_ns,
        "sampled_interval_seconds": None,
        "observed_max_gap_ns": max_gap_ns,
        "sample_count": sample_count,
        "coverage": None,
        "counter": None,
        "gauge": None,
    }


def summarize(samples: Iterable[Mapping[str, object]], window: Window, series: Series) -> dict[str, object]:
    """Summarize exact observed samples without interpolation or reset repair."""
    _validate_window(window, series)
    parsed = [_parse_sample(sample) for sample in samples]
    # Labels define independent Prometheus series. Other label sets are ignored,
    # while every matching-label observation must retain one domain/identity.
    candidates = [s for s in parsed if s["runtime"] == window.runtime and s["block"] == window.block
                  and s["metric_name"] == series.metric_name and s["labels"] == series.labels]
    if not candidates:
        return _unavailable(window, series, "no_samples")
    if any(s["clock_domain"] != window.clock_domain for s in candidates):
        return _unavailable(window, series, "incompatible_clock_domain", len(candidates))
    timestamps = [int(s["monotonic_ns"]) for s in candidates]
    if any(right < left for left, right in zip(timestamps, timestamps[1:])):
        return _unavailable(window, series, "out_of_order", len(candidates))
    if len(set(timestamps)) != len(timestamps):
        return _unavailable(window, series, "duplicate_timestamp", len(candidates))
    left_indexes = [i for i, timestamp in enumerate(timestamps) if timestamp <= window.start_monotonic_ns]
    if not left_indexes:
        return _unavailable(window, series, "missing_left_bracket", len(candidates))
    right_indexes = [i for i, timestamp in enumerate(timestamps) if timestamp >= window.end_monotonic_ns]
    if not right_indexes:
        return _unavailable(window, series, "missing_right_bracket", len(candidates))
    left, right = left_indexes[-1], right_indexes[0]
    observed = candidates[left:right + 1]
    first_ns, last_ns = int(observed[0]["monotonic_ns"]), int(observed[-1]["monotonic_ns"])
    identities = {(s["process_identity"], s["process_start_identity"]) for s in observed}
    expected_identity = (window.process_identity, window.process_start_identity)
    if identities != {expected_identity}:
        return _unavailable(window, series, "identity_changed", len(observed), first_ns, last_ns)
    gaps = [int(b["monotonic_ns"]) - int(a["monotonic_ns"]) for a, b in zip(observed, observed[1:])]
    observed_max_gap = max(gaps, default=0)
    if observed_max_gap > window.max_sampling_gap_ns:
        return _unavailable(window, series, "sampling_gap_exceeded", len(observed), first_ns, last_ns,
                            observed_max_gap)
    bad = next((s for s in observed if s["status"] != "ok"), None)
    if bad is not None:
        reason = {"missing": "sample_missing", "error": "sample_error", "unsupported": "sample_unsupported"}[bad["status"]]
        return _unavailable(window, series, reason, len(observed), first_ns, last_ns, observed_max_gap)
    try:
        values = [float(s["value"]) for s in observed]
    except (OverflowError, TypeError, ValueError):
        values = []
    if not values or not all(math.isfinite(value) for value in values):
        return _unavailable(window, series, "nonfinite_value", len(observed), first_ns, last_ns,
                            observed_max_gap)
    try:
        elapsed_seconds = (last_ns - first_ns) / 1_000_000_000
    except OverflowError:
        return _unavailable(window, series, "derived_nonfinite", len(observed), first_ns, last_ns,
                            observed_max_gap)
    if not math.isfinite(elapsed_seconds):
        return _unavailable(window, series, "derived_nonfinite", len(observed), first_ns, last_ns,
                            observed_max_gap)
    coverage = "window_exact" if (first_ns == window.start_monotonic_ns and last_ns == window.end_monotonic_ns) else "sampled_interval_covering_window"
    result = _unavailable(window, series, "", len(observed), first_ns, last_ns, observed_max_gap)
    result.update({"available": True, "unavailable_reason": None, "sampled_interval_seconds": elapsed_seconds,
                   "coverage": coverage})
    if series.kind == "counter":
        if any(value < 0 for value in values):
            return _unavailable(window, series, "counter_negative", len(observed), first_ns, last_ns,
                                observed_max_gap)
        if any(current < previous for previous, current in zip(values, values[1:])):
            return _unavailable(window, series, "counter_decreased", len(observed), first_ns, last_ns,
                                observed_max_gap)
        delta = values[-1] - values[0]
        rate = delta / elapsed_seconds
        if not math.isfinite(delta) or not math.isfinite(rate):
            return _unavailable(window, series, "derived_nonfinite", len(observed), first_ns, last_ns,
                                observed_max_gap)
        result["counter"] = {"first": values[0], "last": values[-1], "delta": delta,
                             "rate_per_second": rate}
    else:
        try:
            stats = {"minimum": min(values), "maximum": max(values),
                     "mean": statistics.fmean(values), "median": statistics.median(values)}
        except OverflowError:
            return _unavailable(window, series, "derived_nonfinite", len(observed), first_ns, last_ns,
                                observed_max_gap)
        if not all(math.isfinite(value) for value in stats.values()):
            return _unavailable(window, series, "derived_nonfinite", len(observed), first_ns, last_ns,
                                observed_max_gap)
        result["gauge"] = stats
    return result
