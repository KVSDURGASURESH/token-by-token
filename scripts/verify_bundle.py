#!/usr/bin/env python3
"""Fail-closed verification for sanitized public benchmark bundles."""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import ipaddress
import json
import math
import re
import struct
import unicodedata
import zlib
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit

from compile_plan import PlanValidationError, plan_digest


REQUIRED_FILES = (
    "manifest.json",
    "plan.json",
    "runtime-attempts.json",
    "live-study.json",
    "gpu-summary.json",
    "journal.md",
    "report.md",
    "reproduction.md",
    "linkedin-post.md",
    "benchmark-summary.csv",
    "visual-alt-text.md",
    "checksums.sha256",
    "teardown.json",
)
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100_000
MAX_PNG_PIXELS = 4_000_000
SAFE_TEXT_SUFFIXES = {".json", ".md", ".csv", ".svg", ".sha256"}
KNOWN_BINARY_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x7fELF",
    b"\x1f\x8b",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",
    b"Rar!\x1a\x07",
    b"7z\xbc\xaf\x27\x1c",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
)
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")
URL_RE = re.compile(r"\b(?:https?|wss?|ssh)://[^\s<>\"']+", re.IGNORECASE)
HOST_PORT_RE = re.compile(
    r"(?<![A-Z0-9_.-])(?:\[([0-9A-F:.%]+)\]|((?:[A-Z0-9-]+\.)+[A-Z0-9-]+|"
    r"(?:\d{1,3}\.){3}\d{1,3}|localhost)):(?:[1-9]\d{0,4})(?!\d)",
    re.IGNORECASE,
)
ENDPOINT_ASSIGNMENT_RE = re.compile(
    r"(?im)(?<![A-Z0-9_-])[\"']?(?:endpoint|url|host|hostname|address|ip)"
    r"[\"']?(?![A-Z0-9_-])\s*[:=]\s*"
    r"[\"']?([^\s,\"']+)"
)
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?im)[\"']?(?:[A-Z0-9_.-]*[_-])?(?:API[_-]?KEY|ACCESS[_-]?KEY|"
    r"ACCESS[_-]?KEY[_-]?ID|SECRET[_-]?ACCESS[_-]?KEY|AUTHORIZATION|PASSWORD|"
    r"PASSWD|TOKEN|SECRET|CREDENTIALS?|CLIENT[_-]?SECRET|PRIVATE[_-]?KEY)"
    r"[\"']?\s*[:=]\s*[\"']?[^\s,\"']+"
)
SENSITIVE_JSON_KEYS = {
    "apikey",
    "accesskey",
    "accesstoken",
    "password",
    "passwd",
    "token",
    "secret",
    "secretkey",
    "clientsecret",
    "credential",
    "credentials",
    "privatekey",
}
ENDPOINT_JSON_KEYS = {"endpoint", "url", "host", "hostname", "address", "ip"}
SENSITIVE_JSON_SUFFIXES = (
    "authorization",
    "apikey",
    "accesskey",
    "accesskeyid",
    "secretaccesskey",
    "accesstoken",
    "password",
    "passwd",
    "token",
    "secret",
    "secretkey",
    "clientsecret",
    "credential",
    "credentials",
    "privatekey",
)
PROVIDER_IDENTITY_SUFFIXES = (
    "providerid",
    "provideridentity",
    "podid",
    "endpointid",
    "volumeid",
)
_RESOURCE_PROSE_GAP = r"[ \t]*(?:\r?\n[ \t]*)?"
PROVIDER_RESOURCE_PROSE_RE = re.compile(
    rf"\b(?:pod|endpoint|volume){_RESOURCE_PROSE_GAP}"
    rf"(?:(?:(?:was|identifier|id|named)|[:=,;|]|[-–—]){_RESOURCE_PROSE_GAP}){{0,3}}"
    r"[`'\"]?"
    r"((?!local-)(?=[a-z0-9_-]{12,}\b)(?=[a-z0-9_-]*\d)[a-z0-9_-]+)[`'\"]?",
    re.IGNORECASE,
)
NESTED_METRICS = (
    "client_ttft_ms",
    "client_tpot_ms",
    "client_itl_ms",
    "client_e2e_ms",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LOCAL_RESOURCE_REF_RE = re.compile(r"^local-[a-z0-9][a-z0-9-]{0,57}$")
RESOURCE_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RESOURCE_ATTEMPT_FIELDS = {"action", "resource_ref", "kind", "status"}
TEARDOWN_RESOURCE_FIELDS = {
    "resource_ref",
    "kind",
    "deleted",
    "inventory_absent",
    "direct_lookup",
}
RESOURCE_LIFECYCLE = {
    "create": "created",
    "delete": "deleted",
    "inventory_check": "absent",
    "direct_lookup": "not_found",
}
REPORT_COUNT_RE = {
    name: re.compile(rf"\b{name.replace('_', r'\s+')}\s*:\s*(\d+)\b", re.I)
    for name in ("successful_requests", "failed_requests")
}
SANITIZATION_RULES = (
    (
        "private-key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    ),
    (
        "credential",
        re.compile(
            r"\b(?:rp_[A-Za-z0-9_-]{12,}|(?:Authorization\s*:\s*)?Bearer\s+\S+)",
            re.IGNORECASE,
        ),
    ),
    (
        "email",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "account-identifier",
        re.compile(
            r"[\"']?(?:account|customer|owner|user)[_-]?id[\"']?\s*[:=]\s*[\"']?\S+",
            re.IGNORECASE,
        ),
    ),
    (
        "placeholder",
        re.compile(
            r"\$\{[^}\n]+\}|\{\{[^}\n]+\}\}|<(?:REPLACE|YOUR|TODO)[^>\n]*>|"
            r"\b(?:REPLACE_ME|CHANGEME|TBD|TODO)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


class StrictJSONError(ValueError):
    """Raised when input is not interoperable strict JSON."""


def _reject_constant(_value: str) -> None:
    raise StrictJSONError("non-finite constant")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError("duplicate object key")
        result[key] = value
    return result


def _strict_json(text: str) -> Any:
    try:
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except RecursionError as exc:
        raise StrictJSONError("JSON nesting exceeds parser limit") from exc
    if not isinstance(value, dict):
        raise StrictJSONError("required JSON document must be a finite object")
    _validate_json_tree(value)
    return value


def _validate_json_tree(value: Any) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            raise StrictJSONError("JSON tree exceeds safety limits")
        if isinstance(current, float) and not math.isfinite(current):
            raise StrictJSONError("JSON contains a non-finite number")
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)


def _safe_relative_path(raw: str) -> Path | None:
    if "\\" in raw or "\x00" in raw:
        return None
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        return None
    return Path(*pure.parts)


def _safe_location(path: Path) -> str:
    literal = path.as_posix()
    if literal in REQUIRED_FILES or literal == "visual-assets.json":
        return literal
    return "bundle-entry"


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.rstrip(".").lower()
    if normalized in {"localhost", "ip6-localhost"} or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _endpoint_host(value: str) -> str | None:
    candidate = value.strip().strip("[]")
    if not candidate:
        return None
    try:
        if "://" in candidate:
            return urlsplit(candidate).hostname
        if value.startswith("["):
            return value[1 : value.find("]")]
        if candidate.count(":") > 1:
            ipaddress.ip_address(candidate)
            return candidate
        return urlsplit("//" + candidate).hostname
    except (ValueError, IndexError):
        return None


def _standalone_ip_literals(
    text: str,
) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    candidates = re.findall(
        r"(?<![A-Z0-9_.])\[?[0-9A-F:.]+\]?(?![A-Z0-9_.])",
        text,
        flags=re.IGNORECASE,
    )
    for raw in candidates:
        candidate = raw.strip("[]")
        if "." not in candidate and ":" not in candidate:
            continue
        try:
            yield ipaddress.ip_address(candidate)
        except ValueError:
            continue


def _is_sensitive_json_key(normalized: str) -> bool:
    return normalized in SENSITIVE_JSON_KEYS or any(
        normalized.endswith(suffix) for suffix in SENSITIVE_JSON_SUFFIXES
    )


def _is_provider_identity_key(normalized: str) -> bool:
    return any(normalized.endswith(suffix) for suffix in PROVIDER_IDENTITY_SUFFIXES)


def _normalized_public_label(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).casefold()
    return "".join(
        character
        for character in normalized
        if character.isascii() and character.isalnum()
    )


def _is_provider_identity_label(label: str) -> bool:
    normalized = unicodedata.normalize("NFKD", label).casefold()
    pattern = "".join(
        character
        if character.isascii()
        else "?"
        for character in normalized
        if character.isalnum()
    )
    return any(
        len(pattern) >= len(suffix)
        and all(
            actual == expected or actual == "?"
            for actual, expected in zip(pattern[-len(suffix) :], suffix)
        )
        for suffix in PROVIDER_IDENTITY_SUFFIXES
    )


def _assignment_label_candidates(value: str) -> Iterable[str]:
    value = unicodedata.normalize("NFKC", value)
    start = 0
    for offset, character in enumerate(value):
        if character in ":=":
            yield value[start:offset]
            start = offset + 1
        elif character in ";,{}":
            start = offset + 1


def _markdown_table_fields(line: str) -> Iterable[str]:
    line = unicodedata.normalize("NFKC", line)
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    has_separator = False
    for character in line:
        if escaped:
            if character != "|":
                current.append("\\")
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            has_separator = True
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    if has_separator:
        yield from (field for field in fields if field.strip())


def _text_label_candidates(text: str, relative: Path) -> Iterable[str]:
    if relative.suffix.lower() == ".csv":
        try:
            for row_index, row in enumerate(csv.reader(text.splitlines())):
                if row_index == 0:
                    yield from row
                yield from (
                    field
                    for field, following in zip(row, row[1:])
                    if following.strip()
                )
                for field in row:
                    yield from _assignment_label_candidates(field)
        except (csv.Error, TypeError):
            return
        return
    for line in text.splitlines():
        line = unicodedata.normalize("NFKC", line)
        yield from _assignment_label_candidates(line)
        for field in _markdown_table_fields(line):
            yield field
            yield from _assignment_label_candidates(field)


def _sanitization_errors(text: str, relative: Path) -> list[str]:
    location = _safe_location(relative)
    errors = [
        f"sanitization[{rule}] at {location}"
        for rule, pattern in SANITIZATION_RULES
        if pattern.search(text)
    ]
    if CREDENTIAL_ASSIGNMENT_RE.search(text):
        errors.append(f"sanitization[credential] at {location}")
    if any(
        _is_provider_identity_label(label)
        for label in _text_label_candidates(text, relative)
    ):
        errors.append(f"sanitization[provider-identity] at {location}")
    if PROVIDER_RESOURCE_PROSE_RE.search(text):
        errors.append(f"sanitization[provider-identity] at {location}")
    for match in URL_RE.finditer(text):
        if not _is_loopback_host(urlsplit(match.group(0)).hostname):
            errors.append(f"sanitization[non-loopback-endpoint] at {location}")
            break
    if not any("non-loopback-endpoint" in error for error in errors):
        for match in HOST_PORT_RE.finditer(text):
            host = match.group(1) or match.group(2)
            if not _is_loopback_host(host):
                errors.append(f"sanitization[non-loopback-endpoint] at {location}")
                break
    if not any("non-loopback-endpoint" in error for error in errors):
        for match in ENDPOINT_ASSIGNMENT_RE.finditer(text):
            if not _is_loopback_host(_endpoint_host(match.group(1))):
                errors.append(f"sanitization[non-loopback-endpoint] at {location}")
                break
    if not any("non-loopback-endpoint" in error for error in errors):
        if any(not address.is_loopback for address in _standalone_ip_literals(text)):
            errors.append(f"sanitization[non-loopback-endpoint] at {location}")
    return errors


def _structured_sanitization_errors(value: dict[str, Any], relative: Path) -> list[str]:
    location = _safe_location(relative)
    errors: list[str] = []
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                normalized = _normalized_public_label(key)
                if _is_sensitive_json_key(normalized):
                    errors.append(f"sanitization[credential] at {location}")
                if _is_provider_identity_label(key):
                    errors.append(f"sanitization[provider-identity] at {location}")
                if normalized in ENDPOINT_JSON_KEYS and isinstance(child, str):
                    if not _is_loopback_host(_endpoint_host(child)):
                        errors.append(
                            f"sanitization[non-loopback-endpoint] at {location}"
                        )
                stack.append(child)
        elif isinstance(current, list):
            stack.extend(current)
    return errors


def _finite_nonnegative_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return number.is_finite() and number >= 0


def _metric_triplet(value: Any, fields: tuple[str, str, str]) -> tuple[Decimal, ...] | None:
    if not isinstance(value, dict):
        return None
    numbers: list[Decimal] = []
    for field in fields:
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        try:
            number = Decimal(str(item))
        except InvalidOperation:
            return None
        if not number.is_finite() or number < 0:
            return None
        numbers.append(number)
    result = tuple(numbers)
    if not result[0] <= result[1] <= result[2]:
        return None
    return result


def _validate_percentiles(study: Any, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(study, dict) or not isinstance(study.get("cells"), list) or not study["cells"]:
        errors.append("schema[live-study-cells] at live-study.json")
        return []
    valid_cells: list[dict[str, Any]] = []
    for index, cell in enumerate(study["cells"]):
        if not isinstance(cell, dict):
            errors.append(f"schema[percentiles] at live-study.json:cells[{index}]")
            continue
        nested = any(name in cell for name in NESTED_METRICS)
        if nested:
            valid = all(
                _metric_triplet(cell.get(metric), ("p50", "p95", "p99"))
                is not None
                for metric in NESTED_METRICS
            )
        else:
            valid = _metric_triplet(cell, ("p50_ms", "p95_ms", "p99_ms")) is not None
        if not valid:
            errors.append(f"schema[percentiles] at live-study.json:cells[{index}]")
        else:
            valid_cells.append(cell)
    return valid_cells


def _request_totals(study: Any, errors: list[str]) -> tuple[int, int] | None:
    if not isinstance(study, dict) or not isinstance(study.get("cells"), list):
        return None
    totals = [0, 0]
    for index, cell in enumerate(study["cells"]):
        if not isinstance(cell, dict):
            errors.append(f"schema[request-count] at live-study.json:cells[{index}]")
            return None
        for offset, key in enumerate(("successful_requests", "failed_requests")):
            value = cell.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"schema[request-count] at live-study.json:cells[{index}].{key}")
                return None
            totals[offset] += value
    return totals[0], totals[1]


def _integer_field(value: str | None) -> int | None:
    try:
        if value is None or not re.fullmatch(r"0|[1-9]\d*", value):
            return None
        return int(value)
    except ValueError:
        return None


def _decimal_csv_field(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def _cell_identity(cell: dict[str, Any]) -> tuple[str, ...] | None:
    runtime = cell.get("runtime")
    if not isinstance(runtime, str) or not runtime.strip():
        return None
    if "profile" in cell:
        profile = cell.get("profile")
        if not isinstance(profile, str) or not profile.strip():
            return None
        return runtime, profile
    return (runtime,)


def _validate_csv(text: str, cells: list[dict[str, Any]], errors: list[str]) -> None:
    try:
        reader = csv.DictReader(text.splitlines())
        fieldnames = reader.fieldnames
        rows = list(reader)
    except (csv.Error, TypeError):
        errors.append("schema[csv-schema] at benchmark-summary.csv")
        return
    required = {
        "runtime",
        "successful_requests",
        "failed_requests",
        "p50_ms",
        "p95_ms",
        "p99_ms",
    }
    if (
        not fieldnames
        or len(fieldnames) != len(set(fieldnames))
        or not required.issubset(fieldnames)
        or not rows
    ):
        errors.append("schema[csv-schema] at benchmark-summary.csv")
        return

    expected: dict[tuple[str, ...], tuple[int, int, tuple[Decimal, ...]]] = {}
    expected_envelopes: dict[tuple[str, ...], dict[str, str]] = {}
    nested_mode = any(any(metric in cell for metric in NESTED_METRICS) for cell in cells)
    normalized_mode = nested_mode and any(
        isinstance(cell.get(metric), dict) and "available" in cell[metric]
        for cell in cells
        for metric in NESTED_METRICS
    )
    normalized_fields = {
        "attempted_requests",
        "count",
        "percentile_method",
        "source",
        "available",
        "unavailable_reason",
        "warnings",
        "output_tokens_per_second",
        "qualifying_requests",
        "goodput_output_tokens",
        "goodput_tokens_per_second",
        "slo_contract",
    }
    includes_output_totals = any(
        cell.get("successful_output_tokens") is not None for cell in cells
    )
    if normalized_mode:
        if includes_output_totals:
            normalized_fields.update({"successful_output_tokens", "mean_output_tokens"})
        if not normalized_fields.issubset(fieldnames):
            errors.append("schema[csv-schema] at benchmark-summary.csv")
            return

    def rendered(value: Any) -> str:
        return "" if value is None else str(value)

    for cell in cells:
        identity = _cell_identity(cell)
        successful = cell.get("successful_requests")
        failed = cell.get("failed_requests")
        if (
            identity is None
            or isinstance(successful, bool)
            or not isinstance(successful, int)
            or successful < 0
            or isinstance(failed, bool)
            or not isinstance(failed, int)
            or failed < 0
        ):
            errors.append("schema[csv-alignment] at benchmark-summary.csv")
            return
        if nested_mode:
            if len(identity) != 2:
                errors.append("schema[csv-alignment] at benchmark-summary.csv")
                return
            for metric in NESTED_METRICS:
                triplet = _metric_triplet(cell.get(metric), ("p50", "p95", "p99"))
                if triplet is not None:
                    key = identity + (metric,)
                    if key in expected:
                        errors.append("schema[csv-alignment] at benchmark-summary.csv")
                        return
                    expected[key] = (successful, failed, triplet)
                    if normalized_mode:
                        distribution = cell[metric]
                        goodput = cell.get("goodput")
                        if not isinstance(distribution, dict) or not isinstance(goodput, dict):
                            errors.append("schema[csv-alignment] at benchmark-summary.csv")
                            return
                        attempted = successful + failed
                        envelope = {
                            "attempted_requests": str(attempted),
                            "count": rendered(distribution.get("count")),
                            "percentile_method": rendered(distribution.get("percentile_method")),
                            "source": rendered(distribution.get("source")),
                            "available": rendered(distribution.get("available")),
                            "unavailable_reason": rendered(distribution.get("unavailable_reason")),
                            "warnings": " | ".join(distribution.get("warnings", [])),
                            "output_tokens_per_second": rendered(cell.get("output_tokens_per_second")),
                            "qualifying_requests": rendered(goodput.get("qualifying_requests")),
                            "goodput_output_tokens": rendered(goodput.get("output_tokens")),
                            "goodput_tokens_per_second": rendered(goodput.get("tokens_per_second")),
                            "slo_contract": json.dumps(
                                goodput.get("slo_contract"), sort_keys=True, allow_nan=False
                            ),
                        }
                        if includes_output_totals:
                            output_total = cell.get("successful_output_tokens")
                            if (
                                isinstance(output_total, bool)
                                or not isinstance(output_total, int)
                                or output_total < 0
                                or successful == 0
                            ):
                                errors.append("schema[csv-alignment] at benchmark-summary.csv")
                                return
                            envelope["successful_output_tokens"] = str(output_total)
                            envelope["mean_output_tokens"] = str(output_total / successful)
                        expected_envelopes[key] = envelope
        else:
            triplet = _metric_triplet(cell, ("p50_ms", "p95_ms", "p99_ms"))
            if triplet is not None:
                if identity in expected:
                    errors.append("schema[csv-alignment] at benchmark-summary.csv")
                    return
                expected[identity] = (successful, failed, triplet)

    actual: dict[tuple[str, ...], tuple[int, int, tuple[Decimal, ...]]] = {}
    for row in rows:
        identity_parts = [row.get("runtime")]
        if nested_mode:
            identity_parts.extend((row.get("profile"), row.get("metric")))
        if any(not isinstance(part, str) or not part for part in identity_parts):
            errors.append("schema[csv-schema] at benchmark-summary.csv")
            return
        key = tuple(identity_parts)  # type: ignore[arg-type]
        successful = _integer_field(row.get("successful_requests"))
        failed = _integer_field(row.get("failed_requests"))
        triplet_values = tuple(
            _decimal_csv_field(row.get(field))
            for field in ("p50_ms", "p95_ms", "p99_ms")
        )
        if (
            key in actual
            or successful is None
            or failed is None
            or any(value is None for value in triplet_values)
            or not triplet_values[0] <= triplet_values[1] <= triplet_values[2]  # type: ignore[operator]
        ):
            errors.append("schema[csv-schema] at benchmark-summary.csv")
            return
        actual[key] = (successful, failed, triplet_values)  # type: ignore[arg-type]
    if actual != expected:
        errors.append("consistency[csv-alignment] at benchmark-summary.csv")
        return
    if normalized_mode:
        rows_by_key = {
            (row["runtime"], row["profile"], row["metric"]): row for row in rows
        }
        for key, envelope in expected_envelopes.items():
            row = rows_by_key.get(key)
            if row is None or any(row.get(field) != value for field, value in envelope.items()):
                errors.append("consistency[csv-envelope] at benchmark-summary.csv")
                return


def _report_counts(text: str) -> tuple[int | None, int | None]:
    counts: list[int | None] = []
    for name in ("successful_requests", "failed_requests"):
        match = REPORT_COUNT_RE[name].search(text)
        counts.append(int(match.group(1)) if match else None)
    return counts[0], counts[1]


def _validate_synthetic_binding(
    manifest: Any,
    plan: Any,
    runtime_attempts: Any,
    study: Any,
    teardown: Any,
    errors: list[str],
) -> bool:
    documents = (manifest, plan, runtime_attempts, study, teardown)
    marked = [
        isinstance(document, dict)
        and document.get("classification") == "fixture_zero_cost"
        for document in documents
    ]
    synthetic_claimed = any(marked) or (
        isinstance(teardown, dict)
        and teardown.get("evidence_scope") == "synthetic_non_provider"
    )
    if not synthetic_claimed:
        return False
    valid = all(marked)
    valid = valid and manifest.get("execution_mode") == "planning_only"
    valid = valid and plan.get("planning_only") is True
    cost = plan.get("cost") if isinstance(plan, dict) else None
    valid = valid and isinstance(cost, dict)
    if isinstance(cost, dict):
        for field in ("expected_usd", "maximum_usd"):
            try:
                amount = Decimal(str(cost.get(field)))
            except (InvalidOperation, ValueError):
                valid = False
            else:
                valid = valid and amount.is_finite() and amount == 0
    valid = valid and runtime_attempts.get("provider_calls_made") is False
    valid = valid and runtime_attempts.get("attempts") == []
    valid = valid and teardown.get("provider_calls_made") is False
    valid = valid and teardown.get("created_resources") == []
    valid = valid and teardown.get("evidence_scope") == "synthetic_non_provider"
    if not valid:
        errors.append("schema[synthetic-binding] at fixture documents")
    return valid


def _validate_compiled_fixture_plan_binding(
    plan: Any,
    files: dict[Path, bytes],
    json_values: dict[Path, Any],
    errors: list[str],
) -> None:
    """Bind compiler-backed fixture plans and staged dashboard data to sources."""

    if not isinstance(plan, dict) or "compiled_plan" not in plan:
        return
    valid = (
        plan.get("classification") == "fixture_zero_cost"
        and plan.get("planning_only") is True
        and plan.get("execution_ready") is False
        and plan.get("approvable") is False
    )
    compiled = plan.get("compiled_plan")
    advertised = plan.get("compiled_plan_digest")
    cost = plan.get("cost")
    if not isinstance(compiled, dict) or not isinstance(advertised, str):
        valid = False
    else:
        try:
            recomputed = plan_digest(compiled)
        except (PlanValidationError, KeyError, TypeError, ValueError):
            valid = False
        else:
            valid = valid and hmac.compare_digest(advertised, recomputed)
            compiled_manifest = compiled.get("manifest")
            compiled_cost = compiled.get("cost")
            valid = valid and compiled.get("execution_ready") is False
            valid = valid and isinstance(compiled_manifest, dict)
            if isinstance(compiled_manifest, dict):
                valid = valid and compiled_manifest.get("planning_only") is True
            valid = valid and isinstance(compiled_cost, dict)
            if isinstance(compiled_cost, dict):
                valid = valid and compiled_cost.get("expected_usd") == "0.00"
                valid = valid and compiled_cost.get("maximum_usd") == "0.00"
    valid = valid and isinstance(cost, dict)
    if isinstance(cost, dict):
        valid = valid and cost == {"expected_usd": "0.00", "maximum_usd": "0.00"}
    if not valid:
        errors.append("schema[compiled-plan-binding] at plan.json")

    study_path = Path("live-study.json")
    dashboard_path = Path("dashboard/latest.json")
    dashboard_valid = (
        study_path in files
        and dashboard_path in files
        and study_path in json_values
        and dashboard_path in json_values
        and files[study_path] == files[dashboard_path]
        and json_values[study_path] == json_values[dashboard_path]
    )
    if not dashboard_valid:
        errors.append("consistency[dashboard-binding] at dashboard/latest.json")


def _validate_publication_binding(
    manifest: Any,
    plan: Any,
    study: Any,
    files: dict[Path, bytes],
    json_values: dict[Path, Any],
    errors: list[str],
) -> None:
    """Bind publication identity, profile selection, and staged dashboard data."""

    if not all(isinstance(value, dict) for value in (manifest, plan, study)):
        return
    comparisons = (
        ("classification", "classification"),
        ("model", "model"),
        ("model_revision", "model_revision"),
        ("hardware", "gpu"),
        ("precision", "precision"),
    )
    for manifest_field, study_field in comparisons:
        if manifest_field in manifest and manifest.get(manifest_field) != study.get(study_field):
            errors.append("consistency[publication-identity] at manifest.json/live-study.json")
            break

    if "measured_profiles" in plan:
        profiles = plan.get("measured_profiles")
        study_profiles = [
            cell.get("profile")
            for cell in study.get("cells", [])
            if isinstance(cell, dict)
        ]
        valid_profiles = (
            isinstance(profiles, list)
            and bool(profiles)
            and all(isinstance(profile, str) and profile for profile in profiles)
            and len(profiles) == len(set(profiles))
            and set(profiles) == set(study_profiles)
        )
        if not valid_profiles:
            errors.append("consistency[measured-profiles] at plan.json/live-study.json")

    study_path = Path("live-study.json")
    dashboard_path = Path("dashboard/latest.json")
    if dashboard_path in files:
        dashboard_valid = (
            study_path in files
            and study_path in json_values
            and dashboard_path in json_values
            and files[study_path] == files[dashboard_path]
            and json_values[study_path] == json_values[dashboard_path]
        )
        if not dashboard_valid:
            errors.append("consistency[dashboard-binding] at dashboard/latest.json")


def _validate_teardown(teardown: Any, synthetic: bool, errors: list[str]) -> None:
    if not isinstance(teardown, dict):
        errors.append("schema[teardown-proof] at teardown.json")
        return
    resources = teardown.get("created_resources")
    if not isinstance(resources, list) or (not synthetic and not resources):
        errors.append("schema[teardown-proof] at teardown.json:created_resources")
    else:
        for index, resource in enumerate(resources):
            valid = isinstance(resource, dict) and all(
                (
                    resource.get("deleted") is True,
                    resource.get("inventory_absent") is True,
                    resource.get("direct_lookup") == "not_found",
                )
            )
            if not valid:
                errors.append(f"schema[teardown-proof] at teardown.json:created_resources[{index}]")
    if teardown.get("final_balance_observed") is not True:
        errors.append("schema[final-balance-attestation] at teardown.json:final_balance_observed")
    if "final_balance_usd" in teardown:
        errors.append("privacy[final-balance-amount] at teardown.json:final_balance_usd")


def _resource_identity(record: Any) -> tuple[str, str] | None:
    if not isinstance(record, dict):
        return None
    resource_ref = record.get("resource_ref")
    kind = record.get("kind")
    if (
        not isinstance(resource_ref, str)
        or not LOCAL_RESOURCE_REF_RE.fullmatch(resource_ref)
        or not isinstance(kind, str)
        or not RESOURCE_KIND_RE.fullmatch(kind)
    ):
        return None
    return resource_ref, kind


def _validate_live_resource_binding(
    runtime_attempts: Any, teardown: Any, errors: list[str]
) -> None:
    if not isinstance(runtime_attempts, dict) or not isinstance(teardown, dict):
        errors.append("schema[resource-binding] at runtime-attempts.json/teardown.json")
        return
    attempts = runtime_attempts.get("attempts")
    resources = teardown.get("created_resources")
    if not isinstance(attempts, list) or not isinstance(resources, list):
        errors.append("schema[resource-binding] at runtime-attempts.json/teardown.json")
        return
    if (attempts or resources) and not (
        runtime_attempts.get("provider_calls_made") is True
        and teardown.get("provider_calls_made") is True
    ):
        errors.append(
            "schema[provider-activity] at runtime-attempts.json/teardown.json"
        )
    attempt_schema_valid = all(
        isinstance(record, dict)
        and set(record) == RESOURCE_ATTEMPT_FIELDS
        and record.get("action") in RESOURCE_LIFECYCLE
        and record.get("status") == RESOURCE_LIFECYCLE.get(record.get("action"))
        and _resource_identity(record) is not None
        for record in attempts
    )
    teardown_schema_valid = all(
        isinstance(record, dict)
        and set(record) == TEARDOWN_RESOURCE_FIELDS
        and _resource_identity(record) is not None
        for record in resources
    )
    if not attempt_schema_valid or not teardown_schema_valid:
        errors.append("schema[resource-schema] at runtime-attempts.json/teardown.json")
    creation_records = [
        record
        for record in attempts
        if isinstance(record, dict) and record.get("action") == "create"
    ]
    creation_identities = [_resource_identity(record) for record in creation_records]
    lifecycle_identities = [_resource_identity(record) for record in attempts]
    teardown_identities = [_resource_identity(record) for record in resources]
    creation_refs = [identity[0] for identity in creation_identities if identity]
    teardown_refs = [identity[0] for identity in teardown_identities if identity]
    creation_set = set(creation_identities)
    valid = attempt_schema_valid and teardown_schema_valid
    valid = valid and bool(creation_records) and bool(resources)
    valid = valid and all(identity is not None for identity in creation_identities)
    valid = valid and all(identity is not None for identity in lifecycle_identities)
    valid = valid and all(identity is not None for identity in teardown_identities)
    valid = valid and len(creation_refs) == len(set(creation_refs))
    valid = valid and len(teardown_refs) == len(set(teardown_refs))
    valid = valid and len(creation_identities) == len(teardown_identities)
    valid = valid and creation_set == set(teardown_identities)
    valid = valid and all(
        identity in creation_set for identity in lifecycle_identities if identity
    )
    if not valid:
        errors.append("schema[resource-binding] at runtime-attempts.json/teardown.json")


def _walk_files(root: Path, errors: list[str]) -> dict[Path, bytes]:
    files: dict[Path, bytes] = {}
    try:
        entries = sorted(root.rglob("*"))
    except OSError:
        errors.append("filesystem[unreadable-root] at .")
        return files
    for path in entries:
        try:
            relative = path.relative_to(root)
            if path.is_symlink():
                errors.append(f"filesystem[symlink] at {_safe_location(relative)}")
                continue
            if path.is_dir():
                continue
            if not path.is_file():
                errors.append(f"filesystem[non-regular-file] at {_safe_location(relative)}")
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                errors.append(f"filesystem[oversized-file] at {_safe_location(relative)}")
                continue
            data = path.read_bytes()
        except OSError:
            errors.append(f"filesystem[unreadable-file] at {_safe_location(relative)}")
            continue
        files[relative] = data
    return files


def _validate_checksums(files: dict[Path, bytes], errors: list[str]) -> set[Path]:
    checksum_bytes = files.get(Path("checksums.sha256"))
    if checksum_bytes is None:
        return set()
    declared: dict[Path, str] = {}
    try:
        checksum_text = checksum_bytes.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("integrity[checksum-format] at checksums.sha256")
        return set()
    for line_number, line in enumerate(checksum_text.splitlines(), 1):
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            errors.append(f"integrity[checksum-format] at checksums.sha256:{line_number}")
            continue
        relative = _safe_relative_path(match.group(2))
        if relative is None:
            errors.append(f"integrity[checksum-path] at checksums.sha256:{line_number}")
            continue
        if relative == Path("checksums.sha256") or relative in declared:
            errors.append(f"integrity[checksum-entry] at checksums.sha256:{line_number}")
            continue
        declared[relative] = match.group(1)
    actual_paths = set(files) - {Path("checksums.sha256")}
    for relative in sorted(actual_paths - set(declared)):
        errors.append(f"integrity[checksum-missing] at {_safe_location(relative)}")
    for relative in sorted(set(declared) - actual_paths):
        errors.append(f"integrity[checksum-target] at checksums.sha256")
    for relative in sorted(actual_paths & set(declared)):
        actual = hashlib.sha256(files[relative]).hexdigest()
        if not hmac.compare_digest(actual, declared[relative]):
            errors.append(f"integrity[checksum-mismatch] at {_safe_location(relative)}")
    return set(declared)


def _validate_png(data: bytes, errors: list[str]) -> None:
    if not data.startswith(PNG_SIGNATURE):
        errors.append("binary[png-signature] at declared-asset")
        return
    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    for _ in range(1024):
        if offset + 12 > len(data):
            errors.append("binary[png-structure] at declared-asset")
            return
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        if length > MAX_FILE_BYTES or offset + 12 + length > len(data):
            errors.append("binary[png-structure] at declared-asset")
            return
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])[0]
        if zlib.crc32(kind + payload) != expected_crc:
            errors.append("binary[png-crc] at declared-asset")
            return
        if kind not in {b"IHDR", b"IDAT", b"IEND"}:
            errors.append("binary[png-metadata] at declared-asset")
            return
        chunks.append((kind, payload))
        offset += 12 + length
        if kind == b"IEND":
            break
    else:
        errors.append("binary[png-structure] at declared-asset")
        return
    kinds = [kind for kind, _payload in chunks]
    if (
        not chunks
        or kinds[0] != b"IHDR"
        or kinds[-1] != b"IEND"
        or kinds.count(b"IHDR") != 1
        or kinds.count(b"IEND") != 1
        or b"IDAT" not in kinds
        or offset != len(data)
    ):
        errors.append("binary[png-structure] at declared-asset")
        return
    first_idat = kinds.index(b"IDAT")
    last_idat = len(kinds) - 1 - kinds[::-1].index(b"IDAT")
    if any(kind != b"IDAT" for kind in kinds[first_idat : last_idat + 1]):
        errors.append("binary[png-structure] at declared-asset")
        return
    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        errors.append("binary[png-ihdr] at declared-asset")
        return
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    channels = {2: 3, 6: 4}.get(color_type)
    if (
        width < 1
        or height < 1
        or width * height > MAX_PNG_PIXELS
        or bit_depth != 8
        or channels is None
        or compression != 0
        or filtering != 0
        or interlace != 0
        or chunks[-1][1]
    ):
        errors.append("binary[png-ihdr] at declared-asset")
        return
    compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    expected_size = height * (1 + width * channels)
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(compressed, expected_size + 1)
        if len(raw) <= expected_size:
            raw += inflater.flush(expected_size + 1 - len(raw))
    except zlib.error:
        errors.append("binary[png-data] at declared-asset")
        return
    if (
        len(raw) != expected_size
        or not inflater.eof
        or inflater.unused_data
        or inflater.unconsumed_tail
    ):
        errors.append("binary[png-data] at declared-asset")
        return
    stride = 1 + width * channels
    if any(raw[row * stride] > 4 for row in range(height)):
        errors.append("binary[png-data] at declared-asset")


def _validate_binary_assets(
    files: dict[Path, bytes],
    texts: dict[Path, str],
    json_values: dict[Path, Any],
    checksummed: set[Path],
    errors: list[str],
) -> None:
    binary_paths = set(files) - set(texts)
    contract = json_values.get(Path("visual-assets.json"))
    declared_pngs: set[Path] = set()
    if contract is not None:
        if (
            contract.get("schema_version") != 1
            or contract.get("generator") != "build_publication_assets.py"
            or not isinstance(contract.get("assets"), list)
            or not contract["assets"]
        ):
            errors.append("schema[visual-assets] at visual-assets.json")
        else:
            for index, asset in enumerate(contract["assets"]):
                if not isinstance(asset, dict) or set(asset) != {
                    "path",
                    "media_type",
                    "source_paths",
                }:
                    errors.append(f"schema[visual-assets] at visual-assets.json:assets[{index}]")
                    continue
                asset_path = _safe_relative_path(asset.get("path", ""))
                source_paths = asset.get("source_paths")
                valid_path = (
                    asset_path is not None
                    and len(asset_path.parts) == 2
                    and asset_path.parts[0] == "charts"
                    and asset_path.suffix.lower() == ".png"
                )
                valid_sources = (
                    isinstance(source_paths, list)
                    and bool(source_paths)
                    and all(
                        isinstance(source, str)
                        and (source_path := _safe_relative_path(source)) is not None
                        and source_path in texts
                        and source_path in checksummed
                        for source in source_paths
                    )
                )
                if (
                    not valid_path
                    or asset.get("media_type") != "image/png"
                    or not valid_sources
                    or asset_path not in files
                    or asset_path not in checksummed
                    or asset_path in declared_pngs
                ):
                    errors.append(f"schema[visual-assets] at visual-assets.json:assets[{index}]")
                    continue
                declared_pngs.add(asset_path)
                _validate_png(files[asset_path], errors)
    for path in sorted(binary_paths):
        if files[path].startswith(PNG_SIGNATURE):
            if path not in declared_pngs:
                errors.append("binary[undeclared-png] at bundle-entry")
        else:
            errors.append("filesystem[binary-file] at bundle-entry")
            errors.append("binary[unsupported-binary] at bundle-entry")


def _has_known_binary_signature(data: bytes) -> bool:
    pdf_offset = data.find(b"%PDF-", 0, min(len(data), 1029))
    if 0 <= pdf_offset < 1024:
        return True
    return any(data.startswith(signature) for signature in KNOWN_BINARY_SIGNATURES)


def _verify_bundle(root: Path) -> VerificationResult:
    errors: list[str] = []
    warnings: list[str] = []
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        return VerificationResult(False, ("filesystem[invalid-root] at .",), ())

    files = _walk_files(root, errors)
    for name in REQUIRED_FILES:
        relative = Path(name)
        if relative not in files:
            errors.append(f"required-file[missing-or-unsafe] at {name}")

    texts: dict[Path, str] = {}
    json_values: dict[Path, Any] = {}
    for relative, data in files.items():
        suffix = relative.suffix.lower()
        is_png = suffix == ".png" or data.startswith(PNG_SIGNATURE)
        has_binary_signature = _has_known_binary_signature(data)
        if suffix not in SAFE_TEXT_SUFFIXES and not is_png:
            errors.append("filesystem[unsupported-suffix] at bundle-entry")
            continue
        if is_png or has_binary_signature:
            continue
        if any(byte < 32 and byte not in (9, 10, 13) for byte in data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        texts[relative] = text
        errors.extend(_sanitization_errors(text, relative))
        if relative.suffix == ".json":
            try:
                json_values[relative] = _strict_json(text)
            except (json.JSONDecodeError, StrictJSONError, RecursionError):
                errors.append(f"schema[strict-json] at {_safe_location(relative)}")
            else:
                errors.extend(
                    _structured_sanitization_errors(json_values[relative], relative)
                )

    for relative in files:
        if relative.suffix == ".json" and relative not in texts:
            errors.append(f"schema[strict-json] at {_safe_location(relative)}")

    checksummed = _validate_checksums(files, errors)
    _validate_binary_assets(files, texts, json_values, checksummed, errors)
    study = json_values.get(Path("live-study.json"))
    cells = _validate_percentiles(study, errors)
    totals = _request_totals(study, errors)
    csv_text = texts.get(Path("benchmark-summary.csv"))
    if csv_text is not None:
        _validate_csv(csv_text, cells, errors)
    report_text = texts.get(Path("report.md"), "")
    report_counts = _report_counts(report_text)
    if totals is not None:
        if report_counts[0] != totals[0]:
            errors.append("consistency[request-count] at report.md")
        if totals[1] > 0 and report_counts[1] != totals[1]:
            errors.append("consistency[error-disclosure] at report.md")
        elif totals[1] == 0 and report_counts[1] != 0:
            errors.append("consistency[request-count] at report.md")
    manifest = json_values.get(Path("manifest.json"))
    plan = json_values.get(Path("plan.json"))
    runtime_attempts = json_values.get(Path("runtime-attempts.json"))
    teardown = json_values.get(Path("teardown.json"))
    synthetic = _validate_synthetic_binding(
        manifest, plan, runtime_attempts, study, teardown, errors
    )
    _validate_publication_binding(manifest, plan, study, files, json_values, errors)
    _validate_compiled_fixture_plan_binding(plan, files, json_values, errors)
    _validate_teardown(teardown, synthetic, errors)
    if not synthetic:
        _validate_live_resource_binding(runtime_attempts, teardown, errors)

    unique_errors = tuple(dict.fromkeys(errors))
    return VerificationResult(not unique_errors, unique_errors, tuple(warnings))


def verify_bundle(root: Path) -> VerificationResult:
    """Verify a public bundle without disclosing any matched sensitive value."""
    try:
        return _verify_bundle(root)
    except Exception:
        return VerificationResult(
            False, ("verification[internal-failure] at bundle-root",), ()
        )


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    result = verify_bundle(args.root)
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
