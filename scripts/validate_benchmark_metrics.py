#!/usr/bin/env python3
"""Import and validate a private metrics export against loopback VictoriaMetrics."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HTTP_TIMEOUT_SECONDS = 60
QUERY_NAMES = (
    "series_count",
    "sample_count",
    "client_family",
    "engine_family",
    "gpu_family",
    "counter_resets",
)


@dataclass(frozen=True)
class ImportSpec:
    archive: Path
    manifest: Path
    start: datetime
    end: datetime
    namespace: str

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window-must-be-utc")
        if self.start.utcoffset() != timezone.utc.utcoffset(self.start):
            raise ValueError("window-must-be-utc")
        if self.end.utcoffset() != timezone.utc.utcoffset(self.end):
            raise ValueError("window-must-be-utc")
        if self.end <= self.start:
            raise ValueError("window-order-invalid")
        if re.fullmatch(r"[1-9][0-9]{0,9}", self.namespace) is None:
            raise ValueError("namespace-must-be-numeric")


@dataclass(frozen=True)
class VerifiedExport:
    archive_sha256: str
    archive_bytes: int
    expected_series: int
    expected_samples: int
    match_expression: str
    duration_seconds: int


@dataclass(frozen=True)
class ImportResult:
    imported: bool
    status_code: int
    archive_sha256: str
    namespace: str


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    namespace: str
    archive_sha256: str
    archive_bytes: int
    series_count: int
    sample_count: int
    duplicate_samples: int
    query_names: tuple[str, ...]
    start_epoch: float
    end_epoch: float


@dataclass(frozen=True, order=True)
class Sample:
    metric: str
    labels: tuple[tuple[str, str], ...]
    timestamp: float
    value: float | None


@dataclass(frozen=True)
class ExportWindow:
    samples: tuple[Sample, ...]
    raw_sample_count: int
    duplicate_samples: int


Opener = Callable[[urllib.request.Request, int], Any]


def _default_open(request: urllib.request.Request, timeout: int):
    return urllib.request.urlopen(request, timeout=timeout)


def _strict_object(value: object, category: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(category)
    return value


def _nonnegative_int(value: object, category: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(category)
    return value


def _finite_number(value: object, category: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(category)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(category)
    return result


def assert_loopback_url(url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "http" or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError
        if parsed.path not in ("", "/") or host is None:
            raise ValueError
        if host.lower() == "localhost":
            return
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("victoriametrics-url-must-be-loopback") from None


def _read_manifest(path: Path) -> Mapping[str, Any]:
    try:
        return _strict_object(json.loads(path.read_text(encoding="utf-8")), "manifest-invalid")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest-invalid") from exc


def verify_export(spec: ImportSpec) -> VerifiedExport:
    try:
        archive = spec.archive.read_bytes()
    except OSError as exc:
        raise ValueError("archive-unreadable") from exc
    if len(archive) < 2 or archive[:2] != b"\x1f\x8b":
        raise ValueError("archive-not-gzip")
    manifest = _read_manifest(spec.manifest)
    files = _strict_object(manifest.get("files"), "manifest-files-invalid")
    declared_size = _nonnegative_int(files.get(spec.archive.name), "manifest-size-invalid")
    if declared_size != len(archive):
        raise ValueError("archive-size-mismatch")
    digest = hashlib.sha256(archive).hexdigest()
    declared_digest = manifest.get("sha256")
    if declared_digest is not None:
        if not isinstance(declared_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", declared_digest):
            raise ValueError("manifest-checksum-invalid")
        if not hmac.compare_digest(digest, declared_digest):
            raise ValueError("archive-checksum-mismatch")
    start_epoch = _finite_number(manifest.get("start_s"), "manifest-window-invalid")
    end_epoch = _finite_number(manifest.get("end_s"), "manifest-window-invalid")
    if abs(start_epoch - spec.start.timestamp()) > 0.001 or abs(end_epoch - spec.end.timestamp()) > 0.001:
        raise ValueError("manifest-window-mismatch")
    duration = int(round(end_epoch - start_epoch))
    if duration <= 0:
        raise ValueError("manifest-window-invalid")
    match_expression = manifest.get("match")
    if not isinstance(match_expression, str) or not match_expression.startswith("{"):
        raise ValueError("manifest-match-invalid")
    return VerifiedExport(
        archive_sha256=digest,
        archive_bytes=len(archive),
        expected_series=_nonnegative_int(manifest.get("series"), "manifest-series-invalid"),
        expected_samples=_nonnegative_int(manifest.get("samples"), "manifest-samples-invalid"),
        match_expression=match_expression,
        duration_seconds=duration,
    )


def _base_url(url: str) -> str:
    return url.rstrip("/")


def import_native_export(
    spec: ImportSpec,
    victoria_url: str,
    *,
    opener: Opener = _default_open,
) -> ImportResult:
    assert_loopback_url(victoria_url)
    verified = verify_export(spec)
    payload = spec.archive.read_bytes()
    query = urllib.parse.urlencode(
        {"extra_label": f"validation_namespace={spec.namespace}"}
    )
    endpoint = f"{_base_url(victoria_url)}/api/v1/import/native?{query}"
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Encoding": "gzip", "Content-Type": "application/octet-stream"},
        method="POST",
    )
    try:
        with opener(request, HTTP_TIMEOUT_SECONDS) as response:
            status = int(response.status)
            response.read(4096)
    except Exception as exc:
        raise ValueError("native-import-failed") from exc
    if status not in (200, 204):
        raise ValueError("native-import-failed")
    return ImportResult(True, status, verified.archive_sha256, spec.namespace)


def _scoped_match(match_expression: str, namespace: str) -> str:
    if not match_expression.startswith("{") or not match_expression.endswith("}"):
        raise ValueError("manifest-match-invalid")
    content = match_expression[1:-1].strip()
    separator = "," if content else ""
    return f'{{{content}{separator}validation_namespace="{namespace}"}}'


def _export_samples(
    spec: ImportSpec,
    victoria_url: str,
    verified: VerifiedExport,
    opener: Opener,
) -> ExportWindow:
    endpoint = f"{_base_url(victoria_url)}/api/v1/export"
    form = urllib.parse.urlencode(
        {
            "match[]": _scoped_match(verified.match_expression, spec.namespace),
            "start": f"{spec.start.timestamp():.6f}",
            "end": f"{spec.end.timestamp():.6f}",
        }
    ).encode("ascii")
    request = urllib.request.Request(
        endpoint,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with opener(request, HTTP_TIMEOUT_SECONDS) as response:
            if int(response.status) != 200:
                raise ValueError("query-request-failed")
            maximum = min(256 * 1024 * 1024, max(8 * 1024 * 1024, verified.expected_samples * 512))
            payload = response.read(maximum + 1)
            if len(payload) > maximum:
                raise ValueError("export-response-too-large")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("query-request-failed") from exc
    return normalize_export_samples(payload, spec.start, spec.end)


def normalize_export_samples(
    payload: bytes, start: datetime, end: datetime
) -> ExportWindow:
    rows: list[dict[str, object]] = []
    try:
        for raw_line in payload.splitlines():
            if raw_line.strip():
                decoded = json.loads(raw_line.decode("utf-8"))
                rows.append(dict(_strict_object(decoded, "export-response-invalid")))
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "export-response-invalid":
            raise
        raise ValueError("export-response-invalid") from exc
    lower, upper = start.timestamp(), end.timestamp()
    unique: dict[tuple[str, tuple[tuple[str, str], ...], float], Sample] = {}
    raw_sample_count = 0
    for row in rows:
        metric = _strict_object(row.get("metric"), "export-response-invalid")
        name = metric.get("__name__")
        if not isinstance(name, str) or not name:
            raise ValueError("export-response-invalid")
        labels = tuple(
            sorted(
                (str(key), str(value))
                for key, value in metric.items()
                if key != "__name__"
            )
        )
        timestamps = row.get("timestamps")
        values = row.get("values")
        if (
            not isinstance(timestamps, Sequence)
            or isinstance(timestamps, (str, bytes))
            or not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or len(timestamps) != len(values)
        ):
            raise ValueError("export-response-invalid")
        for raw_timestamp, raw_value in zip(timestamps, values, strict=True):
            raw_sample_count += 1
            timestamp = _finite_number(raw_timestamp, "export-response-invalid")
            if timestamp > 100_000_000_000:
                timestamp /= 1000.0
            value = None if raw_value is None else _finite_number(raw_value, "export-response-invalid")
            if timestamp < lower - 0.001 or timestamp > upper + 0.001:
                raise ValueError("out-of-window-sample")
            sample = Sample(name, labels, timestamp, value)
            key = (name, labels, timestamp)
            # Native exports can contain multiple rows for the same series and
            # timestamp. Reconcile the manifest against the raw exported row
            # count, then keep the first exported sample for analysis. This is
            # deterministic and prevents a later conflicting duplicate from
            # manufacturing a counter reset.
            unique.setdefault(key, sample)
    samples = tuple(sorted(unique.values()))
    return ExportWindow(
        samples=samples,
        raw_sample_count=raw_sample_count,
        duplicate_samples=raw_sample_count - len(samples),
    )


def run_validation_queries(
    spec: ImportSpec,
    victoria_url: str,
    *,
    opener: Opener = _default_open,
    visibility_timeout_seconds: float = 15,
    poll_interval_seconds: float = 0.25,
    sleeper: Callable[[float], None] = time.sleep,
) -> ValidationResult:
    assert_loopback_url(victoria_url)
    verified = verify_export(spec)
    if visibility_timeout_seconds < 0 or poll_interval_seconds < 0:
        raise ValueError("visibility-wait-invalid")
    deadline = time.monotonic() + visibility_timeout_seconds
    while True:
        window = _export_samples(spec, victoria_url, verified, opener)
        identities = {(sample.metric, sample.labels) for sample in window.samples}
        series_count = len(identities)
        sample_count = window.raw_sample_count
        if (
            series_count == verified.expected_series
            and sample_count == verified.expected_samples
        ):
            break
        if time.monotonic() >= deadline:
            if series_count != verified.expected_series:
                raise ValueError("series-count-mismatch")
            raise ValueError("sample-count-mismatch")
        sleeper(poll_interval_seconds)
    names = {metric for metric, _labels in identities}
    client_count = sum(name.startswith("agentbench_request") for name in names)
    engine_count = sum(name.startswith(("vllm_", "sglang_")) for name in names)
    gpu_count = sum(name.startswith("agentbench_gpu_") for name in names)
    if min(client_count, engine_count, gpu_count) <= 0:
        raise ValueError("missing-metric-family")
    assert_no_counter_resets(window.samples)
    return ValidationResult(
        passed=True,
        namespace=spec.namespace,
        archive_sha256=verified.archive_sha256,
        archive_bytes=verified.archive_bytes,
        series_count=series_count,
        sample_count=sample_count,
        duplicate_samples=window.duplicate_samples,
        query_names=QUERY_NAMES,
        start_epoch=spec.start.timestamp(),
        end_epoch=spec.end.timestamp(),
    )


def normalize_matrix_samples(
    payload: Mapping[str, object], start: datetime, end: datetime
) -> tuple[Sample, ...]:
    if payload.get("status") != "success":
        raise ValueError("matrix-response-invalid")
    data = _strict_object(payload.get("data"), "matrix-response-invalid")
    rows = data.get("result")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("matrix-response-invalid")
    lower, upper = start.timestamp(), end.timestamp()
    unique: dict[tuple[str, tuple[tuple[str, str], ...], float], Sample] = {}
    for raw_row in rows:
        row = _strict_object(raw_row, "matrix-response-invalid")
        metric = _strict_object(row.get("metric"), "matrix-response-invalid")
        name = metric.get("__name__")
        if not isinstance(name, str) or not name:
            raise ValueError("matrix-response-invalid")
        labels = tuple(
            sorted(
                (str(key), str(value))
                for key, value in metric.items()
                if key != "__name__"
            )
        )
        values = row.get("values")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError("matrix-response-invalid")
        for pair in values:
            if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
                raise ValueError("matrix-response-invalid")
            timestamp = _finite_number(pair[0], "matrix-response-invalid")
            value = _finite_number(float(pair[1]), "matrix-response-invalid")
            if timestamp < lower or timestamp > upper:
                raise ValueError("out-of-window-sample")
            sample = Sample(name, labels, timestamp, value)
            key = (name, labels, timestamp)
            previous = unique.get(key)
            if previous is not None and previous.value != value:
                raise ValueError("conflicting-duplicate-sample")
            unique[key] = sample
    return tuple(sorted(unique.values()))


def assert_no_counter_resets(samples: Sequence[Sample]) -> None:
    previous: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for sample in sorted(samples, key=lambda item: (item.metric, item.labels, item.timestamp)):
        if not sample.metric.endswith("_total"):
            continue
        identity = (sample.metric, sample.labels)
        if sample.value is None:
            previous.pop(identity, None)
            continue
        old = previous.get(identity)
        if old is not None and sample.value < old:
            raise ValueError("counter-reset")
        previous[identity] = sample.value


def write_private_receipt(result: ValidationResult, receipt_path: Path) -> None:
    resolved = receipt_path.resolve()
    if "dashboard" in resolved.parts:
        raise ValueError("receipt-cannot-be-written-to-dashboard")
    payload = {
        "schema": "private-metrics-validation.v1",
        "status": "passed" if result.passed else "failed",
        "namespace": result.namespace,
        "archive_sha256": result.archive_sha256,
        "archive_bytes": result.archive_bytes,
        "series_count": result.series_count,
        "sample_count": result.sample_count,
        "duplicate_samples": result.duplicate_samples,
        "checks": list(result.query_names),
        "window": {"start_epoch": result.start_epoch, "end_epoch": result.end_epoch},
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=resolved.parent, prefix=f".{resolved.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record_dashboard_checks(receipt_path: Path, checks: Mapping[str, str]) -> None:
    allowed_categories = {"client", "engine", "gpu"}
    allowed_states = {"passed", "passed_with_declared_gaps", "failed"}
    if set(checks) != allowed_categories or any(state not in allowed_states for state in checks.values()):
        raise ValueError("dashboard-checks-invalid")
    resolved = receipt_path.resolve()
    if "dashboard" in resolved.parts:
        raise ValueError("receipt-cannot-be-written-to-dashboard")
    receipt = dict(_read_manifest(resolved))
    if receipt.get("status") != "passed":
        raise ValueError("receipt-not-passed")
    receipt["dashboard_checks"] = dict(sorted(checks.items()))
    encoded = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=resolved.parent, prefix=f".{resolved.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include UTC offset")
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--start", type=_utc, required=True)
    parser.add_argument("--end", type=_utc, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--victoria-url", default="http://127.0.0.1:8428")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--skip-import", action="store_true")
    args = parser.parse_args(argv)
    spec = ImportSpec(args.archive, args.manifest, args.start, args.end, args.namespace)
    if not args.skip_import:
        import_native_export(spec, args.victoria_url)
    result = run_validation_queries(spec, args.victoria_url)
    write_private_receipt(result, args.receipt)
    print("metrics validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
