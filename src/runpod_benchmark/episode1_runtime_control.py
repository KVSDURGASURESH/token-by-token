"""Concrete SSH-backed RuntimeControl for the Episode 1 remote helper."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from collections.abc import Mapping
from typing import Any

from .episode1_orchestrator import Allocation, LifecycleError, RuntimeHandle
from .episode1 import canonical_json
from .episode1_remote import SshRemoteExecutor
from .gpu_process_ownership import OwnershipError, verify as verify_gpu_process_ownership


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ATTEST_KEYS = {
    "schema_version", "gpu_uuid", "gpu_pci", "gpu_name", "driver_version",
    "boot_id", "cuda_runtime_version", "nvrtc_version",
    "gpu_count", "gpu_total_memory_mib", "compute_capability",
    "used_memory_mib", "compute_process_count", "build_attestation_sha256",
    "installed_material_sha256", "installed_runtime_builds",
    "gpu_process_pid_domain",
}

_MODEL = "Qwen/Qwen2.5-32B-Instruct"
_REVISION = "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd"
_NATIVE_KERNEL_REASON = "humming_not_selected_by_frozen_runtime_path"


def _expected_argv(runtime: str) -> list[str]:
    if runtime == "vllm-0.29.0":
        return [
            "vllm", "serve", _MODEL, f"--revision={_REVISION}",
            f"--tokenizer-revision={_REVISION}", "--dtype=bfloat16",
            "--kv-cache-dtype=bfloat16", "--gpu-memory-utilization=0.90",
            "--generation-config=vllm", "--max-model-len=4096",
            "--max-num-seqs=4", "--no-enable-prefix-caching",
            "--host=127.0.0.1", "--port=8000",
        ]
    if runtime == "sglang-0.5.20":
        return [
            "python", "-m", "sglang.launch_server", f"--model-path={_MODEL}",
            f"--revision={_REVISION}", "--dtype=bfloat16",
            "--kv-cache-dtype=bfloat16", "--mem-fraction-static=0.90",
            "--sampling-defaults=openai", "--context-length=4096",
            "--max-running-requests=4", "--disable-radix-cache", "--enable-metrics",
            "--host=127.0.0.1", "--port=8000",
        ]
    raise LifecycleError("runtime has no frozen launch argv")


def _argv_sha256(runtime: str) -> str:
    return hashlib.sha256(canonical_json(_expected_argv(runtime)).encode()).hexdigest()


def _exact_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LifecycleError(f"remote {label} is invalid")
    return value


def _closed(value: Mapping[str, Any], keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise LifecycleError(f"remote {label} response is open or incomplete")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise LifecycleError(f"remote {label} is not a SHA-256 digest")
    return value


def _version(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
        raise LifecycleError(f"remote {label} version is invalid")
    return tuple(int(item) for item in value.split("."))


class SshRuntimeControl:
    """Invoke only the fixed remote helper and validate every response closed."""

    def __init__(self, executor: SshRemoteExecutor, *, helper: str = "/usr/local/bin/episode1-control") -> None:
        if not helper.startswith("/"):
            raise ValueError("remote helper path must be absolute")
        self.executor = executor
        self.helper = helper
        self._state_lock = threading.RLock()
        self._attested_gpu_uuid: str | None = None
        self._attested_boot_id: str | None = None
        self._gpu_process_pid_domain: str | None = None
        self._process_identities: dict[str, tuple[int, int]] = {}

    def _sync_clock(self, *, deadline_monotonic: float) -> tuple[float, float]:
        before = time.monotonic()
        remaining = deadline_monotonic - before
        if not math.isfinite(remaining) or remaining <= 0:
            raise LifecycleError("remote clock synchronization deadline is exhausted")
        response = _closed(self.executor.run_json(
            [self.helper, "clock"],
            input_value={"schema_version": "episode1.remote-clock-request.v1"},
            timeout_seconds=min(5, remaining), deadline_monotonic=deadline_monotonic,
        ), {"schema_version", "remote_monotonic", "remote_wall_time_ns"}, "clock synchronization")
        after = time.monotonic()
        if response["schema_version"] != "episode1.remote-clock.v1":
            raise LifecycleError("remote clock schema is unsupported")
        remote = response["remote_monotonic"]
        wall = response["remote_wall_time_ns"]
        if (
            isinstance(remote, bool) or not isinstance(remote, (int, float))
            or not math.isfinite(float(remote))
            or isinstance(wall, bool) or not isinstance(wall, int) or wall <= 0
        ):
            raise LifecycleError("remote clock evidence is invalid")
        midpoint = before + (after - before) / 2
        return float(remote) - midpoint, (after - before) / 2

    def _call(
        self, action: str, value: Mapping[str, Any], *, deadline_monotonic: float,
        timeout_seconds: float = 30,
    ) -> Mapping[str, Any]:
        # Refresh the mapping for every operation: independent host monotonic
        # clocks may drift, and a cached offset has no defensible age bound.
        remote_offset, clock_uncertainty = self._sync_clock(
            deadline_monotonic=deadline_monotonic
        )
        local_now = time.monotonic()
        remaining = deadline_monotonic - local_now
        if not math.isfinite(remaining) or remaining <= 0:
            raise LifecycleError("remote operation deadline is exhausted")
        bounded = min(timeout_seconds, remaining)
        # The remote deadline and declared timeout must describe the same
        # bounded interval.  Mapping the full caller deadline while declaring
        # a shorter timeout creates an invalid request at the remote gate.
        remote_deadline = local_now + bounded + remote_offset - clock_uncertainty
        return self.executor.run_json(
            [self.helper, action],
            input_value={
                **value, "operation_timeout_seconds": bounded,
                "operation_deadline_monotonic": remote_deadline,
            },
            timeout_seconds=bounded,
            deadline_monotonic=deadline_monotonic,
        )

    def attest_allocation(
        self, allocation: Allocation, plan: Mapping[str, Any], *, deadline_monotonic: float
    ) -> Mapping[str, Any]:
        value = _closed(self._call("attest", {
            "schema_version": "episode1.remote-attest-request.v1",
            "plan_sha256": plan["plan_sha256"],
        }, deadline_monotonic=deadline_monotonic), _ATTEST_KEYS, "attestation")
        if value["schema_version"] != "episode1.remote-attestation.v1":
            raise LifecycleError("remote attestation schema is unsupported")
        strings = (
            "gpu_uuid", "gpu_pci", "gpu_name", "driver_version", "boot_id",
            "cuda_runtime_version", "nvrtc_version", "compute_capability",
        )
        if any(not isinstance(value[key], str) or not value[key] for key in strings):
            raise LifecycleError("remote attestation has missing identity strings")
        if value["gpu_name"] != allocation.gpu:
            raise LifecycleError("remote GPU name differs from provider readback")
        if value["gpu_count"] != allocation.gpu_count or value["gpu_count"] != 1:
            raise LifecycleError("remote GPU count differs from the one-device plan")
        if value["gpu_total_memory_mib"] != 81559:
            raise LifecycleError("remote H100 memory does not match the frozen 80 GB device")
        if value["compute_capability"] != "9.0":
            raise LifecycleError("remote GPU compute capability is not Hopper 9.0")
        if _version(value["driver_version"], "driver") < (580, 65, 6):
            raise LifecycleError("remote NVIDIA driver is below the CUDA 13.0 floor")
        if _version(value["cuda_runtime_version"], "CUDA runtime")[:2] != (13, 0):
            raise LifecycleError("remote CUDA runtime is not the frozen 13.0 line")
        if _version(value["nvrtc_version"], "NVRTC")[:2] != (13, 0):
            raise LifecycleError("remote NVRTC is not the frozen 13.0 line")
        images = {item["derived_image_digest"] for item in plan["runtime_builds"]}
        if len(images) != 1 or None in images:
            raise LifecycleError("approved runtime builds do not bind one image digest")
        approved_image = next(iter(images))
        if not allocation.requested_image_reference.endswith("@" + approved_image):
            raise LifecycleError("provider request differs from the approved image digest")
        if allocation.provider_image_reference != allocation.requested_image_reference:
            raise LifecycleError("provider image readback differs from the requested digest reference")
        _exact_nonnegative_int(value["used_memory_mib"], "used GPU memory")
        if _exact_nonnegative_int(value["compute_process_count"], "compute process count") != 0:
            raise LifecycleError("remote allocation has compute processes before runtime start")
        _digest(value["build_attestation_sha256"], "build attestation")
        expected_attestations = {
            item["build_attestation_sha256"] for item in plan["runtime_builds"]
        }
        if len(expected_attestations) != 1 or value["build_attestation_sha256"] not in expected_attestations:
            raise LifecycleError("remote build attestation differs from the approved image evidence")
        _digest(value["installed_material_sha256"], "installed material")
        installed = value["installed_runtime_builds"]
        if not isinstance(installed, list) or len(installed) != 2:
            raise LifecycleError("remote installed runtime build list is incomplete")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(installed):
            record = _closed(item, {
                "runtime", "build_spec_sha256", "dependency_lock_sha256", "launcher_sha256",
            }, f"installed runtime build {index}")
            if record["runtime"] not in {"vllm-0.29.0", "sglang-0.5.20"}:
                raise LifecycleError("remote installed runtime identity is invalid")
            for key in ("build_spec_sha256", "dependency_lock_sha256", "launcher_sha256"):
                _digest(record[key], f"installed runtime {key}")
            normalized.append(dict(record))
        expected = [{key: item[key] for key in (
            "runtime", "build_spec_sha256", "dependency_lock_sha256", "launcher_sha256"
        )} for item in plan["runtime_builds"]]
        if sorted(normalized, key=lambda item: item["runtime"]) != sorted(expected, key=lambda item: item["runtime"]):
            raise LifecycleError("remote installed build material differs from the approved plan")
        actual_material = hashlib.sha256(canonical_json(
            sorted(normalized, key=lambda item: item["runtime"])
        ).encode()).hexdigest()
        if value["installed_material_sha256"] != actual_material:
            raise LifecycleError("remote installed material aggregate is invalid")
        if value["gpu_process_pid_domain"] != "proc_pid":
            raise LifecycleError("remote GPU process PID domain is unsupported")
        with self._state_lock:
            self._attested_gpu_uuid = value["gpu_uuid"]
            self._attested_boot_id = value["boot_id"]
            self._gpu_process_pid_domain = value["gpu_process_pid_domain"]
        return dict(value)

    def start(
        self, allocation: Allocation, block: Mapping[str, Any], plan: Mapping[str, Any],
        *, deadline_monotonic: float,
    ) -> RuntimeHandle:
        del allocation
        runtime_build = next(
            (item for item in plan["runtime_builds"] if item["runtime"] == block["runtime"]), None
        )
        if runtime_build is None:
            raise LifecycleError("block runtime has no bound build")
        response = _closed(self._call("start", {
            "schema_version": "episode1.remote-start-request.v1",
            "plan_sha256": plan["plan_sha256"], "block": dict(block),
            "runtime_build": dict(runtime_build),
        }, deadline_monotonic=deadline_monotonic), {
            "schema_version", "private_process_id", "runtime", "block_id",
            "process_pid", "process_start_ticks",
            "argv_sha256", "started_monotonic_ns", "kernel_path",
            "kernel_evidence_sha256", "kernel_unavailable_reason",
        }, "start")
        if (
            response["schema_version"] != "episode1.remote-start.v1"
            or response["runtime"] != block["runtime"]
            or response["block_id"] != block["block_id"]
            or not isinstance(response["private_process_id"], str)
            or not response["private_process_id"]
            or isinstance(response["started_monotonic_ns"], bool)
            or not isinstance(response["started_monotonic_ns"], int)
            or response["started_monotonic_ns"] <= 0
        ):
            raise LifecycleError("remote start response does not bind the requested block")
        if response["argv_sha256"] != _argv_sha256(block["runtime"]):
            raise LifecycleError("remote runtime argv differs from the frozen launch command")
        if not isinstance(response["kernel_path"], str):
            raise LifecycleError("remote kernel path is invalid")
        if response["kernel_path"] == "native_runtime":
            if response["kernel_evidence_sha256"] is not None or response["kernel_unavailable_reason"] != _NATIVE_KERNEL_REASON:
                raise LifecycleError("native kernel path lacks an explicit Humming non-use reason")
        elif response["kernel_path"] == "humming_nvrtc":
            _digest(response["kernel_evidence_sha256"], "Humming kernel evidence")
            if response["kernel_unavailable_reason"] is not None:
                raise LifecycleError("selected Humming path cannot be marked unavailable")
        else:
            raise LifecycleError("remote kernel path is unsupported")
        process_pid = _exact_nonnegative_int(response["process_pid"], "runtime process PID")
        process_start_ticks = _exact_nonnegative_int(
            response["process_start_ticks"], "runtime process start ticks"
        )
        if process_pid == 0 or process_start_ticks == 0:
            raise LifecycleError("remote runtime process identity is invalid")
        with self._state_lock:
            self._process_identities[response["private_process_id"]] = (
                process_pid, process_start_ticks
            )
        return RuntimeHandle(
            response["private_process_id"], response["runtime"], response["block_id"],
            process_pid, process_start_ticks,
        )

    def sample_system(
        self, allocation: Allocation, plan: Mapping[str, Any], block: Mapping[str, Any],
        handle: RuntimeHandle | None, phase: str, run_id: str, attempt_id: str,
        startup_attempt_id: str, *,
        deadline_monotonic: float, slot_kind: str = "periodic",
    ) -> Mapping[str, Any]:
        if slot_kind not in {"periodic", "measurement_start_boundary", "measurement_end_boundary"}:
            raise ValueError("invalid system sample slot kind")
        with self._state_lock:
            attested_boot_id = self._attested_boot_id
        if attested_boot_id is None:
            raise LifecycleError("system sampling requires a retained boot attestation")
        client_call_started_ns = time.monotonic_ns()
        response = _closed(self._call("sample", {
            "schema_version": "episode1.remote-sample-request.v1",
            "plan_sha256": plan["plan_sha256"],
            "binding": {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "block": str(block["block_id"]),
                "clock_domain": "linux-clock-monotonic",
                "source_boot_id": attested_boot_id,
            },
            "startup_attempt_id": startup_attempt_id,
            "phase": phase,
            "slot_kind": slot_kind,
            "handle": None if handle is None else handle.__dict__,
        }, deadline_monotonic=deadline_monotonic, timeout_seconds=2), {
            "schema_version", "record", "source_sha256",
        }, "system sample")
        client_call_completed_ns = time.monotonic_ns()
        if response["schema_version"] != "episode1.remote-sample.v1":
            raise LifecycleError("remote system sample schema is unsupported")
        source_sha256 = _digest(response["source_sha256"], "system sample source")
        record = response["record"]
        if not isinstance(record, Mapping):
            raise LifecycleError("remote system sample record is invalid")
        expected = hashlib.sha256((canonical_json(record) + "\n").encode()).hexdigest()
        if source_sha256 != expected:
            raise LifecycleError("remote system sample source hash is invalid")
        binding = record.get("binding")
        if (not isinstance(binding, Mapping) or binding.get("source_boot_id") != attested_boot_id
                or binding.get("clock_domain") != "linux-clock-monotonic"
                or record.get("slot_kind") != slot_kind):
            raise LifecycleError("remote system sample binding or slot kind changed")
        result = {"record": dict(record), "source_sha256": source_sha256}
        if slot_kind != "periodic":
            marker = "measurement_start" if slot_kind == "measurement_start_boundary" else "measurement_end"
            result["boundary_receipt"] = {
                "schema_version": "episode1.system-window-boundary.v1",
                "plan_sha256": plan["plan_sha256"],
                "run_id": run_id,
                "attempt_id": attempt_id,
                "block": str(block["block_id"]),
                "runtime": str(block["runtime"]),
                "marker": marker,
                "source_clock_domain": "linux-clock-monotonic",
                "source_boot_id": attested_boot_id,
                "source_sequence": record.get("sequence"),
                "source_record_sha256": source_sha256,
                "source_observed_monotonic_ns": record.get("observed_monotonic_ns"),
                "source_observed_utc_ns": record.get("observed_utc_ns"),
                "source_utc_uncertainty_ns": record.get("clock_uncertainty_ns"),
                "client_clock_domain": "client_monotonic_ns",
                "client_call_started_monotonic_ns": client_call_started_ns,
                "client_call_completed_monotonic_ns": client_call_completed_ns,
            }
        return result

    def observe_process_identity(
        self, handle: RuntimeHandle, *, deadline_monotonic: float
    ) -> tuple[str, str]:
        """Re-observe the live PID/start tuple and listener ownership remotely."""
        response = _closed(self._call("identity", {
            "schema_version": "episode1.remote-identity-request.v1",
            "handle": handle.__dict__,
        }, deadline_monotonic=deadline_monotonic, timeout_seconds=2), {
            "schema_version", "private_process_id", "process_pid",
            "process_start_ticks", "loopback_listener_owned",
        }, "process identity")
        pid = _exact_nonnegative_int(response["process_pid"], "runtime process PID")
        start_ticks = _exact_nonnegative_int(
            response["process_start_ticks"], "runtime process start ticks"
        )
        if (
            response["schema_version"] != "episode1.remote-identity.v1"
            or response["private_process_id"] != handle.private_process_id
            or response["loopback_listener_owned"] is not True
            or pid <= 0 or start_ticks <= 0
            or pid != handle.process_pid
            or start_ticks != handle.process_start_ticks
        ):
            raise LifecycleError("remote runtime process identity changed")
        return f"pid:{pid}", f"ticks:{start_ticks}"

    def wait_ready_and_probe(
        self, allocation: Allocation, handle: RuntimeHandle, plan: Mapping[str, Any],
        *, deadline_monotonic: float,
    ) -> Mapping[str, Any]:
        del allocation
        response = _closed(self._call("probe", {
            "schema_version": "episode1.remote-handle-request.v1",
            "plan_sha256": plan["plan_sha256"], "handle": handle.__dict__,
        }, deadline_monotonic=deadline_monotonic), {
            "schema_version", "private_process_id", "exact_tokens", "effective_flags",
            "loopback_only", "probe_sha256", "token_evidence_sha256",
            "effective_config_sha256", "argv_sha256", "gpu_process_ownership",
        }, "probe")
        if (
            response["schema_version"] != "episode1.remote-probe.v1"
            or response["private_process_id"] != handle.private_process_id
            or response["exact_tokens"] is not True
            or response["effective_flags"] is not True
            or response["loopback_only"] is not True
        ):
            raise LifecycleError("remote readiness probe did not prove the frozen runtime")
        if response["argv_sha256"] != _argv_sha256(handle.runtime):
            raise LifecycleError("probe argv evidence differs from the frozen launch command")
        if response["effective_config_sha256"] != _argv_sha256(handle.runtime):
            raise LifecycleError("effective runtime configuration differs from the frozen launch command")
        for key in ("probe_sha256", "token_evidence_sha256", "effective_config_sha256"):
            _digest(response[key], key)
        with self._state_lock:
            identity = self._process_identities.get(handle.private_process_id)
            attested_gpu_uuid = self._attested_gpu_uuid
            gpu_process_pid_domain = self._gpu_process_pid_domain
        if identity is None or attested_gpu_uuid is None or gpu_process_pid_domain is None:
            raise LifecycleError("GPU process ownership lacks attested runtime identity")
        try:
            verify_gpu_process_ownership(
                response["gpu_process_ownership"],
                root_pid=identity[0], root_start_ticks=identity[1],
                expected_gpu_uuid=attested_gpu_uuid,
                pid_domain=gpu_process_pid_domain,
            )
        except OwnershipError as exc:
            raise LifecycleError("remote GPU process ownership evidence is invalid") from exc
        return dict(response)

    def stop(
        self, allocation: Allocation, handle: RuntimeHandle, *, deadline_monotonic: float
    ) -> Mapping[str, Any]:
        del allocation
        response = _closed(self._call("stop", {
            "schema_version": "episode1.remote-handle-request.v1",
            "handle": handle.__dict__,
        }, deadline_monotonic=deadline_monotonic), {
            "schema_version", "private_process_id", "reaped", "endpoint_closed",
            "sigkill_used",
        }, "stop")
        if (
            response["schema_version"] != "episode1.remote-stop.v1"
            or response["private_process_id"] != handle.private_process_id
            or response["reaped"] is not True
            or response["endpoint_closed"] is not True
            or not isinstance(response["sigkill_used"], bool)
        ):
            raise LifecycleError("remote runtime stop is incomplete")
        return dict(response)

    def descendants_absent(
        self, allocation: Allocation, handle: RuntimeHandle, *, deadline_monotonic: float
    ) -> bool:
        del allocation
        response = _closed(self._call("status", {
            "schema_version": "episode1.remote-handle-request.v1", "handle": handle.__dict__,
        }, deadline_monotonic=deadline_monotonic), {
            "schema_version", "private_process_id", "descendants_absent", "endpoint_closed",
        }, "status")
        return (
            response["schema_version"] == "episode1.remote-status.v1"
            and response["private_process_id"] == handle.private_process_id
            and response["descendants_absent"] is True
            and response["endpoint_closed"] is True
        )

    def memory_recovered(
        self, allocation: Allocation, baseline: Mapping[str, Any], *, deadline_monotonic: float
    ) -> bool:
        del allocation
        response = _closed(self._call("memory", {
            "schema_version": "episode1.remote-memory-request.v1", "baseline": dict(baseline),
        }, deadline_monotonic=deadline_monotonic), {
            "schema_version", "gpu_uuid", "used_memory_mib", "compute_process_count",
        }, "memory")
        if response["schema_version"] != "episode1.remote-memory.v1" or response["gpu_uuid"] != baseline["gpu_uuid"]:
            return False
        observed = _exact_nonnegative_int(response["used_memory_mib"], "used GPU memory")
        processes = _exact_nonnegative_int(response["compute_process_count"], "compute process count")
        base = _exact_nonnegative_int(baseline.get("used_memory_mib"), "baseline GPU memory")
        return processes == 0 and observed <= base + 64

    def cleanup_failed_start(
        self, allocation: Allocation, block: Mapping[str, Any], baseline: Mapping[str, Any],
        *, deadline_monotonic: float,
    ) -> Mapping[str, Any]:
        del allocation
        response = _closed(self._call("cleanup-failed-start", {
            "schema_version": "episode1.remote-cleanup-request.v1",
            "block": dict(block), "baseline": dict(baseline),
        }, deadline_monotonic=deadline_monotonic), {
            "schema_version", "descendants_absent", "endpoint_closed", "gpu_uuid",
            "used_memory_mib", "compute_process_count",
        }, "failed-start cleanup")
        memory_recovered = (
            response["gpu_uuid"] == baseline["gpu_uuid"]
            and _exact_nonnegative_int(response["compute_process_count"], "compute process count") == 0
            and _exact_nonnegative_int(response["used_memory_mib"], "used GPU memory")
            <= _exact_nonnegative_int(baseline.get("used_memory_mib"), "baseline GPU memory") + 64
        )
        if response["schema_version"] != "episode1.remote-cleanup.v1" or response["descendants_absent"] is not True or response["endpoint_closed"] is not True or not memory_recovered:
            raise LifecycleError("remote failed-start cleanup is incomplete")
        return {**dict(response), "memory_recovered": True}
