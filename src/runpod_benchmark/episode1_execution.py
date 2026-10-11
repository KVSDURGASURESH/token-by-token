"""Fail-closed Episode 1 live-plan compiler and approval contract.

This module is pure: it performs no provider, network, SSH, container, or GPU
operations.  A blocked candidate is useful review evidence, but only a fully
bound candidate can produce approval phrases or enter the orchestrator.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
from typing import Any

from .episode1 import RUNTIMES, canonical_json, paired_block_schedule, verify_protocol


EXECUTION_SCHEMA_VERSION = "episode1.execution.v1"
INPUT_SCHEMA_VERSION = "episode1.execution-input.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
_GIT_OBJECT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_MAX_QUOTE_AGE = timedelta(minutes=15)
_PHASE_SECONDS = {
    "provision_and_staging": 20 * 60,
    "six_runtime_startups": 24 * 60,
    "six_warmup_sets": 18 * 60,
    "six_measured_blocks": 42 * 60,
    "export_and_verified_deletion": 8 * 60,
    "one_startup_retry_contingency": 8 * 60,
}
_COST_CATEGORIES = {
    "gpu", "container_storage", "volume_storage", "network_volume",
    "public_ip", "startup", "egress", "tax", "other",
}


class Episode1ExecutionError(ValueError):
    """Raised when a candidate or approval violates the closed contract."""


def _closed(value: object, path: str, required: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Episode1ExecutionError(f"{path} must be an object")
    keys = set(value)
    missing, extra = required - keys, keys - required
    if missing or extra:
        raise Episode1ExecutionError(
            f"{path} has invalid fields; missing={sorted(missing)} extra={sorted(extra)}"
        )
    return value


def _digest(value: object, path: str, *, oci: bool = False) -> str:
    if not isinstance(value, str) or (not (_OCI_DIGEST if oci else _SHA256).fullmatch(value)):
        kind = "OCI sha256 digest" if oci else "SHA-256 digest"
        raise Episode1ExecutionError(f"{path} must be a lowercase {kind}")
    return value


def _git_object(value: object, path: str) -> str:
    if not isinstance(value, str) or _GIT_OBJECT.fullmatch(value) is None:
        raise Episode1ExecutionError(f"{path} must be a lowercase 40- or 64-hex Git object id")
    return value


def _timestamp(value: object, path: str, *, nullable: bool = True) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Episode1ExecutionError(f"{path} must be a UTC RFC3339 timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Episode1ExecutionError(f"{path} must be a UTC RFC3339 timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise Episode1ExecutionError(f"{path} must use UTC")
    return parsed


def _decimal(value: object, path: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise Episode1ExecutionError(f"{path} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise Episode1ExecutionError(f"{path} must be a decimal string") from exc
    if not parsed.is_finite() or (positive and parsed <= 0) or (not positive and parsed < 0):
        raise Episode1ExecutionError(f"{path} is outside the allowed range")
    if format(parsed, "f") != value:
        raise Episode1ExecutionError(f"{path} must use canonical decimal notation")
    return parsed


def _bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise Episode1ExecutionError(f"{path} must be boolean")
    return value


def _integer(value: object, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise Episode1ExecutionError(f"{path} must be an integer in [{minimum}, {maximum}]")
    return value


def _canonical_money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_UP), "f")


def _validate_inputs(value: Mapping[str, Any]) -> tuple[list[str], Decimal]:
    root = _closed(
        value,
        "inputs",
        {
            "schema_version", "candidate_id", "protocol_sha256", "material_sha256",
            "source_commit", "provider", "allocation", "access", "runtime_builds", "capture",
            "benchmark_standard", "phase_budgets", "cost_components", "budget", "guard",
        },
    )
    if root["schema_version"] != INPUT_SCHEMA_VERSION:
        raise Episode1ExecutionError("inputs.schema_version is unsupported")
    if not isinstance(root["candidate_id"], str) or not _OPAQUE.fullmatch(root["candidate_id"]):
        raise Episode1ExecutionError("inputs.candidate_id must be opaque")
    _digest(root["protocol_sha256"], "inputs.protocol_sha256")
    _digest(root["material_sha256"], "inputs.material_sha256")
    _git_object(root["source_commit"], "inputs.source_commit")

    provider = _closed(
        root["provider"], "inputs.provider",
        {
            "api_contract_sha256", "observed_at", "expires_at", "offer_reference_hash",
            "stock_verified", "permanent_delete_supported", "delete_deadline_readback_supported",
            "inventory_read_supported", "direct_lookup_supported", "ambiguous_create_retry_forbidden",
            "recover_by_exact_name_supported", "account_balance_usd",
            "account_evidence_sha256", "auto_pay_disabled", "auto_pay_evidence_sha256",
            "unrelated_resources_evidence_sha256",
        },
    )
    for field in ("api_contract_sha256", "offer_reference_hash"):
        if provider[field] is not None:
            _digest(provider[field], f"inputs.provider.{field}")
    for field in (
        "stock_verified", "permanent_delete_supported", "delete_deadline_readback_supported",
        "inventory_read_supported", "direct_lookup_supported", "ambiguous_create_retry_forbidden",
        "recover_by_exact_name_supported",
    ):
        _bool(provider[field], f"inputs.provider.{field}")
    if provider["account_balance_usd"] is not None:
        _decimal(provider["account_balance_usd"], "inputs.provider.account_balance_usd")
    for field in (
        "account_evidence_sha256", "auto_pay_evidence_sha256",
        "unrelated_resources_evidence_sha256",
    ):
        if provider[field] is not None:
            _digest(provider[field], f"inputs.provider.{field}")
    _bool(provider["auto_pay_disabled"], "inputs.provider.auto_pay_disabled")
    observed = _timestamp(provider["observed_at"], "inputs.provider.observed_at")
    expires = _timestamp(provider["expires_at"], "inputs.provider.expires_at")
    if observed is not None and expires is not None and expires <= observed:
        raise Episode1ExecutionError("provider observation expiry must follow observation time")
    if observed is not None and expires is not None and expires - observed > _MAX_QUOTE_AGE:
        raise Episode1ExecutionError("provider observation window cannot exceed 15 minutes")

    allocation = _closed(
        root["allocation"], "inputs.allocation",
        {
            "gpu", "gpu_count", "data_center_id", "cloud_type", "container_disk_gb",
            "volume_gb", "volume_mount_path", "single_allocation", "isolation_mode",
            "isolation_verified",
        },
    )
    if allocation["gpu"] != "NVIDIA H100 80GB HBM3":
        raise Episode1ExecutionError("inputs.allocation must bind one H100 80GB HBM3")
    _integer(allocation["gpu_count"], "inputs.allocation.gpu_count", 1, 1)
    if not isinstance(allocation["data_center_id"], str) or not allocation["data_center_id"]:
        raise Episode1ExecutionError("inputs.allocation.data_center_id is required")
    if allocation["cloud_type"] != "SECURE":
        raise Episode1ExecutionError("inputs.allocation.cloud_type must be SECURE")
    _integer(allocation["container_disk_gb"], "inputs.allocation.container_disk_gb", 1, 4096)
    _integer(allocation["volume_gb"], "inputs.allocation.volume_gb", 0, 4096)
    if not isinstance(allocation["volume_mount_path"], str):
        raise Episode1ExecutionError("inputs.allocation.volume_mount_path must be a string")
    if allocation["volume_gb"] == 0 and allocation["volume_mount_path"] != "":
        raise Episode1ExecutionError("zero volume size requires an empty mount path")
    if allocation["single_allocation"] is not True:
        raise Episode1ExecutionError("Episode 1 requires one allocation for all six blocks")
    if allocation["isolation_mode"] not in {"oci-sequential", "host-env-sequential"}:
        raise Episode1ExecutionError("inputs.allocation.isolation_mode is unsupported")
    _bool(allocation["isolation_verified"], "inputs.allocation.isolation_verified")

    access = _closed(
        root["access"], "inputs.access",
        {
            "mode", "public_ip_supported", "ssh_port", "public_inference_ports",
            "image_starts_sshd", "strict_host_key_checking",
            "post_create_host_key_verification_required",
        },
    )
    if access["mode"] != "full_ssh_public_ip":
        raise Episode1ExecutionError("Episode 1 access must use plan-bound full SSH on TCP 22")
    _integer(access["ssh_port"], "inputs.access.ssh_port", 22, 22)
    if access["public_inference_ports"] != []:
        raise Episode1ExecutionError("public inference ports are forbidden")
    for field in (
        "public_ip_supported", "image_starts_sshd", "strict_host_key_checking",
        "post_create_host_key_verification_required",
    ):
        _bool(access[field], f"inputs.access.{field}")

    builds = root["runtime_builds"]
    if not isinstance(builds, list) or len(builds) != 2:
        raise Episode1ExecutionError("inputs.runtime_builds must contain exactly two runtimes")
    seen: set[str] = set()
    for index, raw in enumerate(builds):
        build = _closed(
            raw, f"inputs.runtime_builds[{index}]",
            {
                "runtime", "build_spec_sha256", "dependency_lock_sha256", "launcher_sha256",
                "build_attestation_sha256", "derived_image_digest", "post_create_gpu_check_required",
                "post_create_effective_flags_check_required",
            },
        )
        if build["runtime"] not in RUNTIMES or build["runtime"] in seen:
            raise Episode1ExecutionError("runtime builds must bind each frozen runtime once")
        seen.add(build["runtime"])
        for field in ("build_spec_sha256", "dependency_lock_sha256", "launcher_sha256", "build_attestation_sha256"):
            _digest(build[field], f"inputs.runtime_builds[{index}].{field}")
        if build["derived_image_digest"] is not None:
            _digest(build["derived_image_digest"], f"inputs.runtime_builds[{index}].derived_image_digest", oci=True)
        if build["post_create_gpu_check_required"] is not True:
            raise Episode1ExecutionError("each runtime must require a post-create GPU check")
        if build["post_create_effective_flags_check_required"] is not True:
            raise Episode1ExecutionError("each runtime must require a post-create effective-flags check")
    if seen != set(RUNTIMES):
        raise Episode1ExecutionError("runtime builds do not match the frozen runtime pair")
    built = {item["derived_image_digest"] for item in builds if item["derived_image_digest"] is not None}
    if len(built) > 1:
        raise Episode1ExecutionError("both runtime records must bind the same one-image digest")

    capture = _closed(
        root["capture"], "inputs.capture",
        {"collector_sha256", "private_schema_sha256", "telemetry_cadence_seconds"},
    )
    _digest(capture["collector_sha256"], "inputs.capture.collector_sha256")
    _digest(capture["private_schema_sha256"], "inputs.capture.private_schema_sha256")
    _integer(capture["telemetry_cadence_seconds"], "inputs.capture.telemetry_cadence_seconds", 1, 60)

    standard = _closed(
        root["benchmark_standard"], "inputs.benchmark_standard",
        {"serving", "quality", "application_gate"},
    )
    serving = _closed(
        standard["serving"], "inputs.benchmark_standard.serving",
        {
            "harness", "harness_version", "harness_source_commit", "adapter_sha256",
            "dataset", "dataset_revision", "dataset_sha256", "selection_manifest_sha256",
            "seed", "request_count", "output_tokens", "arrival_policy",
        },
    )
    if serving["harness"] != "sglang.bench_serving" or serving["harness_version"] != "0.5.20":
        raise Episode1ExecutionError("serving benchmark must use frozen sglang.bench_serving 0.5.20")
    if serving["dataset"] != "ShareGPT_V3_unfiltered_cleaned_split.json":
        raise Episode1ExecutionError("serving benchmark must use the frozen ShareGPT workload")
    _git_object(serving["harness_source_commit"], "inputs.benchmark_standard.serving.harness_source_commit")
    _git_object(serving["dataset_revision"], "inputs.benchmark_standard.serving.dataset_revision")
    for field in ("adapter_sha256", "dataset_sha256", "selection_manifest_sha256"):
        _digest(serving[field], f"inputs.benchmark_standard.serving.{field}")
    _integer(serving["seed"], "inputs.benchmark_standard.serving.seed", 20260923, 20260923)
    _integer(serving["request_count"], "inputs.benchmark_standard.serving.request_count", 32, 100000)
    _integer(serving["output_tokens"], "inputs.benchmark_standard.serving.output_tokens", 128, 128)
    if serving["arrival_policy"] != "infinite":
        raise Episode1ExecutionError("serving benchmark arrival policy must be infinite")

    quality = _closed(
        standard["quality"], "inputs.benchmark_standard.quality",
        {
            "harness", "harness_source_commit", "adapter_sha256", "task", "task_version",
            "dataset_revision", "dataset_sha256", "task_config_sha256", "num_fewshot",
            "filter", "sample_count", "do_sample", "temperature",
        },
    )
    if quality["harness"] != "lm-evaluation-harness" or quality["task"] != "gsm8k":
        raise Episode1ExecutionError("quality benchmark must use lm-evaluation-harness gsm8k")
    if quality["task_version"] != "3.0" or quality["filter"] != "strict-match":
        raise Episode1ExecutionError("GSM8K task version and filter must match the frozen contract")
    for field in ("harness_source_commit", "dataset_revision"):
        _git_object(quality[field], f"inputs.benchmark_standard.quality.{field}")
    for field in ("adapter_sha256", "dataset_sha256", "task_config_sha256"):
        _digest(quality[field], f"inputs.benchmark_standard.quality.{field}")
    _integer(quality["num_fewshot"], "inputs.benchmark_standard.quality.num_fewshot", 5, 5)
    _integer(quality["sample_count"], "inputs.benchmark_standard.quality.sample_count", 1319, 1319)
    if quality["do_sample"] is not False or quality["temperature"] != 0:
        raise Episode1ExecutionError("GSM8K must use deterministic decoding")

    application = _closed(
        standard["application_gate"], "inputs.benchmark_standard.application_gate",
        {"name", "corpus_sha256", "evaluator_sha256", "standard_benchmark"},
    )
    if application["name"] != "episode1-json-extraction-24" or application["standard_benchmark"] is not False:
        raise Episode1ExecutionError("application gate must remain explicitly nonstandard")
    _digest(application["corpus_sha256"], "inputs.benchmark_standard.application_gate.corpus_sha256")
    _digest(application["evaluator_sha256"], "inputs.benchmark_standard.application_gate.evaluator_sha256")

    phases = _closed(root["phase_budgets"], "inputs.phase_budgets", set(_PHASE_SECONDS))
    for field, expected in _PHASE_SECONDS.items():
        _integer(phases[field], f"inputs.phase_budgets.{field}", expected, expected)

    costs = root["cost_components"]
    if not isinstance(costs, list) or len(costs) != len(_COST_CATEGORIES):
        raise Episode1ExecutionError("inputs.cost_components must cover every charge category once")
    cost_by_category: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(costs):
        component = _closed(
            raw, f"inputs.cost_components[{index}]",
            {
                "category", "status", "amount_usd", "billing_unit", "rounding_seconds",
                "included_in", "source_sha256", "observed_at", "expires_at",
            },
        )
        category = component["category"]
        if category not in _COST_CATEGORIES or category in cost_by_category:
            raise Episode1ExecutionError("cost component categories must be unique and complete")
        if component["status"] not in {"priced", "included", "verified_not_applicable", "unknown"}:
            raise Episode1ExecutionError("cost component status is invalid")
        if component["billing_unit"] not in {"per_hour", "fixed", "included", "not_applicable", "unknown"}:
            raise Episode1ExecutionError("cost component billing unit is invalid")
        amount = component["amount_usd"]
        if amount is not None:
            _decimal(amount, f"inputs.cost_components[{index}].amount_usd")
        if component["source_sha256"] is not None:
            _digest(component["source_sha256"], f"inputs.cost_components[{index}].source_sha256")
        cost_observed = _timestamp(component["observed_at"], f"inputs.cost_components[{index}].observed_at")
        cost_expires = _timestamp(component["expires_at"], f"inputs.cost_components[{index}].expires_at")
        if cost_observed is not None and cost_expires is not None:
            if cost_expires <= cost_observed or cost_expires - cost_observed > _MAX_QUOTE_AGE:
                raise Episode1ExecutionError("cost observation windows must be positive and at most 15 minutes")
        _integer(component["rounding_seconds"], f"inputs.cost_components[{index}].rounding_seconds", 1, 3600)
        status = component["status"]
        if status == "priced":
            if amount is None or component["billing_unit"] not in {"per_hour", "fixed"} or component["included_in"] is not None:
                raise Episode1ExecutionError("priced cost components require an amount and direct billing unit")
        elif status == "included":
            if amount != "0.000000" or component["billing_unit"] != "included" or component["included_in"] not in _COST_CATEGORIES:
                raise Episode1ExecutionError("included cost components must identify their priced parent")
        elif status == "verified_not_applicable":
            if amount != "0.000000" or component["billing_unit"] != "not_applicable" or component["included_in"] is not None:
                raise Episode1ExecutionError("not-applicable cost components must be explicit zeroes")
        else:
            if amount is not None or component["billing_unit"] != "unknown" or component["included_in"] is not None:
                raise Episode1ExecutionError("unknown cost components cannot carry invented prices")
        cost_by_category[str(category)] = component
    if set(cost_by_category) != _COST_CATEGORIES:
        raise Episode1ExecutionError("cost component categories are incomplete")
    for category, component in cost_by_category.items():
        parent = component["included_in"]
        if parent is not None and (parent == category or cost_by_category[parent]["status"] != "priced"):
            raise Episode1ExecutionError("included cost component must reference a priced parent")

    budget = _closed(
        root["budget"], "inputs.budget",
        {
            "maximum_spend_usd", "minimum_final_balance_usd", "maximum_lifetime_seconds",
            "startup_retry_limit", "soft_stop_fraction", "teardown_fraction",
            "delete_verification_seconds", "create_recovery_seconds", "export_seconds",
        },
    )
    maximum = _decimal(budget["maximum_spend_usd"], "inputs.budget.maximum_spend_usd", positive=True)
    reserve = _decimal(budget["minimum_final_balance_usd"], "inputs.budget.minimum_final_balance_usd")
    lifetime = _integer(budget["maximum_lifetime_seconds"], "inputs.budget.maximum_lifetime_seconds", 1, 7200)
    if lifetime != sum(_PHASE_SECONDS.values()):
        raise Episode1ExecutionError("maximum lifetime must equal the frozen 120-minute phase ledger")
    _integer(budget["startup_retry_limit"], "inputs.budget.startup_retry_limit", 1, 1)
    if budget["soft_stop_fraction"] != "0.75" or budget["teardown_fraction"] != "0.85":
        raise Episode1ExecutionError("Episode 1 thresholds must be exactly 0.75 and 0.85")
    for field in ("delete_verification_seconds", "create_recovery_seconds", "export_seconds"):
        _integer(budget[field], f"inputs.budget.{field}", 1, lifetime)
    if budget["create_recovery_seconds"] > phases["provision_and_staging"]:
        raise Episode1ExecutionError("create recovery must fit within provision and staging")
    if budget["delete_verification_seconds"] + budget["export_seconds"] > phases["export_and_verified_deletion"]:
        raise Episode1ExecutionError("export and deletion sub-budgets exceed their frozen phase")
    if provider["account_balance_usd"] is not None:
        balance = _decimal(provider["account_balance_usd"], "inputs.provider.account_balance_usd")
        if balance - maximum < reserve:
            raise Episode1ExecutionError("maximum spend would violate the minimum final balance")

    guard = _closed(
        root["guard"], "inputs.guard",
        {"mode", "provider_deadline_seconds", "local_watchdog_plan_sha256"},
    )
    if guard["mode"] not in {"provider_enforced", "local_watchdog_fallback"}:
        raise Episode1ExecutionError("inputs.guard.mode is unsupported")
    if guard["provider_deadline_seconds"] is not None:
        _integer(guard["provider_deadline_seconds"], "inputs.guard.provider_deadline_seconds", 1, lifetime)
    if guard["local_watchdog_plan_sha256"] is not None:
        _digest(guard["local_watchdog_plan_sha256"], "inputs.guard.local_watchdog_plan_sha256")

    # The phase ledger is exclusive and already includes create recovery,
    # export, and verified deletion. Costs may round the approved 120-minute
    # ceiling, but may never silently extend it with another cleanup horizon.
    envelope = Decimal("0")
    for component in cost_by_category.values():
        if component["status"] != "priced":
            continue
        amount = _decimal(component["amount_usd"], "cost amount")
        if component["billing_unit"] == "fixed":
            envelope += amount
        else:
            rounding = int(component["rounding_seconds"])
            rounded = ((lifetime + rounding - 1) // rounding) * rounding
            envelope += amount * Decimal(rounded) / Decimal(3600)
    if envelope > maximum:
        raise Episode1ExecutionError("conservative charge envelope exceeds maximum spend")
    return sorted(seen), envelope


def _derive_blockers(inputs: Mapping[str, Any]) -> list[str]:
    provider = inputs["provider"]
    allocation = inputs["allocation"]
    guard = inputs["guard"]
    blockers: list[str] = []
    if provider["api_contract_sha256"] is None:
        blockers.append("provider_api_contract_unverified")
    if provider["offer_reference_hash"] is None or not provider["stock_verified"]:
        blockers.append("fresh_offer_or_stock_unverified")
    if provider["observed_at"] is None or provider["expires_at"] is None:
        blockers.append("provider_observation_window_unbound")
    if provider["account_balance_usd"] is None:
        blockers.append("account_balance_unverified")
    for field in (
        "account_evidence_sha256", "auto_pay_evidence_sha256",
        "unrelated_resources_evidence_sha256",
    ):
        if provider[field] is None:
            blockers.append(f"{field}_unverified")
    if not provider["auto_pay_disabled"]:
        blockers.append("auto_pay_not_verified_disabled")
    for capability in (
        "permanent_delete_supported", "inventory_read_supported", "direct_lookup_supported",
        "ambiguous_create_retry_forbidden", "recover_by_exact_name_supported",
    ):
        if not provider[capability]:
            blockers.append(f"{capability}_unverified")
    if not allocation["isolation_verified"]:
        blockers.append("same_allocation_isolation_unverified")
    for build in inputs["runtime_builds"]:
        if build["derived_image_digest"] is None:
            blockers.append(f"{build['runtime']}_derived_image_unbuilt")
    for component in inputs["cost_components"]:
        if component["status"] == "unknown":
            blockers.append(f"{component['category']}_cost_unverified")
        elif component["source_sha256"] is None or component["observed_at"] is None or component["expires_at"] is None:
            blockers.append(f"{component['category']}_cost_evidence_unbound")
    access = inputs["access"]
    for capability in (
        "public_ip_supported", "image_starts_sshd", "strict_host_key_checking",
        "post_create_host_key_verification_required",
    ):
        if not access[capability]:
            blockers.append(f"{capability}_unverified")
    if guard["mode"] == "provider_enforced":
        if not provider["delete_deadline_readback_supported"] or guard["provider_deadline_seconds"] is None:
            blockers.append("provider_delete_deadline_unverified")
        if guard["local_watchdog_plan_sha256"] is None:
            blockers.append("independent_local_watchdog_plan_unbound")
    else:
        if guard["local_watchdog_plan_sha256"] is None:
            blockers.append("local_watchdog_plan_unbound")
        if guard["provider_deadline_seconds"] is not None:
            raise Episode1ExecutionError("local-watchdog mode cannot claim a provider deadline")
    return blockers


def compile_execution_candidate(protocol: Mapping[str, Any], inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Compile a reviewable candidate; unresolved external facts remain blockers."""

    verify_protocol(protocol)
    _, envelope = _validate_inputs(inputs)
    if inputs["protocol_sha256"] != protocol["protocol_sha256"]:
        raise Episode1ExecutionError("inputs.protocol_sha256 does not match the protocol")
    blockers = _derive_blockers(inputs)

    plan: dict[str, Any] = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "classification": "provider_execution_candidate",
        "execution_ready": not blockers,
        "candidate_id": inputs["candidate_id"],
        "protocol_sha256": protocol["protocol_sha256"],
        "material_sha256": inputs["material_sha256"],
        "source_commit": inputs["source_commit"],
        "single_allocation_required": True,
        "blocks": paired_block_schedule(),
        "provider": dict(inputs["provider"]),
        "allocation": dict(inputs["allocation"]),
        "access": dict(inputs["access"]),
        "runtime_builds": [dict(item) for item in inputs["runtime_builds"]],
        "capture": dict(inputs["capture"]),
        "benchmark_standard": json.loads(canonical_json(inputs["benchmark_standard"])),
        "phase_budgets": dict(inputs["phase_budgets"]),
        "cost_components": [dict(item) for item in inputs["cost_components"]],
        "budget": dict(inputs["budget"]),
        "guard": dict(inputs["guard"]),
        "conservative_maximum_charge_usd": _canonical_money(envelope),
        "unresolved_blockers": blockers,
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json(plan).encode()).hexdigest()
    return plan


