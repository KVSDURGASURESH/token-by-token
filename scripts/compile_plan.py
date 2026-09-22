"""Compile a validated, deterministic, digest-bound Runpod cost plan.

This module is deliberately pure: it performs no network or provider operations.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from typing import Mapping


_CENT = Decimal("0.01")
_MAX_CANONICAL_DEPTH = 64
_MAX_LIVE_EVIDENCE_AGE = timedelta(minutes=15)
_LOCAL_GUARD_ACKNOWLEDGMENT = "ACCEPT LOCAL-WATCHDOG RISK"
_ANCILLARY_COMPONENTS = {
    "storage",
    "network_volume",
    "endpoint_public_ip",
    "egress",
    "image_pull",
    "startup",
    "other",
}


class PlanValidationError(ValueError):
    """The approval plan is malformed or differs from compiler output."""


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{path} field names must be strings")
    return value


def _shape(
    value: object,
    path: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> Mapping[str, object]:
    result = _mapping(value, path)
    allowed = required | (optional or set())
    unknown = sorted(set(result) - allowed)
    if unknown:
        raise ValueError(f"{path}: unknown field(s): {', '.join(unknown)}")
    missing = sorted(required - set(result))
    if missing:
        raise ValueError(f"{path}: missing required field(s): {', '.join(missing)}")
    return result


def _string(value: object, path: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{path} must be a non-empty string of at most {maximum} characters")
    return value


def _integer(value: object, path: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{path} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{path} must be between {minimum} and {maximum}")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{path} must be a boolean")
    return value


def _enum(value: object, path: str, allowed: set[str]) -> str:
    result = _string(value, path)
    if result not in allowed:
        raise ValueError(f"{path} must be one of: {', '.join(sorted(allowed))}")
    return result


def _hex(value: object, path: str, *, lengths: tuple[int, ...]) -> str:
    result = _string(value, path, maximum=max(lengths))
    if len(result) not in lengths or re.fullmatch(r"[0-9a-fA-F]+", result) is None:
        expected = " or ".join(str(length) for length in lengths)
        raise ValueError(f"{path} must be immutable hexadecimal text of length {expected}")
    return result


def _pinned_version(value: object, path: str) -> str:
    result = _string(value, path, maximum=128)
    if result.lower() in {"latest", "main", "master", "stable", "nightly"} or re.search(
        r"[<>=*^~,\s]", result
    ):
        raise ValueError(f"{path} must be a pinned version without tags, ranges, or wildcards")
    return result


def _timestamp(value: object, path: str) -> datetime:
    text = _string(value, path, maximum=64)
    if not text.endswith("Z"):
        raise ValueError(f"{path} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{path} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{path} must be UTC")
    return parsed


def _decimal_string(
    value: object,
    path: str,
    *,
    minimum: Decimal,
    maximum: Decimal,
    fractional_digits: int = 6,
) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{path} must be a decimal string")
    if re.fullmatch(rf"(?:0|[1-9][0-9]*)(?:\.[0-9]{{1,{fractional_digits}}})?", value) is None:
        raise ValueError(
            f"{path} must be a plain non-negative decimal string with at most "
            f"{fractional_digits} fractional digits"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{path} must be a valid decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{path} must be finite")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{path} must be between {minimum} and {maximum}")
    return parsed


def _money(value: Decimal) -> str:
    return format(value.quantize(_CENT, rounding=ROUND_HALF_UP), ".2f")


def _string_list(value: object, path: str, *, allow_empty: bool, maximum: int) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{path} must be an array")
    if not allow_empty and not value:
        raise ValueError(f"{path} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{path} must contain at most {maximum} items")
    return [_string(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _plain_json_copy(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_json_copy(item) for item in value]
    return value


def _validate_manifest(manifest: Mapping[str, object]) -> bool:
    root = _shape(
        manifest,
        "manifest",
        required={"schema_version", "planning_only", "experiment_id", "budget", "resource", "model", "runtimes", "workload"},
        optional={"execution"},
    )
    if isinstance(root["schema_version"], bool) or not isinstance(root["schema_version"], int):
        raise TypeError("manifest.schema_version must be the integer 1")
    if root["schema_version"] != 1:
        raise ValueError("manifest.schema_version must be the integer 1")
    _string(root["experiment_id"], "manifest.experiment_id", maximum=128)
    planning_only = _boolean(root["planning_only"], "manifest.planning_only")
    if planning_only and "execution" in root:
        raise ValueError("manifest.execution is forbidden when planning_only is true")
    if not planning_only and "execution" not in root:
        raise ValueError("manifest: missing required field(s): execution")

    budget = _shape(
        root["budget"],
        "manifest.budget",
        required={"max_usd", "minimum_final_balance_usd"},
    )
    _decimal_string(
        budget["max_usd"],
        "manifest.budget.max_usd",
        minimum=Decimal("0.01"),
        maximum=Decimal("10000"),
        fractional_digits=2,
    )
    _decimal_string(
        budget["minimum_final_balance_usd"],
        "manifest.budget.minimum_final_balance_usd",
        minimum=Decimal("0"),
        maximum=Decimal("1000000"),
        fractional_digits=2,
    )

    resource = _shape(
        root["resource"],
        "manifest.resource",
        required={"gpu_count", "cloud", "terminate_after_minutes"},
    )
    _integer(resource["gpu_count"], "manifest.resource.gpu_count", minimum=1, maximum=8)
    if resource["cloud"] not in {"SECURE", "COMMUNITY"}:
        raise ValueError("manifest.resource.cloud must be SECURE or COMMUNITY")
    _integer(
        resource["terminate_after_minutes"],
        "manifest.resource.terminate_after_minutes",
        minimum=1,
        maximum=10080,
    )

    model = _shape(root["model"], "manifest.model", required={"repository", "revision"})
    _string(model["repository"], "manifest.model.repository", maximum=256)
    _hex(model["revision"], "manifest.model.revision", lengths=(40, 64))

    runtimes = root["runtimes"]
    if not isinstance(runtimes, list):
        raise TypeError("manifest.runtimes must be an array")
    if not runtimes:
        raise ValueError("manifest.runtimes must not be empty")
    if len(runtimes) > 16:
        raise ValueError("manifest.runtimes must contain at most 16 items")
    for index, raw_runtime in enumerate(runtimes):
        path = f"manifest.runtimes[{index}]"
        runtime = _shape(raw_runtime, path, required={"id", "version", "fallbacks"})
        _string(runtime["id"], f"{path}.id", maximum=64)
        _string(runtime["version"], f"{path}.version", maximum=128)
        _string_list(runtime["fallbacks"], f"{path}.fallbacks", allow_empty=True, maximum=16)

    workload = _shape(root["workload"], "manifest.workload", required={"cells"})
    cells = workload["cells"]
    if not isinstance(cells, list):
        raise TypeError("manifest.workload.cells must be an array")
    if not cells:
        raise ValueError("manifest.workload.cells must not be empty")
    if len(cells) > 1000:
        raise ValueError("manifest.workload.cells must contain at most 1000 items")
    for index, raw_cell in enumerate(cells):
        path = f"manifest.workload.cells[{index}]"
        cell = _shape(
            raw_cell,
            path,
            required={"input_tokens", "output_tokens", "concurrency", "requests"},
            optional={"repetitions", "timeout_seconds"},
        )
        _integer(cell["input_tokens"], f"{path}.input_tokens", minimum=1, maximum=1048576)
        _integer(cell["output_tokens"], f"{path}.output_tokens", minimum=1, maximum=1048576)
        _integer(cell["concurrency"], f"{path}.concurrency", minimum=1, maximum=10000)
        _integer(cell["requests"], f"{path}.requests", minimum=1, maximum=10000000)
        if "repetitions" in cell:
            _integer(cell["repetitions"], f"{path}.repetitions", minimum=1, maximum=100)
        if "timeout_seconds" in cell:
            _integer(cell["timeout_seconds"], f"{path}.timeout_seconds", minimum=1, maximum=86400)

    if not planning_only:
        _validate_execution_contract(root["execution"], runtimes, cells, resource)
    return not planning_only


def _validate_execution_contract(
    value: object,
    base_runtimes: list[object],
    base_cells: list[object],
    base_resource: Mapping[str, object],
) -> None:
    execution = _shape(
        value,
        "manifest.execution",
        required={"resource", "model", "runtimes", "workload", "quality_gates", "telemetry", "teardown"},
        optional={"selected_arm", "guard_policy"},
    )
    resource = _shape(
        execution["resource"],
        "manifest.execution.resource",
        required={"gpu_id", "regions", "datacenters", "container", "storage", "network"},
    )
    _string(resource["gpu_id"], "manifest.execution.resource.gpu_id", maximum=128)
    _string_list(resource["regions"], "manifest.execution.resource.regions", allow_empty=False, maximum=32)
    _string_list(resource["datacenters"], "manifest.execution.resource.datacenters", allow_empty=False, maximum=64)
    container = _shape(
        resource["container"],
        "manifest.execution.resource.container",
        required={"image_digest", "cuda_version", "driver_requirement"},
        optional={"image"},
    )
    if "image" in container:
        _string(container["image"], "manifest.execution.resource.container.image", maximum=256)
    digest = _string(container["image_digest"], "manifest.execution.resource.container.image_digest", maximum=71)
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) is None:
        raise ValueError("manifest.execution.resource.container.image_digest must be an immutable sha256 digest")
    _string(container["cuda_version"], "manifest.execution.resource.container.cuda_version", maximum=32)
    _string(container["driver_requirement"], "manifest.execution.resource.container.driver_requirement", maximum=64)
    storage = _shape(
        resource["storage"],
        "manifest.execution.resource.storage",
        required={"container_disk_gb", "volume_gb", "network_volume_gb"},
    )
    for name in storage:
        _integer(storage[name], f"manifest.execution.resource.storage.{name}", minimum=0, maximum=65536)
    network = _shape(
        resource["network"],
        "manifest.execution.resource.network",
        required={"ports", "public_ip", "egress_policy"},
    )
    ports = network["ports"]
    if not isinstance(ports, list) or not ports or len(ports) > 64:
        raise ValueError("manifest.execution.resource.network.ports must be a non-empty array of at most 64 items")
    for index, port in enumerate(ports):
        _integer(port, f"manifest.execution.resource.network.ports[{index}]", minimum=1, maximum=65535)
    if len(set(ports)) != len(ports):
        raise ValueError("manifest.execution.resource.network.ports must not contain duplicates")
    _boolean(network["public_ip"], "manifest.execution.resource.network.public_ip")
    _enum(network["egress_policy"], "manifest.execution.resource.network.egress_policy", {"none", "model-download-only", "restricted"})

    model = _shape(
        execution["model"],
        "manifest.execution.model",
        required={"tokenizer_repository", "tokenizer_revision", "dtype", "context_length", "chat_template"},
    )
    _string(model["tokenizer_repository"], "manifest.execution.model.tokenizer_repository", maximum=256)
    _hex(model["tokenizer_revision"], "manifest.execution.model.tokenizer_revision", lengths=(40, 64))
    _enum(model["dtype"], "manifest.execution.model.dtype", {"bfloat16", "float16", "float32", "int8", "int4"})
    _integer(model["context_length"], "manifest.execution.model.context_length", minimum=1, maximum=1048576)
    template = _shape(
        model["chat_template"],
        "manifest.execution.model.chat_template",
        required={"revision", "sha256"},
    )
    _hex(template["revision"], "manifest.execution.model.chat_template.revision", lengths=(40, 64))
    _hex(template["sha256"], "manifest.execution.model.chat_template.sha256", lengths=(64,))

    detailed_runtimes = execution["runtimes"]
    if not isinstance(detailed_runtimes, list) or len(detailed_runtimes) != len(base_runtimes):
        raise ValueError("manifest.execution.runtimes must match manifest.runtimes")
    for index, raw_runtime in enumerate(detailed_runtimes):
        path = f"manifest.execution.runtimes[{index}]"
        runtime = _shape(
            raw_runtime,
            path,
            required={"id", "version", "dependencies", "launch_arguments", "backend", "optimizations", "fallback_policy"},
            optional={"arm_settings"},
        )
        base = _mapping(base_runtimes[index], f"manifest.runtimes[{index}]")
        _pinned_version(base["version"], f"manifest.runtimes[{index}].version")
        _pinned_version(runtime["version"], f"{path}.version")
        if runtime["id"] != base["id"] or runtime["version"] != base["version"]:
            raise ValueError(f"{path} id/version must match manifest.runtimes[{index}]")
        dependencies = runtime["dependencies"]
        if not isinstance(dependencies, list) or not dependencies or len(dependencies) > 128:
            raise ValueError(f"{path}.dependencies must be a non-empty array of at most 128 items")
        for dep_index, raw_dependency in enumerate(dependencies):
            dep_path = f"{path}.dependencies[{dep_index}]"
            dependency = _shape(raw_dependency, dep_path, required={"name", "version"})
            _string(dependency["name"], f"{dep_path}.name", maximum=128)
            _pinned_version(dependency["version"], f"{dep_path}.version")
        _string_list(runtime["launch_arguments"], f"{path}.launch_arguments", allow_empty=True, maximum=128)
        _string(runtime["backend"], f"{path}.backend", maximum=128)
        optimization = _shape(
            runtime["optimizations"],
            f"{path}.optimizations",
            required={"continuous_batching", "chunked_prefill", "prefix_caching", "speculative_decoding", "quantization", "kv_cache_dtype", "tensor_parallel", "pipeline_parallel"},
        )
        for field in ("continuous_batching", "chunked_prefill", "prefix_caching"):
            _boolean(optimization[field], f"{path}.optimizations.{field}")
        for field in ("speculative_decoding", "quantization", "kv_cache_dtype"):
            _string(optimization[field], f"{path}.optimizations.{field}", maximum=128)
        for field in ("tensor_parallel", "pipeline_parallel"):
            _integer(optimization[field], f"{path}.optimizations.{field}", minimum=1, maximum=64)
        policy = _shape(runtime["fallback_policy"], f"{path}.fallback_policy", required={"mode", "max_attempts"})
        mode = _enum(policy["mode"], f"{path}.fallback_policy.mode", {"none", "ordered"})
        _integer(policy["max_attempts"], f"{path}.fallback_policy.max_attempts", minimum=1, maximum=17)
        base_fallbacks = base["fallbacks"]
        if (mode == "none") != (base_fallbacks == []):
            raise ValueError(f"{path}.fallback_policy.mode must agree with manifest.runtimes[{index}].fallbacks")

    workload = _shape(
        execution["workload"],
        "manifest.execution.workload",
        required={"dataset", "prompt_cells", "sampling", "seed", "warmup_requests", "repetitions", "timeout_seconds", "load_mode"},
        optional={"arrival_processes"},
    )
    dataset = _shape(workload["dataset"], "manifest.execution.workload.dataset", required={"source", "revision", "sha256"})
    _string(dataset["source"], "manifest.execution.workload.dataset.source", maximum=256)
    _hex(dataset["revision"], "manifest.execution.workload.dataset.revision", lengths=(40, 64))
    _hex(dataset["sha256"], "manifest.execution.workload.dataset.sha256", lengths=(64,))
    prompt_cells = workload["prompt_cells"]
    if not isinstance(prompt_cells, list) or len(prompt_cells) != len(base_cells):
        raise ValueError("manifest.execution.workload.prompt_cells must match manifest.workload.cells")
    for index, raw_prompt in enumerate(prompt_cells):
        prompt = _shape(raw_prompt, f"manifest.execution.workload.prompt_cells[{index}]", required={"id", "prompt_sha256"})
        _string(prompt["id"], f"manifest.execution.workload.prompt_cells[{index}].id", maximum=128)
        _hex(prompt["prompt_sha256"], f"manifest.execution.workload.prompt_cells[{index}].prompt_sha256", lengths=(64,))
    sampling = _shape(workload["sampling"], "manifest.execution.workload.sampling", required={"temperature", "top_p", "top_k"})
    _decimal_string(sampling["temperature"], "manifest.execution.workload.sampling.temperature", minimum=Decimal("0"), maximum=Decimal("2"), fractional_digits=6)
    _decimal_string(sampling["top_p"], "manifest.execution.workload.sampling.top_p", minimum=Decimal("0"), maximum=Decimal("1"), fractional_digits=6)
    _integer(sampling["top_k"], "manifest.execution.workload.sampling.top_k", minimum=0, maximum=100000)
    _integer(workload["seed"], "manifest.execution.workload.seed", minimum=0, maximum=2147483647)
    _integer(workload["warmup_requests"], "manifest.execution.workload.warmup_requests", minimum=0, maximum=100000)
    _integer(workload["repetitions"], "manifest.execution.workload.repetitions", minimum=1, maximum=100)
    _integer(workload["timeout_seconds"], "manifest.execution.workload.timeout_seconds", minimum=1, maximum=86400)
    load_mode = _enum(workload["load_mode"], "manifest.execution.workload.load_mode", {"closed-loop", "open-loop"})
    if load_mode == "closed-loop":
        if "arrival_processes" in workload:
            raise ValueError("manifest.execution.workload.arrival_processes is forbidden for closed-loop")
    else:
        if "arrival_processes" not in workload:
            raise ValueError("manifest.execution.workload: missing required field(s): arrival_processes")
        arrival_processes = workload["arrival_processes"]
        if not isinstance(arrival_processes, list) or len(arrival_processes) != len(base_cells):
            raise ValueError("manifest.execution.workload.arrival_processes must match manifest.workload.cells")
        for index, raw_process in enumerate(arrival_processes):
            path = f"manifest.execution.workload.arrival_processes[{index}]"
            process = _shape(raw_process, path, required={"arrival_rate_rps", "unit", "distribution"})
            _decimal_string(
                process["arrival_rate_rps"],
                f"{path}.arrival_rate_rps",
                minimum=Decimal("0.000001"),
                maximum=Decimal("1000000"),
                fractional_digits=6,
            )
            _enum(process["unit"], f"{path}.unit", {"requests_per_second"})
            _enum(process["distribution"], f"{path}.distribution", {"constant", "poisson"})

    quality = _shape(
        execution["quality_gates"],
        "manifest.execution.quality_gates",
        required={"minimum_success_rate", "maximum_error_rate", "maximum_p99_ms", "output_validation"},
    )
    _decimal_string(quality["minimum_success_rate"], "manifest.execution.quality_gates.minimum_success_rate", minimum=Decimal("0"), maximum=Decimal("1"), fractional_digits=6)
    _decimal_string(quality["maximum_error_rate"], "manifest.execution.quality_gates.maximum_error_rate", minimum=Decimal("0"), maximum=Decimal("1"), fractional_digits=6)
    _integer(quality["maximum_p99_ms"], "manifest.execution.quality_gates.maximum_p99_ms", minimum=1, maximum=86400000)
    _string(quality["output_validation"], "manifest.execution.quality_gates.output_validation", maximum=128)

    telemetry = _shape(execution["telemetry"], "manifest.execution.telemetry", required={"cadence_seconds", "collectors"})
    _integer(telemetry["cadence_seconds"], "manifest.execution.telemetry.cadence_seconds", minimum=1, maximum=3600)
    _string_list(telemetry["collectors"], "manifest.execution.telemetry.collectors", allow_empty=False, maximum=32)

    teardown = _shape(
        execution["teardown"],
        "manifest.execution.teardown",
        required={"delete_after_minutes", "resources", "require_inventory_absent", "require_direct_lookup_not_found"},
    )
    deadline = _integer(teardown["delete_after_minutes"], "manifest.execution.teardown.delete_after_minutes", minimum=1, maximum=10080)
    if deadline > int(base_resource["terminate_after_minutes"]):
        raise ValueError("manifest.execution.teardown.delete_after_minutes exceeds resource termination deadline")
    resources = _string_list(teardown["resources"], "manifest.execution.teardown.resources", allow_empty=False, maximum=16)
    if not set(resources) <= {"pod", "volume", "network_volume", "endpoint"}:
        raise ValueError("manifest.execution.teardown.resources contains an unknown resource kind")
    _boolean(teardown["require_inventory_absent"], "manifest.execution.teardown.require_inventory_absent")
    _boolean(teardown["require_direct_lookup_not_found"], "manifest.execution.teardown.require_direct_lookup_not_found")
    if teardown["require_inventory_absent"] is not True or teardown["require_direct_lookup_not_found"] is not True:
        raise ValueError("manifest.execution.teardown must require both deletion proof checks")
    if "guard_policy" in execution:
        _validate_guard_policy(execution["guard_policy"], detailed_runtimes)
        if resources != ["pod"]:
            raise ValueError("manifest.execution.guard_policy supports pod-only teardown")
    if "selected_arm" in execution:
        _validate_selected_arm(
            execution["selected_arm"],
            workload,
            detailed_runtimes,
            container,
            int(base_resource["gpu_count"]),
        )


def _validate_guard_policy(value: object, runtimes: list[object]) -> Mapping[str, object]:
    path = "manifest.execution.guard_policy"
    policy = _shape(
        value,
        path,
        required={
            "mode",
            "watchdogs",
            "launcher",
            "clock",
            "poll_interval_seconds",
            "cli_timeout_seconds",
            "arming_timeout_seconds",
            "heartbeat_stale_after_seconds",
            "delete_retry_delays_seconds",
            "start_no_new_arms_at_fraction",
            "teardown_at_fraction",
            "arm_order",
            "watchdog_script_sha256",
            "launcher_script_sha256",
        },
    )
    _enum(policy["mode"], f"{path}.mode", {"local_only_acknowledged"})
    watchdogs = _string_list(
        policy["watchdogs"], f"{path}.watchdogs", allow_empty=False, maximum=2
    )
    if watchdogs != ["primary", "secondary"]:
        raise ValueError(f"{path}.watchdogs must be exactly primary, secondary")
    _enum(policy["launcher"], f"{path}.launcher", {"caffeinate"})
    _enum(policy["clock"], f"{path}.clock", {"monotonic"})
    _integer(
        policy["poll_interval_seconds"],
        f"{path}.poll_interval_seconds",
        minimum=1,
        maximum=60,
    )
    _integer(policy["cli_timeout_seconds"], f"{path}.cli_timeout_seconds", minimum=1, maximum=60)
    _integer(policy["arming_timeout_seconds"], f"{path}.arming_timeout_seconds", minimum=1, maximum=120)
    heartbeat_stale = _integer(
        policy["heartbeat_stale_after_seconds"],
        f"{path}.heartbeat_stale_after_seconds",
        minimum=3,
        maximum=300,
    )
    if heartbeat_stale < int(policy["poll_interval_seconds"]) + int(policy["cli_timeout_seconds"]):
        raise ValueError(f"{path}.heartbeat_stale_after_seconds is too short for one poll")
    delays = policy["delete_retry_delays_seconds"]
    if not isinstance(delays, list) or not 2 <= len(delays) <= 10:
        raise ValueError(
            f"{path}.delete_retry_delays_seconds must contain between 2 and 10 delays"
        )
    previous = -1
    for index, delay in enumerate(delays):
        current = _integer(
            delay,
            f"{path}.delete_retry_delays_seconds[{index}]",
            minimum=0,
            maximum=300,
        )
        if current < previous:
            raise ValueError(f"{path}.delete_retry_delays_seconds must be nondecreasing")
        previous = current
    soft_stop = _decimal_string(
        policy["start_no_new_arms_at_fraction"],
        f"{path}.start_no_new_arms_at_fraction",
        minimum=Decimal("0.75"),
        maximum=Decimal("0.75"),
        fractional_digits=2,
    )
    teardown_fraction = _decimal_string(
        policy["teardown_at_fraction"],
        f"{path}.teardown_at_fraction",
        minimum=Decimal("0.85"),
        maximum=Decimal("0.85"),
        fractional_digits=2,
    )
    if soft_stop >= teardown_fraction:
        raise ValueError(f"{path} soft stop must precede teardown")
    arm_order = _string_list(
        policy["arm_order"], f"{path}.arm_order", allow_empty=False, maximum=16
    )
    runtime_ids = [
        _mapping(runtime, f"manifest.execution.runtimes[{index}]")["id"]
        for index, runtime in enumerate(runtimes)
    ]
    if len(set(arm_order)) != len(arm_order) or set(arm_order) != set(runtime_ids):
        raise ValueError(f"{path}.arm_order must contain every execution runtime id exactly once")
    _hex(policy["watchdog_script_sha256"], f"{path}.watchdog_script_sha256", lengths=(64,))
    _hex(policy["launcher_script_sha256"], f"{path}.launcher_script_sha256", lengths=(64,))
    return policy


def _validate_optional_optimization(
    value: object,
    path: str,
    *,
    required: set[str],
) -> Mapping[str, object]:
    result = _shape(value, path, required={"enabled"}, optional=required)
    enabled = _boolean(result["enabled"], f"{path}.enabled")
    for field in required:
        if enabled and (field not in result or result[field] is None):
            raise ValueError(f"{path}: missing required field(s): {field}")
        if not enabled and field in result and result[field] is not None:
            raise ValueError(f"{path}.{field} must be null when disabled")
    return result


def _validate_arm_settings(value: object, path: str, workload: Mapping[str, object], *, enforce_load: bool = True) -> Mapping[str, object]:
    settings = _shape(
        value,
        path,
        required={"continuous_batching", "chunked_prefill", "prefix_caching", "speculative_decoding", "weight_quantization", "kv_cache_quantization", "parallelism", "open_loop"},
    )
    batching = _shape(settings["continuous_batching"], f"{path}.continuous_batching", required={"enabled", "admission_limit"})
    _boolean(batching["enabled"], f"{path}.continuous_batching.enabled")
    _integer(batching["admission_limit"], f"{path}.continuous_batching.admission_limit", minimum=1, maximum=1000000)
    _boolean(settings["chunked_prefill"], f"{path}.chunked_prefill")
    prefix = _shape(settings["prefix_caching"], f"{path}.prefix_caching", required={"enabled", "shared_prefix_fraction", "shared_prefix_tokens"})
    _boolean(prefix["enabled"], f"{path}.prefix_caching.enabled")
    _decimal_string(prefix["shared_prefix_fraction"], f"{path}.prefix_caching.shared_prefix_fraction", minimum=Decimal("0"), maximum=Decimal("1"), fractional_digits=6)
    _integer(prefix["shared_prefix_tokens"], f"{path}.prefix_caching.shared_prefix_tokens", minimum=0, maximum=1048576)

    speculative = _validate_optional_optimization(settings["speculative_decoding"], f"{path}.speculative_decoding", required={"draft_repository", "draft_revision", "method", "num_speculative_tokens"})
    if speculative["enabled"]:
        _string(speculative["draft_repository"], f"{path}.speculative_decoding.draft_repository", maximum=256)
        _hex(speculative["draft_revision"], f"{path}.speculative_decoding.draft_revision", lengths=(40, 64))
        _string(speculative["method"], f"{path}.speculative_decoding.method", maximum=128)
        _integer(speculative["num_speculative_tokens"], f"{path}.speculative_decoding.num_speculative_tokens", minimum=1, maximum=1024)
    for field in ("weight_quantization", "kv_cache_quantization"):
        binding = _validate_optional_optimization(settings[field], f"{path}.{field}", required={"format", "method"})
        if binding["enabled"]:
            _string(binding["format"], f"{path}.{field}.format", maximum=128)
            _string(binding["method"], f"{path}.{field}.method", maximum=128)
    parallelism = _shape(settings["parallelism"], f"{path}.parallelism", required={"tensor_parallel", "pipeline_parallel", "data_parallel"})
    for field in parallelism:
        _integer(parallelism[field], f"{path}.parallelism.{field}", minimum=1, maximum=64)
    open_loop = _validate_optional_optimization(settings["open_loop"], f"{path}.open_loop", required={"arrival_rate_rps", "distribution", "maximum_ttft_p99_ms", "maximum_e2e_p99_ms", "minimum_achieved_rate_fraction", "maximum_queue_growth_rps", "sustain_seconds"})
    if open_loop["enabled"]:
        rate = _decimal_string(open_loop["arrival_rate_rps"], f"{path}.open_loop.arrival_rate_rps", minimum=Decimal("0.000001"), maximum=Decimal("1000000"), fractional_digits=6)
        distribution = _enum(open_loop["distribution"], f"{path}.open_loop.distribution", {"constant", "poisson"})
        _integer(open_loop["maximum_ttft_p99_ms"], f"{path}.open_loop.maximum_ttft_p99_ms", minimum=1, maximum=86400000)
        _integer(open_loop["maximum_e2e_p99_ms"], f"{path}.open_loop.maximum_e2e_p99_ms", minimum=1, maximum=86400000)
        _decimal_string(open_loop["minimum_achieved_rate_fraction"], f"{path}.open_loop.minimum_achieved_rate_fraction", minimum=Decimal("0"), maximum=Decimal("1"), fractional_digits=6)
        _decimal_string(open_loop["maximum_queue_growth_rps"], f"{path}.open_loop.maximum_queue_growth_rps", minimum=Decimal("0"), maximum=Decimal("1000000"), fractional_digits=6)
        _integer(open_loop["sustain_seconds"], f"{path}.open_loop.sustain_seconds", minimum=1, maximum=86400)
        if enforce_load and workload.get("load_mode") != "open-loop":
            raise ValueError(f"{path}.open_loop requires execution workload load_mode open-loop")
        arrivals = workload.get("arrival_processes")
        if enforce_load and (not isinstance(arrivals, list) or any(not isinstance(process, Mapping) or Decimal(str(process.get("arrival_rate_rps"))) != rate or process.get("distribution") != distribution for process in arrivals)):
            raise ValueError(f"{path}.open_loop must match every workload arrival process")
    elif enforce_load and workload.get("load_mode") != "closed-loop":
        raise ValueError(f"{path}.open_loop disabled requires execution workload load_mode closed-loop")
    return settings


def _validate_selected_arm(
    value: object,
    workload: Mapping[str, object],
    runtimes: list[object],
    container: Mapping[str, object],
    gpu_count: int,
) -> None:
    path = "manifest.execution.selected_arm"
    arm = _shape(
        value,
        path,
        required={
            "id",
            "role",
            "runtime_id",
            "changed_variable",
            "image_digest",
            "image",
            "runtime_version",
            "backend",
            "dependencies",
            "launch_arguments",
            "baseline",
            "treatment",
            "quality_thresholds",
        },
    )
    _string(arm["id"], f"{path}.id", maximum=128)
    _enum(arm["role"], f"{path}.role", {"baseline", "optimized", "peer"})
    _string(arm["runtime_id"], f"{path}.runtime_id", maximum=64)
    _enum(
        arm["changed_variable"],
        f"{path}.changed_variable",
        {
            "baseline",
            "continuous_batching",
            "chunked_prefill",
            "prefix_caching",
            "speculative_decoding",
            "weight_quantization",
            "kv_cache_quantization",
            "parallelism",
            "open_loop",
        },
    )
    digest = _string(arm["image_digest"], f"{path}.image_digest", maximum=71)
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) is None:
        raise ValueError(f"{path}.image_digest must be an immutable sha256 digest")
    _string(arm["image"], f"{path}.image", maximum=256)
    _pinned_version(arm["runtime_version"], f"{path}.runtime_version")
    _string(arm["backend"], f"{path}.backend", maximum=128)
    if not isinstance(arm["dependencies"], list):
        raise TypeError(f"{path}.dependencies must be an array")
    _string_list(arm["launch_arguments"], f"{path}.launch_arguments", allow_empty=True, maximum=128)
    matches = [runtime for runtime in runtimes if isinstance(runtime, Mapping) and runtime.get("id") == arm["runtime_id"]]
    if len(matches) != 1:
        raise ValueError(f"{path}.runtime_id must identify exactly one execution runtime")
    runtime = matches[0]
    for field in ("version", "backend", "dependencies", "launch_arguments"):
        arm_field = "runtime_version" if field == "version" else field
        if arm[arm_field] != runtime[field]:
            raise ValueError(f"{path}.{arm_field} must exactly match the execution runtime")
    for field in ("image", "image_digest"):
        if field not in container or arm[field] != container[field]:
            raise ValueError(f"{path}.{field} must exactly match the execution container")
    if "arm_settings" not in runtime:
        raise ValueError(f"execution runtime selected by {path}.runtime_id must declare arm_settings")
    baseline = _validate_arm_settings(arm["baseline"], f"{path}.baseline", workload, enforce_load=False)
    treatment = _validate_arm_settings(arm["treatment"], f"{path}.treatment", workload)
    for role, settings in (("baseline", baseline), ("treatment", treatment)):
        topology = settings["parallelism"]
        allocated = (
            topology["tensor_parallel"]
            * topology["pipeline_parallel"]
            * topology["data_parallel"]
        )
        if allocated != gpu_count:
            raise ValueError(
                f"{path}.{role}.parallelism GPU allocation {allocated} "
                f"must equal resource.gpu_count {gpu_count}"
            )
    if baseline != runtime["arm_settings"]:
        raise ValueError(f"{path}.baseline must exactly match execution runtime arm_settings")
    optimizations = runtime["optimizations"]
    coarse = {
        "continuous_batching": baseline["continuous_batching"]["enabled"],
        "chunked_prefill": baseline["chunked_prefill"],
        "prefix_caching": baseline["prefix_caching"]["enabled"],
        "speculative_decoding": baseline["speculative_decoding"].get("method", "none") if baseline["speculative_decoding"]["enabled"] else "none",
        "quantization": baseline["weight_quantization"].get("format", "none") if baseline["weight_quantization"]["enabled"] else "none",
        "kv_cache_dtype": baseline["kv_cache_quantization"].get("format", "auto") if baseline["kv_cache_quantization"]["enabled"] else "auto",
        "tensor_parallel": baseline["parallelism"]["tensor_parallel"],
        "pipeline_parallel": baseline["parallelism"]["pipeline_parallel"],
    }
    if optimizations != coarse:
        raise ValueError(f"{path}.baseline must exactly match execution runtime optimizations")
    differences = [field for field in baseline if baseline[field] != treatment[field]]
    changed_variable = arm["changed_variable"]
    if changed_variable == "baseline":
        if differences:
            raise ValueError(f"{path} baseline pair must not change a variable")
    elif differences != [changed_variable]:
        raise ValueError(f"{path} must change exactly the declared variable")

    quality = _shape(
        arm["quality_thresholds"],
        f"{path}.quality_thresholds",
        required={
            "minimum_success_rate",
            "maximum_error_rate",
            "maximum_quality_regression",
            "maximum_output_length_relative_change",
            "maximum_stop_reason_divergence",
            "evaluator",
            "evaluator_version",
        },
    )
    for field in (
        "minimum_success_rate",
        "maximum_error_rate",
        "maximum_quality_regression",
        "maximum_output_length_relative_change",
        "maximum_stop_reason_divergence",
    ):
        _decimal_string(
            quality[field],
            f"{path}.quality_thresholds.{field}",
            minimum=Decimal("0"),
            maximum=Decimal("1"),
            fractional_digits=6,
        )
    _string(quality["evaluator"], f"{path}.quality_thresholds.evaluator", maximum=128)
    _pinned_version(quality["evaluator_version"], f"{path}.quality_thresholds.evaluator_version")



def unresolved_optimization_bindings(template: Mapping[str, object]) -> tuple[str, ...]:
    """Return unresolved JSON-pointer paths from an optimization template."""

    root = _mapping(template, "template")
    readiness = _shape(
        root.get("readiness"),
        "template.readiness",
        required={"required_bindings"},
    )
    pointers = _string_list(
        readiness["required_bindings"],
        "template.readiness.required_bindings",
        allow_empty=False,
        maximum=512,
    )
    unresolved: list[str] = []
    for pointer in pointers:
        if not pointer.startswith("/"):
            raise ValueError("template readiness paths must be absolute JSON pointers")
        current: object = root
        traversed: list[object] = [root]
        try:
            for raw_part in pointer[1:].split("/"):
                part = raw_part.replace("~1", "/").replace("~0", "~")
                if isinstance(current, Mapping):
                    current = current[part]
                elif isinstance(current, list):
                    current = current[int(part)]
                else:
                    raise KeyError(part)
                traversed.append(current)
        except (KeyError, IndexError, ValueError):
            if isinstance(current, Mapping) and current.get("enabled") is False:
                continue
            unresolved.append(pointer)
            continue
        # Optional technique children are material only when their parent
        # discriminator is enabled.  The discriminator itself always remains
        # required and digest-bound.
        parent = traversed[-2] if len(traversed) >= 2 else None
        if isinstance(parent, Mapping) and parent.get("enabled") is False and not pointer.endswith("/enabled"):
            continue
        if current is None or current == "" or current == [] or current == {}:
            unresolved.append(pointer)
    return tuple(unresolved)


def compile_optimization_plan(
    template: Mapping[str, object],
    manifest: Mapping[str, object],
    live_inputs: Mapping[str, object],
) -> dict[str, object]:
    """Compile only a fully resolved, explicitly readied optimization template."""

    template = _mapping(template, "template")
    if (
        template.get("planning_only") is not False
        or template.get("paid_execution_authorized") is not True
        or template.get("ready_for_paid_compile") is not True
    ):
        raise ValueError("optimization template is not ready for paid compilation")
    unresolved = unresolved_optimization_bindings(template)
    if unresolved:
        raise ValueError("optimization template has unresolved material bindings")
    manifest = _mapping(manifest, "manifest")
    execution = _mapping(manifest.get("execution"), "manifest.execution")
    selected = _mapping(
        template.get("selected_execution_arm"), "template.selected_execution_arm"
    )
    if execution.get("selected_arm") != selected:
        raise ValueError("manifest.execution.selected_arm does not match the resolved template")
    return compile_plan(manifest, live_inputs)


def _validate_live(
    live_inputs: Mapping[str, object],
    *,
    execution_ready: bool,
    local_guard_required: bool = False,
) -> None:
    root = _shape(
        live_inputs,
        "live_inputs",
        required={"gpu", "account", "estimate", "compatibility"},
        optional={"ancillary_costs", "guard_acknowledgment"},
    )
    gpu_offer_fields = {"cloud", "region", "datacenter", "source", "observed_at", "expires_at"}
    gpu = _shape(
        root["gpu"],
        "live_inputs.gpu",
        required={"gpu_id", "hourly_usd", "stock"},
        optional=gpu_offer_fields,
    )
    _string(gpu["gpu_id"], "live_inputs.gpu.gpu_id", maximum=128)
    _decimal_string(gpu["hourly_usd"], "live_inputs.gpu.hourly_usd", minimum=Decimal("0.000001"), maximum=Decimal("10000"))
    if gpu["stock"] != "available":
        raise ValueError("live_inputs.gpu.stock must be available")
    if execution_ready or any(field in gpu for field in gpu_offer_fields):
        missing = sorted(gpu_offer_fields - set(gpu))
        if missing:
            raise ValueError(f"live_inputs.gpu: missing required field(s): {', '.join(missing)}")
        _enum(gpu["cloud"], "live_inputs.gpu.cloud", {"SECURE", "COMMUNITY"})
        _string(gpu["region"], "live_inputs.gpu.region", maximum=128)
        _string(gpu["datacenter"], "live_inputs.gpu.datacenter", maximum=128)
        _string(gpu["source"], "live_inputs.gpu.source", maximum=256)
        _validate_observation_window(
            gpu["observed_at"], gpu["expires_at"], "live_inputs.gpu"
        )

    account = _shape(
        root["account"],
        "live_inputs.account",
        required={"balance_usd", "auto_recharge_verified_disabled"},
    )
    _decimal_string(
        account["balance_usd"],
        "live_inputs.account.balance_usd",
        minimum=Decimal("0"),
        maximum=Decimal("1000000"),
    )
    if account["auto_recharge_verified_disabled"] is not True:
        raise ValueError("live_inputs.account auto-recharge must be verified disabled")

    estimate = _shape(
        root["estimate"],
        "live_inputs.estimate",
        required={"expected_minutes", "maximum_minutes"},
    )
    expected = _integer(estimate["expected_minutes"], "live_inputs.estimate.expected_minutes", minimum=1, maximum=10080)
    maximum = _integer(estimate["maximum_minutes"], "live_inputs.estimate.maximum_minutes", minimum=1, maximum=10080)
    if expected > maximum:
        raise ValueError("live_inputs.estimate.expected_minutes must not exceed maximum_minutes")

    compatibility = _shape(
        root["compatibility"],
        "live_inputs.compatibility",
        required={"status", "evidence"},
    )
    if compatibility["status"] != "pass":
        raise ValueError("live_inputs.compatibility.status must be pass")
    _string_list(compatibility["evidence"], "live_inputs.compatibility.evidence", allow_empty=False, maximum=128)

    if "ancillary_costs" in root:
        _validate_ancillary_costs(root["ancillary_costs"])
    elif execution_ready:
        raise ValueError("live_inputs: missing required field(s): ancillary_costs")
    if local_guard_required:
        if "guard_acknowledgment" not in root:
            raise ValueError("live_inputs: missing required field(s): guard_acknowledgment")
        acknowledgment = _shape(
            root["guard_acknowledgment"],
            "live_inputs.guard_acknowledgment",
            required={"response", "source", "observed_at"},
        )
        if acknowledgment["response"] != _LOCAL_GUARD_ACKNOWLEDGMENT:
            raise ValueError(
                "live_inputs.guard_acknowledgment.response must be exactly "
                "ACCEPT LOCAL-WATCHDOG RISK"
            )
        _enum(acknowledgment["source"], "live_inputs.guard_acknowledgment.source", {"user"})
        _timestamp(acknowledgment["observed_at"], "live_inputs.guard_acknowledgment.observed_at")
    elif "guard_acknowledgment" in root:
        raise ValueError(
            "live_inputs.guard_acknowledgment is allowed only for local_only_acknowledged mode"
        )


def _validate_ancillary_costs(value: object) -> Decimal:
    ancillary = _shape(
        value,
        "live_inputs.ancillary_costs",
        required={"observed_at", "expires_at", "source", "components"},
    )
    _validate_observation_window(
        ancillary["observed_at"], ancillary["expires_at"], "live_inputs.ancillary_costs"
    )
    _string(ancillary["source"], "live_inputs.ancillary_costs.source", maximum=256)
    components = _shape(
        ancillary["components"],
        "live_inputs.ancillary_costs.components",
        required=_ANCILLARY_COMPONENTS,
    )
    hourly_total = Decimal("0")
    for name in sorted(_ANCILLARY_COMPONENTS):
        path = f"live_inputs.ancillary_costs.components.{name}"
        component = _shape(
            components[name],
            path,
            required={"status"},
            optional={"amount_usd", "hourly_usd"},
        )
        status = _enum(
            component["status"], f"{path}.status", {"billed", "included", "zero"}
        )
        if status == "billed":
            if set(component) != {"status", "hourly_usd"}:
                raise ValueError(f"{path}.hourly_usd is required for billed components")
            hourly_total += _decimal_string(
                component["hourly_usd"],
                f"{path}.hourly_usd",
                minimum=Decimal("0.000001"),
                maximum=Decimal("10000"),
            )
        else:
            if set(component) != {"status", "amount_usd"}:
                raise ValueError(f"{path}.amount_usd is required for {status} components")
            amount = _decimal_string(
                component["amount_usd"],
                f"{path}.amount_usd",
                minimum=Decimal("0"),
                maximum=Decimal("0"),
                fractional_digits=2,
            )
            if amount != 0 or component["amount_usd"] != "0.00":
                raise ValueError(f"{path}.amount_usd must be exactly 0.00")
    return hourly_total


def _validate_observation_window(observed_value: object, expires_value: object, path: str) -> None:
    observed = _timestamp(observed_value, f"{path}.observed_at")
    expires = _timestamp(expires_value, f"{path}.expires_at")
    now = datetime.now(timezone.utc)
    if observed > now:
        raise ValueError(f"{path}.observed_at is in the future")
    if now - observed > _MAX_LIVE_EVIDENCE_AGE:
        raise ValueError(f"{path} evidence is stale")
    if expires <= observed or expires <= now:
        raise ValueError(f"{path} evidence is expired")
    if expires - observed > _MAX_LIVE_EVIDENCE_AGE:
        raise ValueError(f"{path} validity window exceeds 15 minutes")


def compile_plan(
    manifest: Mapping[str, object], live_inputs: Mapping[str, object]
) -> dict[str, object]:
    """Validate inputs and return a detached deterministic cost plan."""

    manifest = _mapping(manifest, "manifest")
    live_inputs = _mapping(live_inputs, "live_inputs")
    execution_ready = _validate_manifest(manifest)
    guard_policy = None
    if execution_ready:
        execution = _mapping(manifest["execution"], "manifest.execution")
        if "guard_policy" in execution:
            guard_policy = _mapping(
                execution["guard_policy"], "manifest.execution.guard_policy"
            )
    local_guard_required = bool(
        guard_policy and guard_policy.get("mode") == "local_only_acknowledged"
    )
    _validate_live(
        live_inputs,
        execution_ready=execution_ready,
        local_guard_required=local_guard_required,
    )

    budget = _mapping(manifest["budget"], "manifest.budget")
    resource = _mapping(manifest["resource"], "manifest.resource")
    gpu = _mapping(live_inputs["gpu"], "live_inputs.gpu")
    account = _mapping(live_inputs["account"], "live_inputs.account")
    estimate = _mapping(live_inputs["estimate"], "live_inputs.estimate")
    if execution_ready:
        execution = _mapping(manifest["execution"], "manifest.execution")
        execution_resource = _mapping(execution["resource"], "manifest.execution.resource")
        if execution_resource["gpu_id"] != gpu["gpu_id"]:
            raise ValueError("live_inputs.gpu.gpu_id does not match manifest.execution.resource.gpu_id")
        if resource["cloud"] != gpu["cloud"]:
            raise ValueError("live_inputs.gpu.cloud does not match manifest.resource.cloud")
        if gpu["region"] not in execution_resource["regions"]:
            raise ValueError("live_inputs.gpu.region is not allowed by manifest.execution.resource.regions")
        if gpu["datacenter"] not in execution_resource["datacenters"]:
            raise ValueError("live_inputs.gpu.datacenter is not allowed by manifest.execution.resource.datacenters")

    cap = _decimal_string(
        budget["max_usd"],
        "manifest.budget.max_usd",
        minimum=Decimal("0.01"),
        maximum=Decimal("10000"),
        fractional_digits=2,
    )
    reserve = _decimal_string(
        budget["minimum_final_balance_usd"],
        "manifest.budget.minimum_final_balance_usd",
        minimum=Decimal("0"),
        maximum=Decimal("1000000"),
        fractional_digits=2,
    )
    hourly = _decimal_string(gpu["hourly_usd"], "live_inputs.gpu.hourly_usd", minimum=Decimal("0.000001"), maximum=Decimal("10000"))
    balance = _decimal_string(account["balance_usd"], "live_inputs.account.balance_usd", minimum=Decimal("0"), maximum=Decimal("1000000"))
    gpu_count = int(resource["gpu_count"])
    gpu_rate = hourly * Decimal(gpu_count)
    ancillary_rate = Decimal("0")
    if "ancillary_costs" in live_inputs:
        ancillary_rate = _validate_ancillary_costs(live_inputs["ancillary_costs"])
    rate = gpu_rate + ancillary_rate
    expected_cost = rate * Decimal(int(estimate["expected_minutes"])) / Decimal(60)
    requested_maximum_minutes = int(estimate["maximum_minutes"])
    requested_maximum_cost = rate * Decimal(requested_maximum_minutes) / Decimal(60)

    if requested_maximum_cost > cap:
        raise ValueError(f"maximum cost {_money(requested_maximum_cost)} exceeds manifest cap {_money(cap)}")
    requested_final_balance = balance - requested_maximum_cost
    if requested_final_balance < reserve:
        raise ValueError("projected final balance is below the declared reserve")

    manifest_deadline = int(resource["terminate_after_minutes"])
    if requested_maximum_minutes > manifest_deadline:
        raise ValueError("live_inputs.estimate.maximum_minutes exceeds manifest termination deadline")
    cap_affordable_minutes = int(
        (cap * Decimal(60) / rate).to_integral_value(rounding=ROUND_FLOOR)
    )
    reserve_affordable_minutes = int(
        ((balance - reserve) * Decimal(60) / rate).to_integral_value(rounding=ROUND_FLOOR)
    )
    maximum_billable_minutes = min(
        requested_maximum_minutes,
        manifest_deadline,
        cap_affordable_minutes,
        reserve_affordable_minutes,
    )
    if maximum_billable_minutes < 1:
        raise ValueError("approved budget cannot afford a one-minute provider deletion deadline")
    maximum_cost = rate * Decimal(maximum_billable_minutes) / Decimal(60)
    projected_final_balance = balance - maximum_cost

    guards = {
        "soft_stop_usd": _money(cap * Decimal("0.75")),
        "evidence_teardown_usd": _money(cap * Decimal("0.85")),
        "provider_delete_deadline_minutes": maximum_billable_minutes,
    }
    if local_guard_required:
        retry_delays = guard_policy["delete_retry_delays_seconds"]
        teardown_horizon_seconds = (
            int(guard_policy["arming_timeout_seconds"])
            + int(guard_policy["poll_interval_seconds"])
            + sum(int(delay) for delay in retry_delays)
            + 4 * len(retry_delays) * int(guard_policy["cli_timeout_seconds"])
        )
        local_trigger_seconds = maximum_billable_minutes * 60 - teardown_horizon_seconds
        if local_trigger_seconds < 1:
            raise ValueError("local watchdog teardown horizon consumes the entire budget window")
        guards.update(
            {
                "mode": "local_only_acknowledged",
                "watchdog_processes": 2,
                "hourly_usd_exact": format(rate, "f"),
                "launcher": guard_policy["launcher"],
                "clock": guard_policy["clock"],
                "poll_interval_seconds": guard_policy["poll_interval_seconds"],
                "cli_timeout_seconds": guard_policy["cli_timeout_seconds"],
                "arming_timeout_seconds": guard_policy["arming_timeout_seconds"],
                "heartbeat_stale_after_seconds": guard_policy["heartbeat_stale_after_seconds"],
                "teardown_horizon_seconds": teardown_horizon_seconds,
                "local_teardown_trigger_seconds": local_trigger_seconds,
                "delete_retry_delays_seconds": _plain_json_copy(
                    guard_policy["delete_retry_delays_seconds"]
                ),
                "start_no_new_arms_at_fraction": guard_policy[
                    "start_no_new_arms_at_fraction"
                ],
                "teardown_at_fraction": guard_policy["teardown_at_fraction"],
                "arm_order": _plain_json_copy(guard_policy["arm_order"]),
                "watchdog_script_sha256": guard_policy["watchdog_script_sha256"],
                "launcher_script_sha256": guard_policy["launcher_script_sha256"],
                "risk_acknowledgment": "accepted",
            }
        )

    plan = {
        "schema_version": 1,
        "execution_ready": execution_ready,
        "manifest": _plain_json_copy(manifest),
        "live_inputs": _plain_json_copy(live_inputs),
        "budget": {
            "max_usd": _money(cap),
            "minimum_final_balance_usd": _money(reserve),
        },
        "cost": {
            "gpu_hourly_usd": _money(gpu_rate),
            "ancillary_hourly_usd": _money(ancillary_rate),
            "hourly_usd": _money(rate),
            "expected_usd": _money(expected_cost),
            "maximum_billable_minutes": maximum_billable_minutes,
            "maximum_usd": _money(maximum_cost),
            "projected_final_balance_usd": _money(projected_final_balance),
        },
        "guards": guards,
    }
    _validate_json_tree(plan)
    return plan


def _validate_json_tree(
    value: object,
    path: str = "plan",
    *,
    depth: int = 0,
    active: set[int] | None = None,
) -> None:
    if depth > _MAX_CANONICAL_DEPTH:
        raise PlanValidationError(f"{path} exceeds maximum nesting depth")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PlanValidationError(f"{path} is not valid UTF-8 text") from exc
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if active is None:
        active = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise PlanValidationError(f"{path} contains a cycle")
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise PlanValidationError(f"{path} field names must be strings")
                _validate_json_tree(
                    item,
                    f"{path}.{key}",
                    depth=depth + 1,
                    active=active,
                )
        finally:
            active.remove(identity)
        return
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise PlanValidationError(f"{path} contains a cycle")
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _validate_json_tree(
                    item,
                    f"{path}[{index}]",
                    depth=depth + 1,
                    active=active,
                )
        finally:
            active.remove(identity)
        return
    raise PlanValidationError(f"{path} contains an unsupported value")


def _validate_approval_plan(plan: Mapping[str, object]) -> None:
    try:
        _validate_json_tree(plan)
        root = _shape(
            plan,
            "plan",
            required={"schema_version", "execution_ready", "manifest", "live_inputs", "budget", "cost", "guards"},
            optional={"metadata"},
        )
        if "metadata" in root:
            metadata = _shape(
                root["metadata"],
                "plan.metadata",
                required={"compiled_at"},
            )
            _string(metadata["compiled_at"], "plan.metadata.compiled_at", maximum=128)

        expected = compile_plan(
            _mapping(root["manifest"], "plan.manifest"),
            _mapping(root["live_inputs"], "plan.live_inputs"),
        )
        actual_core = {key: root[key] for key in expected}
        if actual_core != expected:
            raise PlanValidationError("plan does not match compiler-derived values")
    except PlanValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanValidationError(str(exc)) from exc


def _canonical_payload(plan: Mapping[str, object]) -> dict[str, object]:
    _validate_approval_plan(plan)
    return {key: plan[key] for key in ("schema_version", "execution_ready", "manifest", "live_inputs", "budget", "cost", "guards")}


def canonical_bytes(plan: Mapping[str, object]) -> bytes:
    """Return stable UTF-8 JSON bytes, excluding transient timestamps."""

    plan = _mapping(plan, "plan")
    normalized = _canonical_payload(plan)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def plan_digest(plan: Mapping[str, object]) -> str:
    """Return the SHA-256 hex digest of the canonical plan."""

    return hashlib.sha256(canonical_bytes(plan)).hexdigest()


def approval_phrase(plan: Mapping[str, object]) -> str:
    """Return the only response that authorizes this exact plan and cap."""

    _validate_approval_plan(plan)
    if plan["execution_ready"] is not True:
        raise PlanValidationError("plan is not execution-ready")
    budget = _mapping(plan["budget"], "plan.budget")
    return f"APPROVE RUNPOD BENCHMARK {plan_digest(plan)} MAX_USD {budget['max_usd']}"


def validate_approval(plan: Mapping[str, object], response: str) -> bool:
    """Accept only a byte-for-byte exact digest-and-cap approval phrase."""

    if not isinstance(response, str):
        return False
    try:
        return response == approval_phrase(plan)
    except PlanValidationError:
        return False
