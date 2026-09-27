"""External, immutable authorization receipt validation for Episode 1.

The verifier never creates an authorization receipt and never treats a command
line argument or compiler output as owner approval. The receipt must be a
separately retained artifact derived from an external user message.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from .episode1 import canonical_json
from .episode1_execution import validate_execution_approvals, verify_execution_candidate


class AuthorizationError(ValueError):
    """The external authorization receipt is invalid or does not match."""


_KEYS = {
    "schema_version", "plan_sha256", "plan_file_sha256", "material_file_sha256",
    "material_sha256",
    "source_commit", "approved_at", "source_kind", "source_reference_sha256",
    "spend_approval", "watchdog_risk_approval",
}

_MATERIAL_KEYS = {"aggregate_sha256", "classification", "files"}
_SOURCE_KEYS = {
    "schema_version", "source_channel", "plan_sha256", "approved_at",
    "spend_approval", "watchdog_risk_approval",
}
_SAFE_MATERIAL_COMPONENT = re.compile(r"^[A-Za-z0-9._@+-]+$")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise AuthorizationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _strict_json(value: bytes, label: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise AuthorizationError(f"{label} contains duplicate JSON keys")
            result[key] = item
        return result

    try:
        return json.loads(
            value.decode("utf-8", errors="strict"),
            parse_constant=lambda _item: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=unique,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuthorizationError(f"{label} is not strict JSON") from exc


def _canonical_material_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise AuthorizationError("material manifest path is invalid")
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise AuthorizationError("material manifest path contains control characters")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} or _SAFE_MATERIAL_COMPONENT.fullmatch(part) is None
        for part in path.parts
    ):
        raise AuthorizationError("material manifest path is not canonical and relative")
    return value


def _material_aggregate(value: bytes, material_files: Mapping[str, bytes]) -> str:
    manifest = _strict_json(value, "material file")
    if not isinstance(manifest, Mapping) or set(manifest) != _MATERIAL_KEYS:
        raise AuthorizationError("material manifest schema is open or incomplete")
    if manifest["classification"] != "execution_material_hashes":
        raise AuthorizationError("material manifest classification is invalid")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise AuthorizationError("material manifest files are missing")
    prior = ""
    expected_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "sha256"}:
            raise AuthorizationError("material manifest entry is open or incomplete")
        path = _canonical_material_path(entry["path"])
        if path <= prior:
            raise AuthorizationError("material manifest paths are invalid or unsorted")
        prior = path
        expected_paths.add(path)
        expected_digest = _digest(entry["sha256"], "material entry sha256")
        actual = material_files.get(path)
        if not isinstance(actual, bytes) or _sha256_bytes(actual) != expected_digest:
            raise AuthorizationError(f"material bytes do not match manifest for {path}")
    if set(material_files) != expected_paths:
        raise AuthorizationError("observed material file set does not exactly match manifest")
    aggregate = hashlib.sha256(canonical_json(files).encode()).hexdigest()
    if manifest["aggregate_sha256"] != aggregate:
        raise AuthorizationError("material manifest aggregate does not match its entries")
    return aggregate


def verify_authorization_receipt(
    plan: Mapping[str, Any], receipt: Mapping[str, Any], *, plan_file_bytes: bytes,
    material_file_bytes: bytes, source_record_bytes: bytes,
    material_files: Mapping[str, bytes], observed_source_commit: str,
    verification_time: datetime,
) -> str:
    """Validate a receipt and return its canonical SHA-256 identifier."""

    verify_execution_candidate(plan)
    if not isinstance(receipt, Mapping) or set(receipt) != _KEYS:
        raise AuthorizationError("authorization receipt schema is open or incomplete")
    if receipt["schema_version"] != "episode1.authorization-receipt.v1":
        raise AuthorizationError("unsupported authorization receipt schema")
    if receipt["source_kind"] != "retained_owner_record":
        raise AuthorizationError("authorization source must be a retained external owner record")
    _digest(receipt["source_reference_sha256"], "source_reference_sha256")
    if receipt["source_reference_sha256"] != _sha256_bytes(source_record_bytes):
        raise AuthorizationError("authorization does not bind the retained external source bytes")
    source = _strict_json(source_record_bytes, "authorization source record")
    if not isinstance(source, Mapping) or set(source) != _SOURCE_KEYS:
        raise AuthorizationError("authorization source record schema is open or incomplete")
    if source["schema_version"] != "episode1.owner-approval-record.v1":
        raise AuthorizationError("authorization source record schema is unsupported")
    if source["source_channel"] != "codex_user_message":
        raise AuthorizationError("authorization source record is not a retained Codex user message")
    if receipt["plan_sha256"] != plan["plan_sha256"]:
        raise AuthorizationError("authorization plan digest mismatch")
    if receipt["plan_file_sha256"] != _sha256_bytes(plan_file_bytes):
        raise AuthorizationError("authorization does not bind the exact plan file bytes")
    parsed_plan = _strict_json(plan_file_bytes, "plan file")
    if parsed_plan != dict(plan):
        raise AuthorizationError("plan file bytes do not parse to the verified plan")
    if receipt["material_file_sha256"] != _sha256_bytes(material_file_bytes):
        raise AuthorizationError("authorization does not bind the exact material file bytes")
    aggregate = _material_aggregate(material_file_bytes, material_files)
    if receipt["material_sha256"] != aggregate or aggregate != plan["material_sha256"]:
        raise AuthorizationError("material manifest aggregate does not match the compiled plan")
    if receipt["source_commit"] != plan["source_commit"]:
        raise AuthorizationError("authorization source commit mismatch")
    if observed_source_commit != plan["source_commit"]:
        raise AuthorizationError("launch-time source HEAD does not match the approved commit")
    timestamp = receipt["approved_at"]
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise AuthorizationError("approved_at must be an explicit UTC timestamp")
    try:
        approved_at = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise AuthorizationError("approved_at is invalid") from exc
    if approved_at.utcoffset() != timezone.utc.utcoffset(approved_at):
        raise AuthorizationError("approved_at must be UTC")
    if verification_time.tzinfo is None or verification_time.utcoffset() is None:
        raise AuthorizationError("verification_time must be timezone-aware")
    if approved_at > verification_time.astimezone(timezone.utc):
        raise AuthorizationError("approved_at is after the pre-create verification time")
    spend = receipt["spend_approval"]
    risk = receipt["watchdog_risk_approval"]
    if not isinstance(spend, str) or (risk is not None and not isinstance(risk, str)):
        raise AuthorizationError("approval responses have invalid types")
    validate_execution_approvals(
        plan, spend_approval=spend, watchdog_risk_approval=risk
    )
    expected_source = {
        "schema_version": "episode1.owner-approval-record.v1",
        "source_channel": "codex_user_message",
        "plan_sha256": plan["plan_sha256"],
        "approved_at": receipt["approved_at"],
        "spend_approval": spend,
        "watchdog_risk_approval": risk,
    }
    if dict(source) != expected_source:
        raise AuthorizationError(
            "retained owner record does not contain the exact approved plan and responses"
        )
    return hashlib.sha256(canonical_json(dict(receipt)).encode()).hexdigest()