def verify_execution_candidate(plan: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "classification", "execution_ready", "candidate_id", "protocol_sha256",
        "material_sha256", "source_commit", "single_allocation_required", "blocks", "provider",
        "allocation", "access", "runtime_builds", "capture", "budget", "guard",
        "benchmark_standard", "phase_budgets", "cost_components",
        "conservative_maximum_charge_usd", "unresolved_blockers", "plan_sha256",
    }
    root = _closed(plan, "plan", required)
    if root["schema_version"] != EXECUTION_SCHEMA_VERSION or root["classification"] != "provider_execution_candidate":
        raise Episode1ExecutionError("plan identity is invalid")
    if root["blocks"] != paired_block_schedule() or root["single_allocation_required"] is not True:
        raise Episode1ExecutionError("plan does not bind the frozen six-block schedule")
    body = dict(root)
    claimed = body.pop("plan_sha256")
    if claimed != hashlib.sha256(canonical_json(body).encode()).hexdigest():
        raise Episode1ExecutionError("plan digest mismatch")
    embedded_inputs = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "candidate_id": root["candidate_id"],
        "protocol_sha256": root["protocol_sha256"],
        "material_sha256": root["material_sha256"],
        "source_commit": root["source_commit"],
        "provider": root["provider"],
        "allocation": root["allocation"],
        "access": root["access"],
        "runtime_builds": root["runtime_builds"],
        "capture": root["capture"],
        "benchmark_standard": root["benchmark_standard"],
        "phase_budgets": root["phase_budgets"],
        "cost_components": root["cost_components"],
        "budget": root["budget"],
        "guard": root["guard"],
    }
    _, envelope = _validate_inputs(embedded_inputs)
    blockers = root["unresolved_blockers"]
    if not isinstance(blockers, list) or any(not isinstance(item, str) or not item for item in blockers):
        raise Episode1ExecutionError("plan blockers are invalid")
    if root["execution_ready"] is not (len(blockers) == 0):
        raise Episode1ExecutionError("execution readiness disagrees with blockers")
    if blockers != _derive_blockers(embedded_inputs):
        raise Episode1ExecutionError("plan blockers do not match embedded facts")
    if root["conservative_maximum_charge_usd"] != _canonical_money(envelope):
        raise Episode1ExecutionError("plan charge envelope does not match embedded costs")


