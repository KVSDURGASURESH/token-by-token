"""Pure, fail-closed promotion gate for private Episode 1 evidence.

The gate consumes already parsed private artifacts.  It performs no I/O and
does not trust producer-supplied pass/fail booleans: hashes, the lifecycle
chain, schedule coverage, cleanup facts, and approval text are recomputed.
"""

from __future__ import annotations

import hashlib
import base64
import binascii
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from runpod_benchmark.episode1 import CELLS, authored_quality_corpus, canonical_json, paired_block_schedule, validate_observation
from runpod_benchmark.episode1_execution import (
    validate_execution_approvals,
    verify_execution_candidate,
)


class PromotionError(ValueError):
    """Evidence is malformed, incomplete, corrupt, or inconsistently bound."""


HEX = re.compile(r"^[0-9a-f]{64}$")
OPAQUE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
OCI = re.compile(r"^sha256:[0-9a-f]{64}$")
POD_ID = re.compile(r"^[A-Za-z0-9_-]+$", re.ASCII)
IMAGE_REFERENCE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$", re.ASCII)
ZERO = "0" * 64


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def seal(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy carrying a canonical hash (useful to producers/tests)."""
    result = dict(value)
    if "artifact_sha256" in result:
        raise ValueError("artifact already sealed")
    result["artifact_sha256"] = digest(result)
    return result


def _closed(value: object, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionError(f"{path} must be an object")
    missing, extra = keys - set(value), set(value) - keys
    if missing or extra:
        raise PromotionError(f"{path} fields invalid; missing={sorted(missing)} extra={sorted(extra)}")
    return value


def _seq(value: object, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise PromotionError(f"{path} must be an array")
    return value


def _string(value: object, path: str, *, opaque: bool = False) -> str:
    if not isinstance(value, str) or not value or (opaque and OPAQUE.fullmatch(value) is None):
        raise PromotionError(f"{path} must be a nonempty{' opaque' if opaque else ''} string")
    return value


def _hex(value: object, path: str, *, oci: bool = False) -> str:
    if not isinstance(value, str) or (OCI if oci else HEX).fullmatch(value) is None:
        raise PromotionError(f"{path} must be a canonical digest")
    return value


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PromotionError(f"{path} must be an integer >= {minimum}")
    return value


def _sealed(value: object, path: str, keys: set[str]) -> Mapping[str, Any]:
    artifact = _closed(value, path, keys | {"artifact_sha256"})
    claimed = _hex(artifact["artifact_sha256"], f"{path}.artifact_sha256")
    body = dict(artifact)
    del body["artifact_sha256"]
    if claimed != digest(body):
        raise PromotionError(f"{path} hash mismatch")
    return artifact


def _common(value: Mapping[str, Any], path: str, binding: tuple[str, str, str]) -> None:
    run_id, attempt_id, plan_sha256 = binding
    if (
        value["run_id"] != run_id
        or value["attempt_id"] != attempt_id
        or value["plan_sha256"] != plan_sha256
    ):
        raise PromotionError(f"{path} binding mismatch")


def _validate_manifest(plan: Mapping[str, Any], raw: object) -> tuple[Mapping[str, Any], tuple[str, str, str]]:
    keys = {
        "schema_version", "run_id", "attempt_id", "plan_sha256", "protocol_sha256",
        "material_sha256", "source_commit", "image_digest", "collector_sha256",
        "private_schema_sha256", "records_sha256", "telemetry_sha256",
        "sources_sha256", "approval_sha256", "cleanup_sha256", "ledger_sha256", "settlement_sha256", "resource_identity_sha256",
        "allocation_authority_sha256",
        "provider_private_id", "provider_ownership_identity_sha256",
        "start_monotonic_ns", "hard_deadline_monotonic_ns",
    }
    value = _sealed(raw, "manifest", keys)
    if value["schema_version"] != "episode1.evidence-manifest.v1":
        raise PromotionError("manifest schema unsupported")
    run_id = _string(value["run_id"], "manifest.run_id", opaque=True)
    attempt_id = _string(value["attempt_id"], "manifest.attempt_id", opaque=True)
    plan_sha = _hex(value["plan_sha256"], "manifest.plan_sha256")
    if plan_sha != plan["plan_sha256"]:
        raise PromotionError("manifest plan mismatch")
    for name in (
        "protocol_sha256", "material_sha256", "collector_sha256", "private_schema_sha256",
        "records_sha256", "telemetry_sha256", "sources_sha256", "approval_sha256", "cleanup_sha256", "ledger_sha256", "settlement_sha256",
        "resource_identity_sha256",
        "allocation_authority_sha256",
    ):
        _hex(value[name], f"manifest.{name}")
    if not isinstance(value["provider_private_id"], str) or POD_ID.fullmatch(value["provider_private_id"]) is None:
        raise PromotionError("manifest provider private id invalid")
    _hex(value["provider_ownership_identity_sha256"], "manifest.provider_ownership_identity_sha256")
    _hex(value["image_digest"], "manifest.image_digest", oci=True)
    expected_image = {item["derived_image_digest"] for item in plan["runtime_builds"]}
    if expected_image != {value["image_digest"]}:
        raise PromotionError("manifest image digest mismatch")
    if (
        value["protocol_sha256"] != plan["protocol_sha256"]
        or value["material_sha256"] != plan["material_sha256"]
        or value["source_commit"] != plan["source_commit"]
        or value["collector_sha256"] != plan["capture"]["collector_sha256"]
        or value["private_schema_sha256"] != plan["capture"]["private_schema_sha256"]
    ):
        raise PromotionError("manifest material/source/capture binding mismatch")
    start = _integer(value["start_monotonic_ns"], "manifest.start_monotonic_ns", minimum=1)
    deadline = _integer(value["hard_deadline_monotonic_ns"], "manifest.hard_deadline_monotonic_ns", minimum=1)
    expected_span = int(plan["budget"]["maximum_lifetime_seconds"]) * 1_000_000_000
    if deadline - start != expected_span:
        raise PromotionError("manifest deadline is not the original plan-bound lifetime")
    return value, (run_id, attempt_id, plan_sha)


def _validate_allocation_authority(
    plan: Mapping[str, Any], raw: object, binding: tuple[str, str, str],
    manifest: Mapping[str, Any],
) -> Mapping[str, Any]:
    keys={"schema_version","run_id","attempt_id","plan_sha256","provider","private_id",
        "unique_name","ownership_token_sha256","billing_started_monotonic",
        "billing_started_monotonic_ns","original_t0_monotonic_ns","hard_deadline_monotonic_ns",
        "resource_identity_sha256","ownership_identity_sha256","immutable_allocation",
        "immutable_allocation_sha256"}
    value=_sealed(raw,"allocation_authority",keys)
    if value["schema_version"]!="episode1.sanitized-allocation-authority.v1":
        raise PromotionError("allocation authority schema unsupported")
    _common(value,"allocation_authority",binding)
    if value["provider"]!="runpod-rest-v2": raise PromotionError("allocation provider unsupported")
    private_id=value["private_id"]
    if not isinstance(private_id,str) or POD_ID.fullmatch(private_id) is None:
        raise PromotionError("allocation private id invalid")
    unique_name=_string(value["unique_name"],"allocation unique name",opaque=True)
    token_sha=_hex(value["ownership_token_sha256"],"allocation token digest")
    billing=value["billing_started_monotonic"]
    if isinstance(billing,bool) or not isinstance(billing,(int,float)) or not math.isfinite(billing) or billing<0:
        raise PromotionError("allocation billing start invalid")
    billing_ns=_integer(value["billing_started_monotonic_ns"],"allocation billing start ns",minimum=1)
    if int(billing*1_000_000_000)!=billing_ns:
        raise PromotionError("allocation billing representations disagree")
    start=_integer(value["original_t0_monotonic_ns"],"allocation original t0",minimum=1)
    deadline=_integer(value["hard_deadline_monotonic_ns"],"allocation hard deadline",minimum=1)
    if start!=manifest["start_monotonic_ns"] or deadline!=manifest["hard_deadline_monotonic_ns"] or not start<=billing_ns<=deadline:
        raise PromotionError("allocation authority lifetime mismatch")
    resource=digest({"provider":"runpod-rest-v2","private_id":private_id,
        "unique_name":unique_name,"ownership_token_sha256":token_sha,
        "billing_started_monotonic":billing})
    ownership=digest({"provider":"runpod-rest-v2","private_id":private_id,
        "unique_name":unique_name,"ownership_token_sha256":token_sha,
        "billing_started_monotonic_ns":billing_ns})
    facts=_closed(value["immutable_allocation"],"allocation immutable facts",{
        "private_id","unique_name","ssh_host","ssh_public_port","requested_image_reference",
        "provider_image_reference","gpu","gpu_count","data_center_id","cloud_type",
        "container_disk_gb","volume_gb","volume_mount_path","container_ssh_port"})
    if facts["private_id"]!=private_id or facts["unique_name"]!=unique_name:
        raise PromotionError("immutable allocation ownership mismatch")
    if not isinstance(facts["ssh_host"],str) or not facts["ssh_host"]:
        raise PromotionError("immutable allocation SSH host invalid")
    for name,minimum in (("ssh_public_port",1),("container_ssh_port",1),("gpu_count",1),
                         ("container_disk_gb",1),("volume_gb",0)):
        _integer(facts[name],f"immutable allocation {name}",minimum=minimum)
    if facts["ssh_public_port"]>65535 or facts["container_ssh_port"]>65535:
        raise PromotionError("immutable allocation SSH port invalid")
    requested_ref=facts["requested_image_reference"]
    provider_ref=facts["provider_image_reference"]
    approved_digest=manifest["image_digest"]
    if (not isinstance(requested_ref,str) or IMAGE_REFERENCE.fullmatch(requested_ref) is None
            or not isinstance(provider_ref,str) or IMAGE_REFERENCE.fullmatch(provider_ref) is None
            or requested_ref!=provider_ref
            or not requested_ref.endswith("@"+approved_digest)):
        raise PromotionError("immutable allocation image reference mismatch")
    expected={"gpu":plan["allocation"]["gpu"],"gpu_count":plan["allocation"]["gpu_count"],
        "data_center_id":plan["allocation"]["data_center_id"],"cloud_type":plan["allocation"]["cloud_type"],
        "container_disk_gb":plan["allocation"]["container_disk_gb"],"volume_gb":plan["allocation"]["volume_gb"],
        "volume_mount_path":plan["allocation"]["volume_mount_path"],
        "container_ssh_port":plan["access"]["ssh_port"]}
    if any(facts[name]!=expected_value for name,expected_value in expected.items()):
        raise PromotionError("immutable allocation differs from approved plan")
    immutable=digest(facts)
    if (value["resource_identity_sha256"]!=resource
            or value["ownership_identity_sha256"]!=ownership
            or value["immutable_allocation_sha256"]!=immutable
            or manifest["resource_identity_sha256"]!=resource
            or manifest["provider_ownership_identity_sha256"]!=ownership
            or manifest["provider_private_id"]!=private_id
            or manifest["allocation_authority_sha256"]!=value["artifact_sha256"]):
        raise PromotionError("allocation authority identity link mismatch")
    return value


def _validate_sources(plan: Mapping[str, Any], raw: object, binding: tuple[str, str, str]) -> Mapping[str, Any]:
    keys = {
        "schema_version", "run_id", "attempt_id", "plan_sha256", "source_commit",
        "protocol_sha256", "material_sha256", "collector_sha256",
        "private_schema_sha256", "runtime_builds",
    }
    value = _sealed(raw, "sources", keys)
    if value["schema_version"] != "episode1.immutable-sources.v1":
        raise PromotionError("sources schema unsupported")
    _common(value, "sources", binding)
    for name in ("protocol_sha256", "material_sha256", "collector_sha256", "private_schema_sha256"):
        _hex(value[name], f"sources.{name}")
    builds = _seq(value["runtime_builds"], "sources.runtime_builds")
    build_keys = {
        "runtime", "build_spec_sha256", "dependency_lock_sha256", "launcher_sha256",
        "build_attestation_sha256", "image_digest",
    }
    normalized = []
    for index, raw_build in enumerate(builds):
        item = _closed(raw_build, f"sources.runtime_builds[{index}]", build_keys)
        _string(item["runtime"], "sources.runtime")
        for name in ("build_spec_sha256", "dependency_lock_sha256", "launcher_sha256", "build_attestation_sha256"):
            _hex(item[name], f"sources.{name}")
        _hex(item["image_digest"], "sources.image_digest", oci=True)
        normalized.append(dict(item))
    expected_builds = [{
        "runtime": item["runtime"], "build_spec_sha256": item["build_spec_sha256"],
        "dependency_lock_sha256": item["dependency_lock_sha256"],
        "launcher_sha256": item["launcher_sha256"],
        "build_attestation_sha256": item["build_attestation_sha256"],
        "image_digest": item["derived_image_digest"],
    } for item in plan["runtime_builds"]]
    if normalized != expected_builds or any(value[name] != plan[name] for name in ("source_commit", "protocol_sha256", "material_sha256")) or value["collector_sha256"] != plan["capture"]["collector_sha256"] or value["private_schema_sha256"] != plan["capture"]["private_schema_sha256"]:
        raise PromotionError("immutable source inventory does not match the plan")
    return value


def _validate_approval(plan: Mapping[str, Any], raw: object, binding: tuple[str, str, str]) -> Mapping[str, Any]:
    keys = {
        "schema_version", "run_id", "attempt_id", "plan_sha256", "approved_plan_sha256",
        "spend_approval", "watchdog_risk_approval", "retained_receipt_sha256",
    }
    value = _sealed(raw, "approval", keys)
    if value["schema_version"] != "episode1.digest-approval-receipt.v1":
        raise PromotionError("approval schema unsupported")
    _common(value, "approval", binding)
    if value["approved_plan_sha256"] != binding[2]:
        raise PromotionError("approval does not bind the executed plan")
    _hex(value["retained_receipt_sha256"], "approval.retained_receipt_sha256")
    if not isinstance(value["spend_approval"], str):
        raise PromotionError("approval spend text must be a string")
    if value["watchdog_risk_approval"] is not None and not isinstance(value["watchdog_risk_approval"], str):
        raise PromotionError("approval watchdog text must be a string or null")
    try:
        validate_execution_approvals(
            plan,
            spend_approval=value["spend_approval"],
            watchdog_risk_approval=value["watchdog_risk_approval"],
        )
    except ValueError as exc:
        raise PromotionError("approval text does not authorize the plan") from exc
    return value


def _validate_records(plan: Mapping[str, Any], raw: object, binding: tuple[str, str, str]) -> tuple[Mapping[str, Any], list[dict[str, Any]], dict[tuple[str, str, bool], str], dict[tuple[str, str, bool], tuple[int, int]]]:
    keys = {"schema_version", "run_id", "attempt_id", "plan_sha256", "records"}
    artifact = _sealed(raw, "record_artifact", keys)
    if artifact["schema_version"] != "episode1.private-records.v1":
        raise PromotionError("record artifact schema unsupported")
    _common(artifact, "record_artifact", binding)
    records_raw = _seq(artifact["records"], "record_artifact.records")
    expected_blocks = {block["block_id"]: block for block in paired_block_schedule()}
    cells = {cell["id"]: cell for cell in CELLS}
    quality_ids = [task["task_id"] for task in authored_quality_corpus()]
    counts: Counter[tuple[str, str, bool]] = Counter()
    orders: dict[tuple[str, str, bool], set[int]] = defaultdict(set)
    request_ids: set[str] = set()
    grouped: dict[tuple[str, str, bool], list[Mapping[str, Any]]] = defaultdict(list)
    validated: list[dict[str, Any]] = []
    for index, raw_record in enumerate(records_raw):
        if not isinstance(raw_record, Mapping) or raw_record.get("evidence_class") != "provider_candidate":
            raise PromotionError(f"record[{index}] is not a private provider candidate")
        try:
            record = validate_observation(raw_record)
        except (TypeError, ValueError) as exc:
            raise PromotionError(f"record[{index}] invalid") from exc
        if record["status"] != "success":
            raise PromotionError("aborted or failed captures must remain private candidates")
        request_id = record["request_id"]
        if request_id in request_ids:
            raise PromotionError("request identifiers must be globally unique")
        request_ids.add(request_id)
        block = expected_blocks.get(record["block_id"])
        cell = cells.get(record["cell_id"])
        if block is None or cell is None or (
            record["pair_id"] != block["pair_id"]
            or record["runtime"] != block["runtime"]
            or record["cell_id"] not in block["cell_order"]
            or record["mode"] != cell["mode"]
        ):
            raise PromotionError("record is outside the frozen schedule")
        if record["mode"] == "fixed_output" and (
            record["input_tokens"] != cell["input_tokens"]
            or record["fixed_length_valid"] is not True
        ):
            raise PromotionError("fixed-output evidence violates the exact token contract")
        key = (record["block_id"], record["cell_id"], record["warmup"])
        if record["cell_id"] == "natural-quality" and record["quality_task_id"] != quality_ids[record["scheduled_order"] - 1]:
            raise PromotionError("natural-quality task identity disagrees with the authored schedule")
        counts[key] += 1
        if record["scheduled_order"] in orders[key]:
            raise PromotionError("duplicate scheduled order")
        orders[key].add(record["scheduled_order"])
        grouped[key].append(raw_record)
        validated.append(record)
    expected_total = 0
    for block in paired_block_schedule():
        for cell_id in block["cell_order"]:
            for warmup, field in ((True, "warmups"), (False, "requests")):
                expected = int(cells[cell_id][field])
                expected_total += expected
                key = (block["block_id"], cell_id, warmup)
                if counts[key] != expected or orders[key] != set(range(1, expected + 1)):
                    raise PromotionError(f"incomplete scheduled attempts for {key}")
    if expected_total != 600 or len(validated) != 600:
        raise PromotionError("record artifact must contain exact 72+528 coverage")
    group_hashes = {
        key: digest(sorted(values, key=lambda item: item["scheduled_order"]))
        for key, values in grouped.items()
    }
    group_bounds = {
        key: (min(item["a_ns"] for item in values), max(item["end_ns"] for item in values))
        for key, values in grouped.items()
    }
    if any(item["clock_domain"] != "client_monotonic_ns" for item in validated):
        raise PromotionError("record chronology must use the ledger client monotonic domain")
    return artifact, validated, group_hashes, group_bounds


def _validate_telemetry(raw: object, binding: tuple[str, str, str],
                        group_bounds: Mapping[tuple[str, str, bool], tuple[int, int]]) -> Mapping[str, Any]:
    keys = {"schema_version", "run_id", "attempt_id", "plan_sha256", "summaries"}
    artifact = _sealed(raw, "telemetry_artifact", keys)
    if artifact["schema_version"] != "episode1.private-telemetry.v1":
        raise PromotionError("telemetry artifact schema unsupported")
    _common(artifact, "telemetry_artifact", binding)
    summaries = _seq(artifact["summaries"], "telemetry_artifact.summaries")
    expected = {(block["block_id"], block["runtime"]) for block in paired_block_schedule()}
    seen_blocks: set[tuple[str, str]] = set()
    seen_series: set[tuple[str, str]] = set()
    seen_sources: set[tuple[str, str, str, str, tuple[tuple[str, str], ...]]] = set()
    reasons = {"unsupported", "not_reported", "scrape_failed", "sampling_gap", "counter_reset", "identity_changed", "nonfinite"}
    summary_keys = {
        "block_id", "runtime", "series_id", "source_kind", "metric_name", "kind", "labels",
        "status", "value",
        "unavailable_reason", "expected_samples", "observed_samples", "missing_samples",
        "samples_sha256",
    }
    counter_projection_keys = {
        "unit", "counter_semantics", "first_sample_monotonic_ns",
        "last_sample_monotonic_ns", "coverage",
    }
    # Source-window summaries predate native sampler series identities.  Keep
    # their closed schema distinct: requiring native-only ``series_id`` and
    # ``labels`` here would reject valid source-domain evidence.
    legacy_source_window_keys = (summary_keys - {"series_id", "labels"}) | {"observation_window"}
    series_source_window_keys = summary_keys | {"observation_window"}
    for index, raw_summary in enumerate(summaries):
        if (isinstance(raw_summary, Mapping)
                and frozenset(raw_summary) in {frozenset(legacy_source_window_keys),
                                               frozenset(series_source_window_keys)}):
            source_window_keys = (series_source_window_keys
                                  if "series_id" in raw_summary
                                  else legacy_source_window_keys)
            item = _closed(raw_summary, f"telemetry.summary[{index}]", source_window_keys)
            source_window = True
        elif (isinstance(raw_summary, Mapping)
              and raw_summary.get("kind")=="counter"
              and raw_summary.get("source_kind")!="system_source_window"):
            item = _closed(raw_summary, f"telemetry.summary[{index}]",
                           summary_keys|counter_projection_keys)
            source_window = False
        else:
            item = _closed(raw_summary, f"telemetry.summary[{index}]", summary_keys)
            source_window = False
        pair = (_string(item["block_id"], "telemetry.block_id", opaque=True), _string(item["runtime"], "telemetry.runtime"))
        if pair not in expected:
            raise PromotionError("telemetry block/runtime mismatch")
        seen_blocks.add(pair)
        if "series_id" in item:
            series_id = _string(item["series_id"], "telemetry.series_id", opaque=True)
            if (pair[0], series_id) in seen_series:
                raise PromotionError("duplicate telemetry series")
            seen_series.add((pair[0], series_id))
        source_kind = item["source_kind"]
        if source_kind not in {"native", "system", "system_source_window"}:
            raise PromotionError("telemetry source kind invalid")
        metric = _string(item["metric_name"], "telemetry.metric_name")
        if item["kind"] not in {"counter", "gauge"}:
            raise PromotionError("telemetry kind invalid")
        ordinary_counter=item["kind"]=="counter" and not source_window
        if ordinary_counter:
            _string(item["unit"], "telemetry.unit")
            if item["counter_semantics"]!="delta_over_actual_bracketing_interval":
                raise PromotionError("telemetry counter semantics invalid")
        labels = item.get("labels", {})
        if (not isinstance(labels, Mapping) or len(labels) > 16
                or any(not isinstance(key, str) or not key or len(key) > 256
                       or not isinstance(value, str) or not value or len(value) > 256
                       for key, value in labels.items())):
            raise PromotionError("telemetry labels invalid")
        source_identity = (pair[0], source_kind, metric, item["kind"], tuple(sorted(labels.items())))
        if source_identity in seen_sources:
            raise PromotionError("duplicate telemetry source identity")
        seen_sources.add(source_identity)
        expected_n = _integer(item["expected_samples"], "telemetry.expected_samples", minimum=1)
        observed = _integer(item["observed_samples"], "telemetry.observed_samples")
        missing = _integer(item["missing_samples"], "telemetry.missing_samples")
        if expected_n != observed + missing:
            raise PromotionError("telemetry sampling slots are not fully accounted")
        _hex(item["samples_sha256"], "telemetry.samples_sha256")
        if item["status"] == "available":
            if item["unavailable_reason"] is not None or missing != 0 or observed < 1:
                raise PromotionError("available telemetry has gaps or an unavailable reason")
            if item["kind"] == "counter":
                values = _closed(item["value"], "telemetry.value",
                                 {"first", "last", "delta", "rate_per_second", "elapsed_seconds"})
            else:
                values = _closed(item["value"], "telemetry.value", {"minimum", "maximum", "mean"})
            for number in values.values():
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                    raise PromotionError("available telemetry summary is nonfinite")
            if item["kind"] == "counter":
                if (values["first"] < 0 or values["last"] < values["first"]
                        or values["delta"] != values["last"] - values["first"]
                        or values["elapsed_seconds"] <= 0
                        or not math.isclose(values["rate_per_second"], values["delta"] / values["elapsed_seconds"], rel_tol=1e-12, abs_tol=0.0)):
                    raise PromotionError("counter summary is inconsistent")
            elif not values["minimum"] <= values["mean"] <= values["maximum"]:
                raise PromotionError("telemetry summary bounds are inconsistent")
        elif item["status"] == "unavailable":
            if item["value"] is not None or item["unavailable_reason"] not in reasons:
                raise PromotionError("unavailable telemetry must be null with a fixed reason")
        else:
            raise PromotionError("telemetry status invalid")
        if ordinary_counter:
            first=item["first_sample_monotonic_ns"]
            last=item["last_sample_monotonic_ns"]
            coverage=item["coverage"]
            if item["status"]=="available":
                first=_integer(first,"telemetry.first_sample_monotonic_ns")
                last=_integer(last,"telemetry.last_sample_monotonic_ns",minimum=1)
                if last<=first or coverage not in {"window_exact","sampled_interval_covering_window"}:
                    raise PromotionError("telemetry counter interval invalid")
                if not math.isclose(item["value"]["elapsed_seconds"],
                                    (last-first)/1_000_000_000,rel_tol=1e-12,abs_tol=0.0):
                    raise PromotionError("telemetry counter interval is inconsistent")
            else:
                if ((first is None)!=(last is None) or coverage is not None):
                    raise PromotionError("unavailable telemetry counter interval invalid")
                if first is not None:
                    first=_integer(first,"telemetry.first_sample_monotonic_ns")
                    last=_integer(last,"telemetry.last_sample_monotonic_ns",minimum=1)
                    if last<first: raise PromotionError("unavailable telemetry counter interval invalid")
        if source_window:
            if source_kind != "system_source_window":
                raise PromotionError("source-window telemetry kind invalid")
            window = _closed(item["observation_window"], "telemetry.observation_window", {
                "schema_version", "interval_role", "basis", "source_clock_domain",
                "source_boot_id_sha256", "source_start_monotonic_ns", "source_end_monotonic_ns",
                "duration_ns", "start_boundary_receipt_sha256", "end_boundary_receipt_sha256",
                "client_start_completed_monotonic_ns", "client_end_started_monotonic_ns", "association",
            })
            if (window["schema_version"] != "episode1.source-domain-window.v1"
                    or window["interval_role"] != "measured-block-observation"
                    or window["basis"] != "remote_source_monotonic"
                    or window["source_clock_domain"] != "linux-clock-monotonic"
                    or window["association"] != "causal_enclosure_no_clock_mapping"):
                raise PromotionError("source observation window semantics invalid")
            for key in ("source_boot_id_sha256", "start_boundary_receipt_sha256", "end_boundary_receipt_sha256"):
                _hex(window[key], f"telemetry.observation_window.{key}")
            source_start = _integer(window["source_start_monotonic_ns"], "source window start", minimum=1)
            source_end = _integer(window["source_end_monotonic_ns"], "source window end", minimum=1)
            duration = _integer(window["duration_ns"], "source window duration", minimum=1)
            if source_end <= source_start or duration != source_end - source_start:
                raise PromotionError("source observation interval invalid")
            client_start = _integer(window["client_start_completed_monotonic_ns"], "client start association", minimum=1)
            client_end = _integer(window["client_end_started_monotonic_ns"], "client end association", minimum=1)
            measured = [bounds for (block_id, _cell, warmup), bounds in group_bounds.items()
                        if block_id == pair[0] and warmup is False]
            if not measured or client_start > min(x[0] for x in measured) or client_end < max(x[1] for x in measured):
                raise PromotionError("source observation window does not causally enclose measured records")
    if seen_blocks != expected:
        raise PromotionError("telemetry must account for every block")
    return artifact


def _validate_cleanup(raw: object, binding: tuple[str, str, str], manifest: Mapping[str, Any]) -> tuple[Mapping[str, Any], dict[str, Mapping[str, Any]]]:
    keys = {"schema_version", "run_id", "attempt_id", "plan_sha256", "receipts"}
    artifact = _sealed(raw, "cleanup", keys)
    if artifact["schema_version"] != "episode1.provider-cleanup.v1":
        raise PromotionError("cleanup schema unsupported")
    _common(artifact, "cleanup", binding)
    receipts = _seq(artifact["receipts"], "cleanup.receipts")
    if len(receipts) != 3:
        raise PromotionError("cleanup requires exactly three provider observations")
    receipt_keys = {
        "schema_version", "kind", "run_id", "attempt_id", "plan_sha256",
        "delete_attempt",
        "resource_identity_sha256", "observed_monotonic_ns", "provider_response_sha256",
        "status", "complete", "resource_absent", "receipt_sha256",
    }
    expected = ("delete_ack", "inventory_read", "direct_read")
    result: dict[str, Mapping[str, Any]] = {}
    selected_attempt: int | None = None
    previous_time = manifest["start_monotonic_ns"]
    for index, (raw_receipt, kind) in enumerate(zip(receipts, expected, strict=True)):
        item = _closed(raw_receipt, f"cleanup.receipts[{index}]", receipt_keys)
        if item["schema_version"] != "episode1.provider-receipt.v1" or item["kind"] != kind:
            raise PromotionError("cleanup observations are not in provider call order")
        _common(item, f"cleanup.receipts[{index}]", binding)
        delete_attempt=_integer(item["delete_attempt"],"cleanup.delete_attempt",minimum=1)
        if selected_attempt is None: selected_attempt=delete_attempt
        elif delete_attempt!=selected_attempt: raise PromotionError("cleanup receipts mix delete attempts")
        if item["resource_identity_sha256"] != manifest["resource_identity_sha256"]:
            raise PromotionError("cleanup receipt resource identity mismatch")
        when = _integer(item["observed_monotonic_ns"], "cleanup.observed_monotonic_ns", minimum=1)
        if when <= previous_time or when > manifest["hard_deadline_monotonic_ns"]:
            raise PromotionError("cleanup receipt is stale, reordered, or after the original deadline")
        previous_time = when
        _hex(item["provider_response_sha256"], "cleanup.provider_response_sha256")
        body = dict(item); claimed = body.pop("receipt_sha256")
        _hex(claimed, "cleanup.receipt_sha256")
        if digest(body) != claimed:
            raise PromotionError("cleanup receipt hash mismatch")
        if kind == "delete_ack":
            valid = item["status"] == "acknowledged" and item["complete"] is None and item["resource_absent"] is None
        elif kind == "inventory_read":
            valid = item["status"] == "complete" and item["complete"] is True and item["resource_absent"] is True
        else:
            valid = item["status"] == "not_found" and item["complete"] is None and item["resource_absent"] is None
        if not valid:
            raise PromotionError(f"cleanup {kind} does not prove deletion")
        result[kind] = item
    return artifact, result


def _provider_json(raw: bytes, path: str) -> Any:
    def unique(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PromotionError(f"{path} contains duplicate JSON keys")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=lambda _x: (_ for _ in ()).throw(ValueError()), object_pairs_hook=unique)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise PromotionError(f"{path} is not strict JSON") from None


def _provider_call(value: object, *, role: str, binding: tuple[str, str, str],
                   raw: bytes, ownership: str | None = None) -> Mapping[str, Any]:
    keys = {"schema_version","role","run_id","attempt_id","plan_sha256",
            "delete_attempt",
            "resource_identity_sha256","ownership_identity_sha256","http_method",
            "request_path","request_query","http_status","request_started_monotonic_ns",
            "body_complete_monotonic_ns","absolute_deadline_monotonic_ns",
            "operation_deadline_monotonic_ns","raw_body_sha256","raw_body_base64"}
    if role=="inventory-page":
        keys |= {"sequence","request_cursor","has_next_page","next_cursor"}
    item=_sealed(value,f"provider call {role}",keys)
    if item["schema_version"]!="episode1.provider-call-evidence.v1" or item["role"]!=role:
        raise PromotionError("provider call schema or role mismatch")
    _common(item,f"provider call {role}",binding)
    _integer(item["delete_attempt"],"provider delete attempt",minimum=1)
    _hex(item["resource_identity_sha256"],"provider resource identity")
    owner=_hex(item["ownership_identity_sha256"],"provider ownership identity")
    if ownership is not None and owner!=ownership: raise PromotionError("provider ownership identity mismatch")
    if not isinstance(item["request_path"],str) or not item["request_path"].startswith("/"):
        raise PromotionError("provider request path invalid")
    if not isinstance(item["request_query"],Mapping) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in item["request_query"].items()):
        raise PromotionError("provider query invalid")
    status=_integer(item["http_status"],"provider HTTP status",minimum=100)
    if status>599: raise PromotionError("provider HTTP status invalid")
    started=_integer(item["request_started_monotonic_ns"],"provider request start",minimum=1)
    completed=_integer(item["body_complete_monotonic_ns"],"provider body completion",minimum=1)
    op_deadline=_integer(item["operation_deadline_monotonic_ns"],"provider operation deadline",minimum=1)
    hard=_integer(item["absolute_deadline_monotonic_ns"],"provider hard deadline",minimum=1)
    if not started<=completed<op_deadline<=hard: raise PromotionError("provider call time bounds invalid")
    encoded=_string(item["raw_body_base64"],"provider raw body base64") if raw else item["raw_body_base64"]
    if not isinstance(encoded,str): raise PromotionError("provider raw body base64 invalid")
    try: embedded=base64.b64decode(encoded,validate=True)
    except (binascii.Error,ValueError): raise PromotionError("provider raw body base64 invalid") from None
    if embedded!=raw or _hex(item["raw_body_sha256"],"provider raw body digest")!=hashlib.sha256(raw).hexdigest():
        raise PromotionError("provider call raw body mismatch")
    return item


def _validate_provider_artifacts(raw: object, binding: tuple[str, str, str],
    cleanup_receipts: Mapping[str, Mapping[str, Any]],
    trusted_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    artifact=_sealed(raw,"provider_artifacts",{"schema_version","run_id","attempt_id","plan_sha256","artifacts"})
    if artifact["schema_version"]!="episode1.provider-artifacts.v1": raise PromotionError("provider artifacts schema unsupported")
    _common(artifact,"provider_artifacts",binding)
    values=_seq(artifact["artifacts"],"provider_artifacts.artifacts")
    expected=(("delete-response","delete_ack"),("inventory-after-delete","inventory_read"),("direct-after-delete","direct_read"))
    if len(values)!=3: raise PromotionError("provider artifacts require exactly three cleanup observations")
    decoded=[]
    for index,(raw_item,(role,receipt_kind)) in enumerate(zip(values,expected,strict=True)):
        item=_closed(raw_item,f"provider_artifacts.artifacts[{index}]",{"role","encoding","raw_base64","raw_sha256","bytes","evidence"})
        if item["role"]!=role or item["encoding"]!="base64": raise PromotionError("provider artifact role or encoding mismatch")
        if not isinstance(item["raw_base64"],str): raise PromotionError("provider artifact payload must be base64 text")
        try: exact=base64.b64decode(item["raw_base64"],validate=True)
        except (binascii.Error,ValueError): raise PromotionError("provider artifact payload is invalid base64") from None
        size=_integer(item["bytes"],"provider artifact bytes")
        actual=hashlib.sha256(exact).hexdigest()
        if size!=len(exact) or size>16*1024*1024 or _hex(item["raw_sha256"],"provider artifact digest")!=actual or cleanup_receipts[receipt_kind]["provider_response_sha256"]!=actual:
            raise PromotionError("cleanup receipt is not backed by exact provider bytes")
        decoded.append((exact,item["evidence"]))
    delete=_provider_call(decoded[0][1],role="delete-response",binding=binding,raw=decoded[0][0])
    direct=_provider_call(decoded[2][1],role="direct-after-delete",binding=binding,raw=decoded[2][0],ownership=delete["ownership_identity_sha256"])
    selected_attempt=cleanup_receipts["delete_ack"]["delete_attempt"]
    if (delete["delete_attempt"]!=selected_attempt or direct["delete_attempt"]!=selected_attempt
            or any(receipt["delete_attempt"]!=selected_attempt for receipt in cleanup_receipts.values())):
        raise PromotionError("provider cleanup evidence mixes delete attempts")
    if delete["http_method"]!="DELETE" or delete["http_status"]!=204 or delete["request_query"]!={}:
        raise PromotionError("delete artifact does not prove an acknowledged DELETE")
    if decoded[0][0] != b"":
        raise PromotionError("DELETE 204 provider evidence must have an empty body")
    trusted_resource=_hex(trusted_manifest["resource_identity_sha256"],"trusted resource identity")
    trusted_ownership=_hex(trusted_manifest["provider_ownership_identity_sha256"],"trusted ownership identity")
    trusted_start=_integer(trusted_manifest["start_monotonic_ns"],"trusted start",minimum=1)
    trusted_deadline=_integer(trusted_manifest["hard_deadline_monotonic_ns"],"trusted hard deadline",minimum=1)
    owned_id=trusted_manifest["provider_private_id"]
    if not isinstance(owned_id,str) or POD_ID.fullmatch(owned_id) is None:
        raise PromotionError("trusted provider private id invalid")
    owned_path=f"/pods/{owned_id}"
    if (delete["resource_identity_sha256"]!=trusted_resource
            or delete["ownership_identity_sha256"]!=trusted_ownership
            or delete["absolute_deadline_monotonic_ns"]!=trusted_deadline
            or delete["request_started_monotonic_ns"]<trusted_start
            or delete["request_path"]!=owned_path):
        raise PromotionError("delete artifact does not bind trusted owned resource")
    if direct["http_method"]!="GET" or direct["http_status"]!=404 or direct["request_query"]!={} or direct["request_path"]!=delete["request_path"]:
        raise PromotionError("direct artifact does not prove same-resource absence")
    if direct["resource_identity_sha256"]!=delete["resource_identity_sha256"] or direct["absolute_deadline_monotonic_ns"]!=delete["absolute_deadline_monotonic_ns"]:
        raise PromotionError("direct artifact binding mismatch")
    if cleanup_receipts["delete_ack"]["observed_monotonic_ns"] != delete["body_complete_monotonic_ns"]:
        raise PromotionError("delete receipt completion does not match provider evidence")
    manifest=_sealed(decoded[1][1],"inventory evidence",{"schema_version","role","delete_attempt","run_id","attempt_id","plan_sha256","resource_identity_sha256","ownership_identity_sha256","absolute_deadline_monotonic_ns","pages","terminal_page_sequence","terminal_next_cursor","complete","resource_absent"})
    if decoded[1][0]!=canonical_json(manifest).encode() or manifest["schema_version"]!="episode1.provider-inventory-evidence.v1" or manifest["role"]!="inventory-after-delete":
        raise PromotionError("inventory manifest bytes or schema mismatch")
    _common(manifest,"inventory evidence",binding)
    if _integer(manifest["delete_attempt"],"inventory delete attempt",minimum=1)!=selected_attempt:
        raise PromotionError("inventory manifest belongs to another delete attempt")
    if manifest["ownership_identity_sha256"]!=delete["ownership_identity_sha256"] or manifest["resource_identity_sha256"]!=delete["resource_identity_sha256"]:
        raise PromotionError("inventory identity mismatch")
    if manifest["absolute_deadline_monotonic_ns"]!=delete["absolute_deadline_monotonic_ns"]:
        raise PromotionError("inventory deadline mismatch")
    pages=_seq(manifest["pages"],"inventory pages")
    terminal_sequence=_integer(manifest["terminal_page_sequence"],"inventory terminal sequence",minimum=1)
    if not pages or terminal_sequence!=len(pages) or manifest["terminal_next_cursor"] is not None or manifest["complete"] is not True or manifest["resource_absent"] is not True:
        raise PromotionError("inventory is incomplete or not absent")
    cursor=None; previous=delete["body_complete_monotonic_ns"]; seen_cursors:set[str]=set()
    for n,page_raw in enumerate(pages,1):
        if not isinstance(page_raw,Mapping) or not isinstance(page_raw.get("raw_body_base64"),str):
            raise PromotionError("inventory page raw body is invalid")
        try: page_exact=base64.b64decode(page_raw["raw_body_base64"],validate=True)
        except (binascii.Error,ValueError): raise PromotionError("inventory page raw body is invalid") from None
        page=_provider_call(page_raw,role="inventory-page",binding=binding,raw=page_exact,ownership=delete["ownership_identity_sha256"])
        if page["delete_attempt"]!=selected_attempt:
            raise PromotionError("inventory page belongs to another delete attempt")
        if page["resource_identity_sha256"]!=delete["resource_identity_sha256"] or page["absolute_deadline_monotonic_ns"]!=delete["absolute_deadline_monotonic_ns"]:
            raise PromotionError("inventory page binding mismatch")
        sequence=_integer(page["sequence"],"inventory page sequence",minimum=1)
        expected_query={"includeClusterPods":"true","limit":"1000"}
        if cursor is not None: expected_query["cursor"]=cursor
        if (page["http_method"]!="GET" or page["request_path"]!="/pods"
                or page["request_query"]!=expected_query or page["http_status"]!=200
                or sequence!=n or page["request_cursor"]!=cursor
                or page["request_started_monotonic_ns"]<previous
                or page["body_complete_monotonic_ns"]<=previous):
            raise PromotionError("inventory page order or request mismatch")
        body=_provider_json(page_exact,"inventory page")
        if (not isinstance(body,Mapping) or set(body)!={"pods","pagination"}
                or not isinstance(body["pods"],list)
                or any(not isinstance(p,Mapping) or not isinstance(p.get("id"),str)
                       or POD_ID.fullmatch(p["id"]) is None or p["id"]==owned_id
                       for p in body["pods"])):
            raise PromotionError("inventory page does not prove owned resource absence")
        pagination=body["pagination"]
        if not isinstance(pagination,Mapping) or set(pagination)!={"nextCursor","hasNextPage"} or type(pagination["hasNextPage"]) is not bool or page["has_next_page"] is not pagination["hasNextPage"] or page["next_cursor"]!=pagination["nextCursor"]:
            raise PromotionError("inventory pagination mismatch")
        previous=page["body_complete_monotonic_ns"]
        if n<len(pages):
            if not page["has_next_page"] or not isinstance(page["next_cursor"],str) or not page["next_cursor"]: raise PromotionError("inventory cursor chain incomplete")
            if page["next_cursor"] in seen_cursors: raise PromotionError("inventory cursor repeated")
            seen_cursors.add(page["next_cursor"])
            cursor=page["next_cursor"]
        elif page["has_next_page"] or page["next_cursor"] is not None: raise PromotionError("inventory terminal page invalid")
    if cleanup_receipts["inventory_read"]["observed_monotonic_ns"] != previous:
        raise PromotionError("inventory receipt completion does not match terminal page")
    if cleanup_receipts["direct_read"]["observed_monotonic_ns"] != direct["body_complete_monotonic_ns"]:
        raise PromotionError("direct receipt completion does not match provider evidence")
    if direct["request_started_monotonic_ns"]<previous or direct["body_complete_monotonic_ns"]<=previous: raise PromotionError("provider cleanup observations are reordered")
    return artifact

def _validate_ledger(raw: object, binding: tuple[str, str, str], manifest: Mapping[str, Any], allocation_authority: Mapping[str, Any], group_hashes: Mapping[tuple[str, str, bool], str], group_bounds: Mapping[tuple[str, str, bool], tuple[int, int]], cleanup_receipts: Mapping[str, Mapping[str, Any]], records_sha: str, telemetry_sha: str) -> Mapping[str, Any]:
    keys = {"schema_version", "run_id", "attempt_id", "plan_sha256", "entries"}
    artifact = _sealed(raw, "ledger_artifact", keys)
    if artifact["schema_version"] != "episode1.private-ledger-artifact.v1":
        raise PromotionError("ledger artifact schema unsupported")
    _common(artifact, "ledger_artifact", binding)
    entries = _seq(artifact["entries"], "ledger.entries")
    entry_keys = {"schema_version", "sequence", "run_id", "attempt_id", "plan_sha256", "event", "monotonic_ns", "previous_sha256", "details", "record_sha256"}
    previous, last_ns = ZERO, None
    expected_events: list[tuple[str, dict[str, Any]]] = [("allocation-owned", {})]
    cursor = 1
    startup_retries = 0
    for block in paired_block_schedule():
        if cursor < len(entries) and isinstance(entries[cursor], Mapping) and entries[cursor].get("event") == "startup-failed":
            startup_retries += 1
            expected_events.append(("startup-failed", {"block_id": block["block_id"], "runtime": block["runtime"], "block_attempt": 1}))
            expected_events.append(("failed-start-cleanup", {"block_id": block["block_id"], "runtime": block["runtime"], "block_attempt": 1}))
            expected_events.append(("block-start", {"block_id": block["block_id"], "runtime": block["runtime"], "block_attempt": 2}))
            cursor += 3
        else:
            expected_events.append(("block-start", {"block_id": block["block_id"], "runtime": block["runtime"], "block_attempt": 1}))
            cursor += 1
        for cell_id in block["cell_order"]:
            expected_events.append(("warmup-complete", {"block_id": block["block_id"], "cell_id": cell_id}))
            cursor += 1
        for cell_id in block["cell_order"]:
            expected_events.append(("cell-complete", {"block_id": block["block_id"], "cell_id": cell_id}))
            cursor += 1
        expected_events.append(("block-stop", {"block_id": block["block_id"]}))
        cursor += 1
    expected_events += [("essential-export-complete", {}), ("delete-ack", {}), ("inventory-read", {}), ("direct-read", {}), ("capture-closed", {})]
    # The verified Episode 1 plan fixes this to one global runtime-startup retry.
    # It is intentionally not a caller-controlled manifest field.
    if startup_retries > 1:
        raise PromotionError("startup retry count exceeds the frozen global limit")
    if len(entries) != len(expected_events):
        raise PromotionError("ledger event count is incomplete or contains unknown events")
    process_ids: set[tuple[str, str]] = set()
    successful_process_identities: set[str] = set()
    failed_process_ids: set[str] = set()
    startup_attempt_ids: set[str] = set()
    active_process: str | None = None
    active_startup_attempt: str | None = None
    resource = manifest["resource_identity_sha256"]
    deadline = manifest["hard_deadline_monotonic_ns"]
    for index, (raw_entry, (expected_event, expected_identity)) in enumerate(zip(entries, expected_events, strict=True)):
        entry = _closed(raw_entry, f"ledger[{index}]", entry_keys)
        if entry["schema_version"] != "episode1.private-ledger.v2":
            raise PromotionError("ledger entry schema unsupported")
        _common(entry, f"ledger[{index}]", binding)
        if _integer(entry["sequence"], "ledger.sequence", minimum=1) != index + 1:
            raise PromotionError("ledger sequence is not contiguous")
        prior_event_ns = last_ns
        when = _integer(entry["monotonic_ns"], "ledger.monotonic_ns", minimum=1)
        if last_ns is not None and when <= last_ns:
            raise PromotionError("ledger time is not strictly increasing")
        last_ns = when
        if not manifest["start_monotonic_ns"] <= when <= deadline:
            raise PromotionError("ledger event occurred outside the original lifetime")
        if entry["previous_sha256"] != previous:
            raise PromotionError("ledger chain predecessor mismatch")
        body = dict(entry); claimed = body.pop("record_sha256")
        _hex(claimed, "ledger.record_sha256")
        if digest(body) != claimed:
            raise PromotionError("ledger entry hash mismatch")
        previous = claimed
        if entry["event"] != expected_event:
            raise PromotionError("ledger events are not in the frozen lifecycle order")
        details = entry["details"]
        if not isinstance(details, Mapping):
            raise PromotionError("ledger details must be an object")
        for name, expected_value in expected_identity.items():
            if details.get(name) != expected_value:
                raise PromotionError("ledger block/cell identity mismatch")
        if details.get("resource_identity_sha256") != resource:
            raise PromotionError("ledger resource identity mismatch")
        if expected_event == "allocation-owned":
            d = _closed(details, "allocation-owned.details", {"resource_identity_sha256", "cleanup_deadline_monotonic_ns", "immutable_allocation_sha256", "allocation_authority_sha256"})
            if d["cleanup_deadline_monotonic_ns"] != deadline:
                raise PromotionError("allocation deadline does not match original deadline")
            _hex(d["immutable_allocation_sha256"], "immutable_allocation_sha256")
            if (d["immutable_allocation_sha256"]!=allocation_authority["immutable_allocation_sha256"]
                    or d["allocation_authority_sha256"]!=allocation_authority["artifact_sha256"]):
                raise PromotionError("allocation ledger does not bind sanitized authority")
        elif expected_event == "block-start":
            d = _closed(details, "block-start.details", {"resource_identity_sha256", "block_id", "runtime", "block_attempt", "startup_attempt_id_sha256", "process_id_sha256", "process_start_identity_sha256", "image_digest"})
            _integer(d["block_attempt"], "block_attempt", minimum=1)
            startup_attempt = _hex(d["startup_attempt_id_sha256"], "startup_attempt_id_sha256")
            expected_startup_attempt = hashlib.sha256(
                f"{d['block_id']}-attempt-{d['block_attempt']}".encode()
            ).hexdigest()
            process = (_hex(d["process_id_sha256"], "process_id_sha256"), _hex(d["process_start_identity_sha256"], "process_start_identity_sha256"))
            if (startup_attempt != expected_startup_attempt
                    or startup_attempt in startup_attempt_ids or process in process_ids
                    or digest({"process_id_sha256": process[0], "process_start_identity_sha256": process[1]}) in failed_process_ids
                    or d["image_digest"] != manifest["image_digest"]):
                raise PromotionError("startup attempt/process is reused or image is unbound")
            startup_attempt_ids.add(startup_attempt)
            process_ids.add(process)
            active_startup_attempt = startup_attempt
            active_process = digest({"process_id_sha256": process[0], "process_start_identity_sha256": process[1]})
            successful_process_identities.add(active_process)
        elif expected_event == "startup-failed":
            d = _closed(details, "startup-failed.details", {"resource_identity_sha256", "block_id", "runtime", "block_attempt", "startup_attempt_id_sha256", "process_identity_sha256", "failure_stage", "warmup_records", "measured_records"})
            startup_attempt = _hex(d["startup_attempt_id_sha256"], "startup_attempt_id_sha256")
            process_identity = _hex(d["process_identity_sha256"], "process_identity_sha256")
            expected_startup_attempt = hashlib.sha256(
                f"{d['block_id']}-attempt-{d['block_attempt']}".encode()
            ).hexdigest()
            if (
                active_startup_attempt is not None or active_process is not None
                or startup_attempt != expected_startup_attempt
                or startup_attempt in startup_attempt_ids
                or process_identity in failed_process_ids
                or process_identity in successful_process_identities
                or d["failure_stage"] not in {"runtime_start", "readiness_probe"}
                or _integer(d["warmup_records"], "startup-failed.warmup_records") != 0
                or _integer(d["measured_records"], "startup-failed.measured_records") != 0
            ):
                raise PromotionError("failed startup evidence is invalid or contains traffic")
            startup_attempt_ids.add(startup_attempt)
            failed_process_ids.add(process_identity)
            active_startup_attempt = startup_attempt
            active_process = process_identity
        elif expected_event == "failed-start-cleanup":
            d = _closed(details, "failed-start-cleanup.details", {"resource_identity_sha256", "block_id", "runtime", "block_attempt", "startup_attempt_id_sha256", "process_identity_sha256", "descendants_absent", "gpu_memory_recovered"})
            if d["startup_attempt_id_sha256"] != active_startup_attempt or d["process_identity_sha256"] != active_process or d["descendants_absent"] is not True or d["gpu_memory_recovered"] is not True:
                raise PromotionError("failed startup cleanup did not restore process/GPU isolation")
            active_startup_attempt = None
            active_process = None
        elif expected_event in {"warmup-complete", "cell-complete"}:
            d = _closed(details, f"{expected_event}.details", {"resource_identity_sha256", "block_id", "cell_id", "scheduled", "failed", "records_sha256", "startup_attempt_id_sha256", "process_identity_sha256"})
            warmup = expected_event == "warmup-complete"
            key = (d["block_id"], d["cell_id"], warmup)
            expected_count = next(cell for cell in CELLS if cell["id"] == d["cell_id"])["warmups" if warmup else "requests"]
            record_start, record_end = group_bounds[key]
            if (
                _integer(d["scheduled"], "cell.scheduled") != expected_count
                or _integer(d["failed"], "cell.failed") != 0
                or d["records_sha256"] != group_hashes[key]
                or d["startup_attempt_id_sha256"] != active_startup_attempt
                or d["process_identity_sha256"] != active_process
                or (prior_event_ns is not None and record_start < prior_event_ns)
                or record_end > when
            ):
                raise PromotionError("ledger cell receipt disagrees with record evidence")
        elif expected_event == "block-stop":
            d = _closed(details, "block-stop.details", {"resource_identity_sha256", "block_id", "startup_attempt_id_sha256", "process_identity_sha256", "descendants_absent", "gpu_memory_recovered"})
            if d["startup_attempt_id_sha256"] != active_startup_attempt or d["process_identity_sha256"] != active_process or d["descendants_absent"] is not True or d["gpu_memory_recovered"] is not True:
                raise PromotionError("block isolation proof failed")
            active_startup_attempt = None
            active_process = None
        elif expected_event == "essential-export-complete":
            d = _closed(details, "export.details", {"resource_identity_sha256", "records_sha256", "telemetry_sha256"})
            if d["records_sha256"] != records_sha or d["telemetry_sha256"] != telemetry_sha:
                raise PromotionError("export receipt does not bind captured artifacts")
        elif expected_event == "delete-ack":
            d = _closed(details, "delete.details", {"resource_identity_sha256", "provider_receipt_sha256", "delete_attempt"})
            if d["provider_receipt_sha256"] != cleanup_receipts["delete_ack"]["receipt_sha256"] or when != cleanup_receipts["delete_ack"]["observed_monotonic_ns"] or d["delete_attempt"]!=cleanup_receipts["delete_ack"]["delete_attempt"]:
                raise PromotionError("delete ledger event does not bind its provider receipt")
        elif expected_event == "inventory-read":
            d = _closed(details, "inventory.details", {"resource_identity_sha256", "provider_receipt_sha256", "complete", "resource_absent", "delete_attempt"})
            receipt = cleanup_receipts["inventory_read"]
            if d["provider_receipt_sha256"] != receipt["receipt_sha256"] or when != receipt["observed_monotonic_ns"] or d["complete"] is not receipt["complete"] or d["resource_absent"] is not receipt["resource_absent"] or d["delete_attempt"]!=receipt["delete_attempt"]:
                raise PromotionError("fresh complete inventory does not prove absence")
        elif expected_event == "direct-read":
            d = _closed(details, "direct.details", {"resource_identity_sha256", "provider_receipt_sha256", "status", "delete_attempt"})
            receipt = cleanup_receipts["direct_read"]
            if d["provider_receipt_sha256"] != receipt["receipt_sha256"] or when != receipt["observed_monotonic_ns"] or d["status"] != receipt["status"] or d["delete_attempt"]!=receipt["delete_attempt"]:
                raise PromotionError("direct lookup does not prove deletion")
        elif expected_event == "capture-closed":
            _closed(details, "capture-closed.details", {"resource_identity_sha256"})
    return artifact


def _validate_settlement(raw: object, binding: tuple[str, str, str]) -> Mapping[str, Any]:
    keys = {"schema_version", "run_id", "attempt_id", "plan_sha256", "status", "observed_total_usd", "reason", "billing_source_sha256"}
    value = _sealed(raw, "settlement", keys)
    if value["schema_version"] != "episode1.cost-settlement.v1":
        raise PromotionError("settlement schema unsupported")
    _common(value, "settlement", binding)
    if value["status"] == "settled":
        if value["reason"] is not None:
            raise PromotionError("settled cost cannot have an unavailable reason")
        _hex(value["billing_source_sha256"], "settlement.billing_source_sha256")
        try:
            amount = Decimal(value["observed_total_usd"])
        except (InvalidOperation, TypeError) as exc:
            raise PromotionError("settled cost must be a decimal string") from exc
        if not isinstance(value["observed_total_usd"], str) or not amount.is_finite() or amount < 0 or format(amount, "f") != value["observed_total_usd"]:
            raise PromotionError("settled cost must be a canonical nonnegative decimal")
    elif value["status"] == "provisional":
        if value["observed_total_usd"] is not None or value["billing_source_sha256"] is not None or value["reason"] not in {"pending_provider_settlement", "provider_billing_unavailable"}:
            raise PromotionError("provisional cost must remain null with a fixed reason")
    else:
        raise PromotionError("settlement status invalid")
    return value


def promote_private_evidence(*, plan: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Validate all private artifacts and return a closed private promotion result."""
    try:
        verify_execution_candidate(plan)
    except (TypeError, ValueError) as exc:
        raise PromotionError("execution plan is invalid") from exc
    if plan.get("execution_ready") is not True:
        raise PromotionError("only an execution-ready plan can be promoted")
    root = _closed(bundle, "bundle", {"manifest", "allocation_authority", "sources", "approval", "records", "telemetry", "cleanup", "provider_artifacts", "ledger", "settlement"})
    manifest, binding = _validate_manifest(plan, root["manifest"])
    allocation_authority = _validate_allocation_authority(plan, root["allocation_authority"], binding, manifest)
    sources = _validate_sources(plan, root["sources"], binding)
    approval = _validate_approval(plan, root["approval"], binding)
    records_artifact, records, group_hashes, group_bounds = _validate_records(plan, root["records"], binding)
    telemetry = _validate_telemetry(root["telemetry"], binding, group_bounds)
    cleanup, cleanup_receipts = _validate_cleanup(root["cleanup"], binding, manifest)
    _validate_provider_artifacts(root["provider_artifacts"], binding, cleanup_receipts, manifest)
    ledger = _validate_ledger(root["ledger"], binding, manifest, allocation_authority, group_hashes, group_bounds, cleanup_receipts, records_artifact["artifact_sha256"], telemetry["artifact_sha256"])
    settlement = _validate_settlement(root["settlement"], binding)
    if (
        manifest["sources_sha256"] != sources["artifact_sha256"]
        or manifest["records_sha256"] != records_artifact["artifact_sha256"]
        or manifest["telemetry_sha256"] != telemetry["artifact_sha256"]
        or manifest["cleanup_sha256"] != cleanup["artifact_sha256"]
        or manifest["approval_sha256"] != approval["artifact_sha256"]
        or manifest["ledger_sha256"] != ledger["artifact_sha256"]
        or manifest["settlement_sha256"] != settlement["artifact_sha256"]
    ):
        raise PromotionError("manifest artifact inventory mismatch")
    promoted: list[dict[str, Any]] = []
    for record in records:
        item = {key: value for key, value in record.items() if key != "derived"}
        item["evidence_class"] = "provider_measurement"
        validate_observation(item)
        promoted.append(item)
    return {
        "schema_version": "episode1.private-promotion.v1",
        "classification": "private_provider_measurement",
        "run_id": binding[0],
        "attempt_id": binding[1],
        "plan_sha256": binding[2],
        "manifest_sha256": manifest["artifact_sha256"],
        "record_count": len(promoted),
        "records": promoted,
        "telemetry_status": "validated_with_explicit_unavailability",
        "cost_status": settlement["status"],
    }