def verify_fresh_for_create(plan: Mapping[str, Any], *, now: datetime) -> None:
    """Apply the time-dependent provider quote gate immediately before create."""

    verify_execution_candidate(plan)
    if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise Episode1ExecutionError("create-gate time must be timezone-aware UTC")
    observed = _timestamp(plan["provider"]["observed_at"], "plan.provider.observed_at", nullable=False)
    expires = _timestamp(plan["provider"]["expires_at"], "plan.provider.expires_at", nullable=False)
    assert observed is not None and expires is not None
    if now < observed or now >= expires:
        raise Episode1ExecutionError("provider observation is not fresh at the create gate")
    if now - observed > _MAX_QUOTE_AGE:
        raise Episode1ExecutionError("provider observation is older than 15 minutes")
    for index, component in enumerate(plan["cost_components"]):
        cost_observed = _timestamp(component["observed_at"], f"plan.cost_components[{index}].observed_at", nullable=False)
        cost_expires = _timestamp(component["expires_at"], f"plan.cost_components[{index}].expires_at", nullable=False)
        assert cost_observed is not None and cost_expires is not None
        if now < cost_observed or now >= cost_expires or now - cost_observed > _MAX_QUOTE_AGE:
            raise Episode1ExecutionError("cost observation is not fresh at the create gate")


def spend_approval_phrase(plan: Mapping[str, Any]) -> str:
    verify_execution_candidate(plan)
    if plan["execution_ready"] is not True:
        raise Episode1ExecutionError("blocked candidates cannot produce approval phrases")
    return (
        f"APPROVE EPISODE1 {plan['plan_sha256']} "
        f"MAX USD {plan['budget']['maximum_spend_usd']}"
    )


def watchdog_risk_phrase(plan: Mapping[str, Any]) -> str | None:
    verify_execution_candidate(plan)
    if plan["execution_ready"] is not True:
        raise Episode1ExecutionError("blocked candidates cannot produce risk phrases")
    if plan["guard"]["mode"] != "local_watchdog_fallback":
        return None
    # The immutable approval receipt binds this exact response to plan_sha256
    # and local_watchdog_plan_sha256; the human-facing response stays literal.
    return "ACCEPT LOCAL-WATCHDOG RISK"


def validate_execution_approvals(
    plan: Mapping[str, Any], *, spend_approval: str, watchdog_risk_approval: str | None
) -> None:
    if spend_approval != spend_approval_phrase(plan):
        raise Episode1ExecutionError("spend approval does not exactly match the compiled plan")
    expected_risk = watchdog_risk_phrase(plan)
    if watchdog_risk_approval != expected_risk:
        raise Episode1ExecutionError("watchdog risk approval does not exactly match the compiled plan")
