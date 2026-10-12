"""Episode 1 one-allocation lifecycle orchestration.

All side effects are injected.  Importing this module, compiling a plan, or
constructing an orchestrator performs no provider or remote operation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .episode1 import CELLS, RUNTIMES, canonical_json
from .episode1_authorization import verify_authorization_receipt
from .episode1_execution import verify_execution_candidate, verify_fresh_for_create
from .episode1_guard import GuardBinding, make_guard_binding


class CreateOutcomeUnknown(RuntimeError):
    """The provider may have created the uniquely named allocation."""


class LifecycleError(RuntimeError):
    """A fail-closed lifecycle or evidence gate failed."""


@dataclass(frozen=True)
class Allocation:
    private_id: str
    unique_name: str
    ssh_host: str
    ssh_public_port: int
    container_ssh_port: int
    ownership_token: str
    gpu: str
    gpu_count: int
    data_center_id: str
    cloud_type: str
    container_disk_gb: int
    volume_gb: int
    volume_mount_path: str
    requested_image_reference: str
    provider_image_reference: str
    billing_started_monotonic: float | None
    resource_identity_sha256: str | None = None
    immutable_allocation_sha256: str | None = None


@dataclass(frozen=True)
class DeletionAuthority:
    private_id: str
    unique_name: str
    ownership_token: str
    billing_started_monotonic: float | None


@dataclass(frozen=True)
class RuntimeHandle:
    private_process_id: str
    runtime: str
    block_id: str
    process_pid: int | None = None
    process_start_ticks: int | None = None


class ProviderControl(Protocol):
    def bind_cleanup_owner(self, callback: Callable[[DeletionAuthority], None]) -> None: ...
    def create_allocation(
        self, *, unique_name: str, ownership_token: str, plan: Mapping[str, Any],
        deadline_monotonic: float,
    ) -> Allocation: ...
    def recover_exact_name(self, unique_name: str, *, deadline_monotonic: float) -> Sequence[Allocation]: ...
    def read_allocation(self, allocation: Allocation, *, deadline_monotonic: float) -> Allocation: ...
    def current_exposure_fraction(
        self, allocation: Allocation, plan: Mapping[str, Any], *, deadline_monotonic: float
    ) -> float: ...
    def make_cleanup_observation_binding(
        self, allocation: Allocation, *, run_id: str, attempt_id: str,
        plan_sha256: str, resource_identity_sha256: str,
        original_deadline_monotonic_ns: int,
    ) -> Any: ...
    def delete_allocation_observed(
        self, allocation: Allocation, *, binding: Any, delete_attempt: int,
        deadline_monotonic: float,
    ) -> Any: ...
    def inventory_absent_observed(
        self, allocation: Allocation, *, binding: Any, delete_attempt: int,
        deadline_monotonic: float,
    ) -> Any: ...
    def direct_not_found_observed(
        self, allocation: Allocation, *, binding: Any, delete_attempt: int,
        deadline_monotonic: float,
    ) -> Any: ...


class GuardControl(Protocol):
    def arm(
        self, binding: GuardBinding, *, deadline_monotonic: float
    ) -> Mapping[str, Any]: ...
    def healthy(self, binding: GuardBinding, *, deadline_monotonic: float) -> bool: ...


class RuntimeControl(Protocol):
    def attest_allocation(
        self, allocation: Allocation, plan: Mapping[str, Any], *, deadline_monotonic: float
    ) -> Mapping[str, Any]: ...
    def start(
        self, allocation: Allocation, block: Mapping[str, Any], plan: Mapping[str, Any],
        *, deadline_monotonic: float,
    ) -> RuntimeHandle: ...
    def wait_ready_and_probe(
        self, allocation: Allocation, handle: RuntimeHandle, plan: Mapping[str, Any],
        *, deadline_monotonic: float,
    ) -> Mapping[str, Any]: ...
    def stop(
        self, allocation: Allocation, handle: RuntimeHandle, *, deadline_monotonic: float
    ) -> Mapping[str, Any]: ...
    def descendants_absent(
        self, allocation: Allocation, handle: RuntimeHandle, *, deadline_monotonic: float
    ) -> bool: ...
    def memory_recovered(
        self, allocation: Allocation, baseline: Mapping[str, Any], *, deadline_monotonic: float
    ) -> bool: ...
    def cleanup_failed_start(
        self, allocation: Allocation, block: Mapping[str, Any], baseline: Mapping[str, Any],
        *, deadline_monotonic: float,
    ) -> Mapping[str, Any]: ...
    def sample_system(
        self, allocation: Allocation, plan: Mapping[str, Any], block: Mapping[str, Any],
        handle: RuntimeHandle | None, phase: str, run_id: str, attempt_id: str,
        startup_attempt_id: str, *,
        deadline_monotonic: float, slot_kind: str = "periodic",
    ) -> Mapping[str, Any]: ...


class BlockTelemetryControl(Protocol):
    """Own one block's retained telemetry sources and final capture envelope."""

    run_attempt_id: str
    startup_attempt_id: str
    block_attempt: int
    def start(self, handle: RuntimeHandle, *, deadline_monotonic: float) -> None: ...
    def system_sample(self, value: Mapping[str, Any]) -> None: ...
    def observe_request(self, value: Mapping[str, Any], *, warmup: bool) -> None: ...
    def finish(self, *, deadline_monotonic: float) -> None: ...
    def abort(self, *, deadline_monotonic: float) -> None: ...


TelemetryFactory = Callable[
    [Mapping[str, Any], Mapping[str, Any], str, str, int, Allocation, Any],
    BlockTelemetryControl,
]

RuntimeFactory = Callable[[Allocation], RuntimeControl]
CellFactory = Callable[[Allocation], "CellDriver"]


class RunTimingContext(Protocol):
    """Pre-create clock boundary shared with the durable capture contract."""

    plan_sha256: str
    original_t0_monotonic: float
    hard_deadline_monotonic: float
    teardown_deadline_monotonic: float
    clock_domain: str


class CellDriver(Protocol):
    def start(self, *, deadline_monotonic: float) -> None: ...
    def run_cell(
        self,
        *,
        allocation: Allocation,
        block: Mapping[str, Any],
        cell: Mapping[str, Any],
        warmup: bool,
        evidence_class: str,
        cancel_event: threading.Event,
        record: Callable[[Mapping[str, Any]], None],
        request_lifecycle: Callable[[Mapping[str, Any]], None] | None,
        deadline_monotonic: float,
    ) -> Mapping[str, Any]: ...
    def close(self, *, deadline_monotonic: float) -> None: ...


class CaptureControl(Protocol):
    contract: Any
    def prepare(self, plan: Mapping[str, Any], unique_name: str, ownership_token: str) -> None: ...
    def owned(
        self, authority: DeletionAuthority, plan: Mapping[str, Any], *,
        cleanup_deadline_monotonic: float,
    ) -> None: ...
    def start(
        self, allocation: Allocation, plan: Mapping[str, Any], *, cleanup_deadline_monotonic: float
    ) -> None: ...
    def boundary(self, event: str, details: Mapping[str, Any]) -> None: ...
    def request_lifecycle(self, value: Mapping[str, Any]) -> None: ...
    def request(self, value: Mapping[str, Any]) -> None: ...
    def telemetry(self, value: Mapping[str, Any]) -> None: ...
    def system_source(self, value: Mapping[str, Any]) -> None: ...
    def block_start(
        self, block_id: str, runtime: str, *, block_attempt: int,
        startup_attempt_id_sha256: str, process_id_sha256: str,
        process_start_identity_sha256: str, image_digest: str,
    ) -> None: ...
    def startup_failed(
        self, block_id: str, runtime: str, *, block_attempt: int,
        startup_attempt_id_sha256: str, process_identity_sha256: str,
        failure_stage: str,
    ) -> None: ...
    def failed_start_cleanup(
        self, block_id: str, runtime: str, *, block_attempt: int,
        startup_attempt_id_sha256: str, process_identity_sha256: str,
        descendants_absent: bool, memory_recovered: bool,
    ) -> None: ...
    def cell_complete(
        self, block_id: str, cell_id: str, *, warmup: bool,
        startup_attempt_id_sha256: str, process_identity_sha256: str,
    ) -> None: ...
    def block_complete(
        self, block_id: str, runtime: str, *, descendants_absent: bool,
        memory_recovered: bool, startup_attempt_id_sha256: str,
        process_identity_sha256: str,
    ) -> None: ...
    def export_essential(self, *, deadline_monotonic: float) -> None: ...
    def deletion_verified(
        self, *, attempts: int, acknowledged: bool, inventory_absent: bool,
        direct_not_found: bool, attempt_evidence: Sequence[Mapping[str, Any]],
        provider_evidence: Sequence[Mapping[str, Any]], delete_response: bytes,
        inventory_response: bytes, direct_response: bytes,
    ) -> None: ...
    def cleanup_attempt_observed(
        self, *, delete_attempt: int, operation: str, observation: Any | None,
        error_type: str | None,
    ) -> None: ...
    def failed_telemetry_source(
        self, *, block_id: str, runtime: str, source_kind: str,
        source_bytes: bytes, reason: str,
    ) -> None: ...
    def settlement_observed(
        self, *, status: str, response: bytes, observed_total_usd: str | None = None,
        reason: str | None = None,
    ) -> None: ...
    def close(self) -> None: ...


class PrivateEvidenceWriter:
    """Append-only private JSONL evidence with a chained lifecycle ledger."""

    def __init__(self, directory: Path, *, clock_ns: Callable[[], int] = time.monotonic_ns) -> None:
        self.directory = directory
        self.clock_ns = clock_ns
        if directory.exists() and any(directory.iterdir()):
            raise ValueError("private evidence directory must be new or empty")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        self._previous = "0" * 64
        self._sequence = 0
        self._lock = threading.Lock()
        self._allocation: Allocation | None = None
        self._request_lifecycle: dict[str, tuple[str, str, int, str]] = {}

    def prepare(self, plan: Mapping[str, Any], unique_name: str, ownership_token: str) -> None:
        self.boundary(
            "allocation-create-intent",
            {
                "plan_sha256": plan["plan_sha256"],
                "unique_name": unique_name,
                "ownership_token_sha256": hashlib.sha256(ownership_token.encode()).hexdigest(),
            },
        )

    def _append(self, name: str, value: Mapping[str, Any]) -> None:
        path = self.directory / name
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (canonical_json(dict(value)) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def start(
        self, allocation: Allocation, plan: Mapping[str, Any], *, cleanup_deadline_monotonic: float
    ) -> None:
        self._allocation = allocation
        self.boundary("allocation-owned", {
            "plan_sha256": plan["plan_sha256"],
            "private_id": allocation.private_id,
            "unique_name": allocation.unique_name,
            "ownership_token_sha256": hashlib.sha256(allocation.ownership_token.encode()).hexdigest(),
            "immutable_allocation": _allocation_facts(allocation),
            "cleanup_deadline_monotonic": cleanup_deadline_monotonic,
        })

    def owned(
        self, authority: DeletionAuthority, plan: Mapping[str, Any], *,
        cleanup_deadline_monotonic: float,
    ) -> None:
        self.boundary("deletion-authority-owned", {
            "plan_sha256": plan["plan_sha256"],
            "private_id": authority.private_id,
            "unique_name": authority.unique_name,
            "ownership_token_sha256": hashlib.sha256(
                authority.ownership_token.encode()
            ).hexdigest(),
            "billing_started_monotonic": authority.billing_started_monotonic,
            "cleanup_deadline_monotonic": cleanup_deadline_monotonic,
        })

    def boundary(self, event: str, details: Mapping[str, Any]) -> None:
        if not isinstance(event, str) or not event:
            raise ValueError("event name is required")
        with self._lock:
            self._sequence += 1
            entry = {
                "schema_version": "episode1.private-ledger.v1",
                "sequence": self._sequence,
                "event": event,
                "monotonic_ns": self.clock_ns(),
                "previous_sha256": self._previous,
                "details": dict(details),
            }
            entry["record_sha256"] = hashlib.sha256(canonical_json(entry).encode()).hexdigest()
            self._append("lifecycle.jsonl", entry)
            self._previous = entry["record_sha256"]

    def request(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._append("requests.jsonl", value)

    def request_lifecycle(self, value: Mapping[str, Any]) -> None:
        expected = {
            "schema_version", "request_id", "block_id", "cell_id", "scheduled_order",
            "clock_domain", "stage", "at_ns",
        }
        if set(value) != expected or value.get("schema_version") != "episode1.request-lifecycle.v1":
            raise ValueError("request lifecycle fact uses an invalid closed schema")
        if value.get("stage") not in {"scheduled", "dispatched", "finalized"}:
            raise ValueError("request lifecycle stage is invalid")
        if value.get("clock_domain") != "client_monotonic_ns":
            raise ValueError("request lifecycle clock domain is invalid")
        for name in ("request_id", "block_id", "cell_id"):
            item = value.get(name)
            if (
                not isinstance(item, str) or not item or len(item) > 256
                or any(ord(character) < 32 for character in item)
            ):
                raise ValueError(f"request lifecycle {name} is invalid")
        scheduled_order = value.get("scheduled_order")
        at_ns = value.get("at_ns")
        if (
            isinstance(scheduled_order, bool) or not isinstance(scheduled_order, int)
            or scheduled_order < 1
        ):
            raise ValueError("request lifecycle scheduled order is invalid")
        if isinstance(at_ns, bool) or not isinstance(at_ns, int) or at_ns < 0:
            raise ValueError("request lifecycle timestamp is invalid")
        with self._lock:
            request_id = value["request_id"]
            prior = self._request_lifecycle.get(request_id)
            identity = (value["block_id"], value["cell_id"], scheduled_order)
            stage = value["stage"]
            if prior is None:
                if stage != "scheduled":
                    raise ValueError("request lifecycle must begin with scheduled")
            else:
                prior_block, prior_cell, prior_order, prior_stage = prior
                if identity != (prior_block, prior_cell, prior_order):
                    raise ValueError("request lifecycle identity changed")
                allowed = (
                    {"dispatched", "finalized"} if prior_stage == "scheduled"
                    else {"finalized"} if prior_stage == "dispatched" else set()
                )
                if stage not in allowed:
                    raise ValueError("request lifecycle stage transition is invalid")
            self._append("request-lifecycle.jsonl", value)
            self._request_lifecycle[request_id] = (*identity, stage)

    def telemetry(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._append("telemetry.jsonl", value)

    def block_start(self, block_id: str, runtime: str, **details: Any) -> None:
        self.boundary("block-start", {"block_id": block_id, "runtime": runtime, **details})

    def startup_failed(self, block_id: str, runtime: str, **details: Any) -> None:
        self.boundary("startup-failed", {"block_id": block_id, "runtime": runtime, **details})

    def failed_start_cleanup(self, block_id: str, runtime: str, **details: Any) -> None:
        self.boundary("failed-start-cleanup", {"block_id": block_id, "runtime": runtime, **details})

    def cell_complete(self, block_id: str, cell_id: str, *, warmup: bool,
                      **details: Any) -> None:
        self.boundary("warmup-complete" if warmup else "cell-complete",
                      {"block_id": block_id, "cell_id": cell_id, **details})

    def block_complete(
        self, block_id: str, runtime: str, *, descendants_absent: bool,
        memory_recovered: bool, startup_attempt_id_sha256: str,
        process_identity_sha256: str,
    ) -> None:
        if descendants_absent is not True or memory_recovered is not True:
            raise LifecycleError("block completion requires verified runtime cleanup")
        self.boundary("block-complete", {
            "block_id": block_id,
            "runtime": runtime,
            "descendants_absent": True,
            "memory_recovered": True,
            "startup_attempt_id_sha256": startup_attempt_id_sha256,
            "process_identity_sha256": process_identity_sha256,
        })

    def export_essential(self, *, deadline_monotonic: float) -> None:
        if self.clock_ns() >= int(deadline_monotonic * 1_000_000_000):
            raise TimeoutError("essential export deadline reached")
        self.boundary("essential-export-complete", {"final_ledger_sha256": self._previous})

    def close(self) -> None:
        self.boundary("capture-closed", {})


class BudgetMonitor:
    """Continuously enforces time/exposure/guard thresholds during active cells."""

    def __init__(
        self,
        *,
        provider: ProviderControl,
        guard: GuardControl,
        allocation: Allocation,
        plan: Mapping[str, Any],
        start_monotonic: float,
        monotonic: Callable[[], float],
        poll_seconds: float,
        hard_deadline: float,
        guard_binding: GuardBinding,
    ) -> None:
        self.provider, self.guard, self.allocation, self.plan = provider, guard, allocation, plan
        self.start_monotonic, self.monotonic, self.poll_seconds = start_monotonic, monotonic, poll_seconds
        self.hard_deadline = hard_deadline
        self.guard_binding = guard_binding
        self.stop_new_arms = threading.Event()
        self.teardown_now = threading.Event()
        self._shutdown = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._poll_lock = threading.Lock()

    def _poll_once(self) -> None:
        lock_deadline = min(self.hard_deadline, self.monotonic() + self.poll_seconds)
        if not self._poll_lock.acquire(
            timeout=max(0.0, lock_deadline - self.monotonic())
        ):
            raise LifecycleError("budget monitor poll serialization deadline reached")
        try:
            elapsed = max(0.0, self.monotonic() - self.start_monotonic)
            lifetime = float(self.plan["budget"]["maximum_lifetime_seconds"])
            time_fraction = elapsed / lifetime
            operation_deadline = min(
                self.hard_deadline, self.monotonic() + self.poll_seconds
            )
            exposure = float(self.provider.current_exposure_fraction(
                self.allocation, self.plan, deadline_monotonic=operation_deadline
            ))
            if not self.guard.healthy(
                self.guard_binding, deadline_monotonic=operation_deadline
            ):
                raise LifecycleError("termination guard health check failed")
            fraction = max(time_fraction, exposure)
            if fraction >= 0.75:
                self.stop_new_arms.set()
            if fraction >= 0.85:
                self.teardown_now.set()
        finally:
            self._poll_lock.release()

    def _run(self) -> None:
        try:
            while not self._shutdown.is_set():
                self._poll_once()
                if self.teardown_now.is_set():
                    return
                if self._shutdown.wait(self.poll_seconds):
                    return
        except BaseException as exc:  # retained and re-raised in the main lifecycle
            self._error = exc
            self.teardown_now.set()

    def start(self) -> None:
        self._poll_once()
        self._thread = threading.Thread(target=self._run, name="episode1-budget-monitor", daemon=True)
        self._thread.start()

    def check_new_work(self) -> None:
        self._poll_once()
        if self._error is not None:
            raise LifecycleError("budget monitor failed") from self._error
        if self.teardown_now.is_set():
            raise LifecycleError("85% teardown threshold reached")
        if self.stop_new_arms.is_set():
            raise LifecycleError("75% no-new-work threshold reached")

    def stop(self, *, deadline_monotonic: float) -> None:
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, deadline_monotonic - self.monotonic()))
            if self._thread.is_alive():
                raise LifecycleError("budget monitor did not stop before the cleanup deadline")


class SystemSamplingLoop:
    """Drive exact remote sampling slots from prestart through final drain."""

    def __init__(
        self, *, runtime: RuntimeControl, allocation: Allocation,
        plan: Mapping[str, Any], block: Mapping[str, Any], run_id: str, attempt_id: str,
        startup_attempt_id: str,
        emit: Callable[[Mapping[str, Any]], None], cancel_event: threading.Event,
        monotonic: Callable[[], float], hard_deadline: float, interval_seconds: float,
    ) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("system sampling cadence is invalid")
        self.runtime, self.allocation, self.plan, self.block = runtime, allocation, plan, block
        prefix = f"{block['block_id']}-attempt-"
        suffix = (startup_attempt_id[len(prefix):]
                  if isinstance(startup_attempt_id, str)
                  and startup_attempt_id.startswith(prefix) else "")
        if (not suffix.isdigit() or suffix.startswith("0")
                or int(suffix) not in {1, 2}):
            raise ValueError("system sampling startup attempt identity is invalid")
        self.run_id, self.attempt_id = run_id, attempt_id
        self.startup_attempt_id, self.emit = startup_attempt_id, emit
        self.cancel_event, self.monotonic = cancel_event, monotonic
        self.hard_deadline, self.interval_seconds = hard_deadline, interval_seconds
        self._phase = "prestart"
        self._handle: RuntimeHandle | None = None
        self._shutdown = threading.Event()
        self._sample_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    def set_phase(self, phase: str, handle: RuntimeHandle | None = None) -> None:
        with self._state_lock:
            self._phase, self._handle = phase, handle

    def _sample(self, *, deadline_monotonic: float, slot_kind: str = "periodic") -> Mapping[str, Any]:
        with self._sample_lock:
            with self._state_lock:
                phase, handle = self._phase, self._handle
            value = self.runtime.sample_system(
                self.allocation, self.plan, self.block, handle, phase,
                self.run_id, self.attempt_id, self.startup_attempt_id,
                deadline_monotonic=deadline_monotonic, slot_kind=slot_kind,
            )
            self.emit(value)
            return value

    def measurement_boundary(self, slot_kind: str, *, deadline_monotonic: float) -> Mapping[str, Any]:
        if slot_kind not in {"measurement_start_boundary", "measurement_end_boundary"}:
            raise ValueError("invalid measurement boundary slot")
        return self._sample(deadline_monotonic=deadline_monotonic, slot_kind=slot_kind)

    def start(self, *, deadline_monotonic: float) -> None:
        # This synchronous slot proves sampling began before runtime creation.
        self._sample(deadline_monotonic=deadline_monotonic)
        self._thread = threading.Thread(
            target=self._run, name="episode1-system-sampler", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            while not self._shutdown.wait(self.interval_seconds):
                now = self.monotonic()
                operation_deadline = min(
                    self.hard_deadline, now + min(2.0, self.interval_seconds)
                )
                if operation_deadline <= now:
                    raise TimeoutError("system sampling hard deadline reached")
                self._sample(deadline_monotonic=operation_deadline)
        except BaseException as exc:
            self._error = exc
            self.cancel_event.set()

    def check(self) -> None:
        if self._error is not None:
            raise LifecycleError("system sampling failed") from self._error

    def finish(self, *, deadline_monotonic: float) -> None:
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, deadline_monotonic - self.monotonic()))
            if self._thread.is_alive():
                raise LifecycleError("system sampler did not stop before its deadline")
        self.check()
        self.set_phase("drain", self._handle)
        self._sample(deadline_monotonic=deadline_monotonic)


def _identity(value: Mapping[str, Any]) -> tuple[Any, ...]:
    required = (
        "gpu_uuid", "gpu_pci", "driver_version", "boot_id",
        "build_attestation_sha256", "installed_material_sha256", "gpu_count",
        "gpu_total_memory_mib", "compute_capability",
    )
    if any(key not in value for key in required):
        raise LifecycleError("allocation attestation is incomplete")
    return tuple(value[key] for key in required)


def _allocation_facts(allocation: Allocation) -> dict[str, Any]:
    return {
        "gpu": allocation.gpu,
        "gpu_count": allocation.gpu_count,
        "data_center_id": allocation.data_center_id,
        "cloud_type": allocation.cloud_type,
        "container_disk_gb": allocation.container_disk_gb,
        "volume_gb": allocation.volume_gb,
        "volume_mount_path": allocation.volume_mount_path,
        "container_ssh_port": allocation.container_ssh_port,
    }


def _hash_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _promotion_allocation(allocation: Allocation) -> Allocation:
    resource = _cleanup_resource_identity(allocation)
    immutable = _hash_json({
        "private_id": allocation.private_id, "unique_name": allocation.unique_name,
        "ssh_host": allocation.ssh_host, "ssh_public_port": allocation.ssh_public_port,
        "requested_image_reference": allocation.requested_image_reference,
        "provider_image_reference": allocation.provider_image_reference,
        **_allocation_facts(allocation),
    })
    return Allocation(
        allocation.private_id, allocation.unique_name, allocation.ssh_host,
        allocation.ssh_public_port, allocation.container_ssh_port,
        allocation.ownership_token, allocation.gpu, allocation.gpu_count,
        allocation.data_center_id, allocation.cloud_type, allocation.container_disk_gb,
        allocation.volume_gb, allocation.volume_mount_path,
        allocation.requested_image_reference, allocation.provider_image_reference,
        allocation.billing_started_monotonic, resource, immutable,
    )


def _cleanup_resource_identity(allocation: Allocation | DeletionAuthority) -> str:
    """Hash fields present as soon as provider ownership becomes durable."""
    return _hash_json({
        "provider": "runpod-rest-v2", "private_id": allocation.private_id,
        "unique_name": allocation.unique_name,
        "ownership_token_sha256": hashlib.sha256(allocation.ownership_token.encode()).hexdigest(),
        "billing_started_monotonic": allocation.billing_started_monotonic,
    })


def _attempt_hashes(block_id: str, block_attempt: int,
                    handle: RuntimeHandle | None) -> tuple[str, str, str, str]:
    attempt = f"{block_id}-attempt-{block_attempt}"
    startup_hash = hashlib.sha256(attempt.encode()).hexdigest()
    process_id = "not-created" if handle is None else handle.private_process_id
    process_start = ({"pid": None, "start_ticks": None} if handle is None else
                     {"pid": handle.process_pid, "start_ticks": handle.process_start_ticks})
    process_id_hash = hashlib.sha256(process_id.encode()).hexdigest()
    process_start_hash = _hash_json(process_start)
    process_identity_hash = _hash_json({
        "process_id_sha256": process_id_hash,
        "process_start_identity_sha256": process_start_hash,
    })
    return startup_hash, process_id_hash, process_start_hash, process_identity_hash


def _expected_allocation_facts(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "gpu": plan["allocation"]["gpu"],
        "gpu_count": plan["allocation"]["gpu_count"],
        "data_center_id": plan["allocation"]["data_center_id"],
        "cloud_type": plan["allocation"]["cloud_type"],
        "container_disk_gb": plan["allocation"]["container_disk_gb"],
        "volume_gb": plan["allocation"]["volume_gb"],
        "volume_mount_path": plan["allocation"]["volume_mount_path"],
        "container_ssh_port": plan["access"]["ssh_port"],
    }


class Episode1Orchestrator:
    """Run the exact six-block protocol on one allocation and always clean up."""

    def __init__(
        self,
        *,
        provider: ProviderControl,
        guard: GuardControl,
        runtime: RuntimeControl | None = None,
        cells: CellDriver | None = None,
        runtime_factory: RuntimeFactory | None = None,
        cell_factory: CellFactory | None = None,
        capture: CaptureControl,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monitor_poll_seconds: float = 1.0,
        clock_domain: str = "process-monotonic-domain",
        primary_watchdog_sha256: str | None = None,
        secondary_watchdog_sha256: str | None = None,
        telemetry_factory: TelemetryFactory | None = None,
        run_context: RunTimingContext | None = None,
    ) -> None:
        if (runtime is None) == (runtime_factory is None):
            raise ValueError("provide exactly one runtime or allocation-bound runtime factory")
        if (cells is None) == (cell_factory is None):
            raise ValueError("provide exactly one cell driver or allocation-bound cell factory")
        self.provider, self.guard, self.runtime = provider, guard, runtime
        self.cells, self.capture = cells, capture
        self.runtime_factory, self.cell_factory = runtime_factory, cell_factory
        self.monotonic, self.utc_now = monotonic, utc_now
        self.monitor_poll_seconds = monitor_poll_seconds
        self.clock_domain = clock_domain
        self.primary_watchdog_sha256 = primary_watchdog_sha256
        self.secondary_watchdog_sha256 = secondary_watchdog_sha256
        self.telemetry_factory = telemetry_factory
        self.run_context = run_context

    def _create_or_recover(
        self, plan: Mapping[str, Any], unique_name: str, ownership_token: str,
        deadline_monotonic: float,
    ) -> Allocation:
        try:
            allocation = self.provider.create_allocation(
                unique_name=unique_name, ownership_token=ownership_token, plan=plan,
                deadline_monotonic=deadline_monotonic,
            )
        except CreateOutcomeUnknown:
            recovery_deadline = min(
                deadline_monotonic,
                self.monotonic() + float(plan["budget"]["create_recovery_seconds"]),
            )
            matches = list(self.provider.recover_exact_name(
                unique_name, deadline_monotonic=recovery_deadline
            ))
            if (
                len(matches) != 1
                or matches[0].unique_name != unique_name
                or not secrets.compare_digest(matches[0].ownership_token, ownership_token)
                or _allocation_facts(matches[0]) != _expected_allocation_facts(plan)
            ):
                raise LifecycleError("ambiguous create could not be recovered to exactly one owned allocation")
            allocation = matches[0]
        if allocation.unique_name != unique_name or not secrets.compare_digest(
            allocation.ownership_token, ownership_token
        ) or _allocation_facts(allocation) != _expected_allocation_facts(plan):
            raise LifecycleError("provider returned an allocation outside the ownership intent")
        return allocation

    def _safe_boundary(self, event: str, details: Mapping[str, Any]) -> None:
        try:
            self.capture.boundary(event, details)
        except BaseException:
            # Evidence loss is later reported, but must never delay resource deletion.
            pass

    def _delete_and_verify(
        self, allocation: Allocation | DeletionAuthority, *, deadline_monotonic: float
    ) -> None:
        acknowledged = False
        absent = False
        not_found = False
        attempts = 0
        successful: tuple[Any, Any, Any] | None = None
        retention_error: BaseException | None = None
        contract = self.capture.contract
        resource_identity = getattr(allocation, "resource_identity_sha256", None)
        if not isinstance(resource_identity, str):
            resource_identity = _cleanup_resource_identity(allocation)
        binding = self.provider.make_cleanup_observation_binding(
            allocation, run_id=contract.run_id, attempt_id=contract.attempt_id,
            plan_sha256=contract.plan_sha256,
            resource_identity_sha256=resource_identity,
            original_deadline_monotonic_ns=contract.hard_deadline_monotonic_ns,
        )
        # Provider adapters may apply their own backoff; this bounded retry loop
        # handles transient delete/readback responses without an unbounded wait.
        def retain(operation: str, observation: Any | None,
                   error: BaseException | None) -> None:
            nonlocal retention_error
            try:
                self.capture.cleanup_attempt_observed(
                    delete_attempt=attempts,operation=operation,
                    observation=observation,
                    error_type=None if error is None else type(error).__name__,
                )
            except BaseException as exc:
                retention_error = retention_error or exc

        for attempts in range(1, 4):
            if self.monotonic() >= deadline_monotonic:
                break
            deleted = inventory = direct = None
            try:
                deleted = self.provider.delete_allocation_observed(
                    allocation, binding=binding, delete_attempt=attempts,
                    deadline_monotonic=deadline_monotonic,
                )
            except BaseException as exc:
                retain("delete",None,exc)
            else:
                retain("delete",deleted,None)
            if self.monotonic() < deadline_monotonic:
                try:
                    inventory = self.provider.inventory_absent_observed(
                        allocation, binding=binding, delete_attempt=attempts,
                        deadline_monotonic=deadline_monotonic,
                    )
                except BaseException as exc:
                    retain("inventory",None,exc)
                else:
                    retain("inventory",inventory,None)
            if self.monotonic() < deadline_monotonic:
                try:
                    direct = self.provider.direct_not_found_observed(
                        allocation, binding=binding, delete_attempt=attempts,
                        deadline_monotonic=deadline_monotonic,
                    )
                except BaseException as exc:
                    retain("direct",None,exc)
                else:
                    retain("direct",direct,None)
            if deleted is not None and inventory is not None and direct is not None:
                acknowledged = deleted.value is True
                absent = inventory.value is True
                not_found = direct.value is True
                if acknowledged and absent and not_found:
                    successful = (deleted, inventory, direct)
            else:
                acknowledged = absent = not_found = False
            if acknowledged and absent and not_found:
                break
        if retention_error is not None:
            raise LifecycleError("cleanup evidence retention failed") from retention_error
        if successful is None:
            raise LifecycleError("permanent deletion proof is incomplete")
        deleted, inventory, direct = successful
        self.capture.deletion_verified(
            attempts=attempts, acknowledged=True, inventory_absent=True,
            direct_not_found=True,
            attempt_evidence=[deleted.capture_input, inventory.capture_input,
                              direct.capture_input],
            provider_evidence=[deleted.provider_artifact, inventory.provider_artifact,
                               direct.provider_artifact],
            delete_response=deleted.raw_bytes,
            inventory_response=inventory.raw_bytes,
            direct_response=direct.raw_bytes,
        )
        self.capture.settlement_observed(
            status="provisional", response=b"",
            reason="provider_billing_unavailable",
        )

    def run(
        self,
        *,
        plan: Mapping[str, Any],
        authorization_receipt: Mapping[str, Any],
        plan_file_bytes: bytes,
        material_file_bytes: bytes,
        material_files: Mapping[str, bytes],
        observed_source_commit: str,
        authorization_source_bytes: bytes,
        unique_name: str,
    ) -> Mapping[str, Any]:
        # This must precede the monotonic create boundary and every provider call.
        verify_execution_candidate(plan)
        if self.telemetry_factory is None:
            raise LifecycleError("the executable Episode 1 path requires a telemetry factory")
        verification_time = self.utc_now()
        authorization_receipt_sha256 = verify_authorization_receipt(
            plan, authorization_receipt, plan_file_bytes=plan_file_bytes,
            material_file_bytes=material_file_bytes,
            material_files=material_files,
            observed_source_commit=observed_source_commit,
            source_record_bytes=authorization_source_bytes,
            verification_time=verification_time,
        )
        if not unique_name.startswith(f"episode1-{plan['candidate_id']}-"):
            raise LifecycleError("unique allocation name is not bound to the candidate")
        verify_fresh_for_create(plan, now=verification_time)
        if self.run_context is None:
            started = self.monotonic()  # t0 is before the first mutating provider call
            hard_deadline = started + float(plan["budget"]["maximum_lifetime_seconds"])
        else:
            context = self.run_context
            if context.plan_sha256 != plan["plan_sha256"]:
                raise LifecycleError("run context is bound to a different plan")
            if context.clock_domain != self.clock_domain:
                raise LifecycleError("run context clock domain differs from the orchestrator")
            started = context.original_t0_monotonic
            hard_deadline = context.hard_deadline_monotonic
            expected_hard = started + float(plan["budget"]["maximum_lifetime_seconds"])
            if not math.isclose(hard_deadline, expected_hard, rel_tol=0, abs_tol=1e-9):
                raise LifecycleError("run context hard deadline differs from the plan")
            contract = self.capture.contract
            if (
                contract.plan_sha256 != context.plan_sha256
                or contract.original_t0_monotonic_ns != int(started * 1_000_000_000)
                or contract.hard_deadline_monotonic_ns != int(hard_deadline * 1_000_000_000)
                or contract.teardown_deadline_monotonic_ns
                != int(context.teardown_deadline_monotonic * 1_000_000_000)
            ):
                raise LifecycleError("capture contract differs from the shared run context")
        hard_deadline_ns = int(hard_deadline * 1_000_000_000)
        cleanup_reserve = float(plan["phase_budgets"]["export_and_verified_deletion"])
        work_deadline = hard_deadline - cleanup_reserve
        monitor_stop_deadline = work_deadline + cleanup_reserve * 0.10
        runtime_stop_deadline = work_deadline + cleanup_reserve * 0.30
        export_deadline = work_deadline + cleanup_reserve * 0.55
        provision_deadline = min(
            work_deadline,
            started + float(plan["phase_budgets"]["provision_and_staging"]),
        )
        ownership_token = secrets.token_hex(32)
        self.capture.prepare(plan, unique_name, ownership_token)
        self.capture.boundary("authorization-verified", {
            "authorization_receipt_sha256": authorization_receipt_sha256,
            "plan_file_sha256": hashlib.sha256(plan_file_bytes).hexdigest(),
            "material_file_sha256": hashlib.sha256(material_file_bytes).hexdigest(),
            "authorization_source_sha256": hashlib.sha256(authorization_source_bytes).hexdigest(),
        })
        allocation: Allocation | None = None
        deletion_authority: DeletionAuthority | None = None
        monitor: BudgetMonitor | None = None
        active: RuntimeHandle | None = None
        cells_started = False
        primary_error: BaseException | None = None
        cleanup_errors: list[BaseException] = []
        startup_retries = 0
        completed_blocks = 0
        baseline: Mapping[str, Any] | None = None
        stable_device: tuple[Any, ...] | None = None
        guard_binding: GuardBinding | None = None
        sampler: SystemSamplingLoop | None = None
        block_telemetry: BlockTelemetryControl | None = None
        try:
            def bind_owner(authority: DeletionAuthority) -> None:
                nonlocal deletion_authority
                if deletion_authority is not None and deletion_authority != authority:
                    raise LifecycleError("provider attempted to replace deletion authority")
                deletion_authority = authority
                self.capture.owned(
                    authority,
                    plan,
                    cleanup_deadline_monotonic=hard_deadline_ns,
                )
                failure_sink_binder = getattr(
                    self.provider, "bind_failure_observation_sink", None
                )
                if failure_sink_binder is not None:
                    if not callable(failure_sink_binder):
                        raise LifecycleError("provider failure sink binder is invalid")
                    from .episode1_provider_failure_capture import CaptureFailureSink
                    failure_sink_binder(CaptureFailureSink(self.capture))

            self.provider.bind_cleanup_owner(bind_owner)
            allocation = self._create_or_recover(
                plan, unique_name, ownership_token, provision_deadline
            )
            readback = self.provider.read_allocation(
                allocation, deadline_monotonic=provision_deadline
            )
            readback_verified = readback == allocation and _allocation_facts(readback) == _expected_allocation_facts(plan)
            self.capture.boundary("allocation-readback", {"verified": readback_verified})
            if not readback_verified:
                raise LifecycleError("created allocation did not match the compiled plan")
            allocation = _promotion_allocation(readback)
            self.capture.start(
                allocation,
                plan,
                cleanup_deadline_monotonic=hard_deadline_ns,
            )
            if self.runtime_factory is not None:
                self.runtime = self.runtime_factory(allocation)
            if self.cell_factory is not None:
                self.cells = self.cell_factory(allocation)
            if self.runtime is None or self.cells is None:
                raise LifecycleError("allocation-bound controls were not constructed")
            configured_watchdog = plan["guard"]["local_watchdog_plan_sha256"]
            guard_binding = make_guard_binding(
                plan=plan, unique_name=unique_name, allocation_id=allocation.private_id,
                ownership_token=ownership_token, original_t0_monotonic=started,
                hard_deadline_monotonic=hard_deadline, clock_domain=self.clock_domain,
                primary_script_sha256=self.primary_watchdog_sha256 or configured_watchdog,
                secondary_script_sha256=self.secondary_watchdog_sha256 or configured_watchdog,
            )
            guard_evidence = self.guard.arm(
                guard_binding, deadline_monotonic=provision_deadline
            )
            self.capture.boundary("termination-guard-armed", {
                **guard_evidence, "binding_sha256": guard_binding.sha256,
                "original_t0_monotonic": started,
                "hard_deadline_monotonic": hard_deadline,
                "teardown_deadline_monotonic": guard_binding.teardown_deadline_monotonic,
            })
            if not self.guard.healthy(guard_binding, deadline_monotonic=provision_deadline):
                raise LifecycleError("termination guard failed its initial readback")
            monitor = BudgetMonitor(
                provider=self.provider, guard=self.guard, allocation=allocation, plan=plan,
                start_monotonic=started, monotonic=self.monotonic,
                poll_seconds=self.monitor_poll_seconds,
                hard_deadline=hard_deadline,
                guard_binding=guard_binding,
            )
            monitor.start()
            self.cells.start(
                deadline_monotonic=min(work_deadline, self.monotonic() + 30.0)
            )
            cells_started = True
            blocks = plan["blocks"]
            if len(blocks) != 6:
                raise LifecycleError("compiled plan does not contain six blocks")
            for block_index, block in enumerate(blocks):
                monitor.check_new_work()
                remaining_blocks = len(blocks) - block_index
                block_budget = (
                    float(plan["phase_budgets"]["six_runtime_startups"])
                    + float(plan["phase_budgets"]["six_warmup_sets"])
                    + float(plan["phase_budgets"]["six_measured_blocks"])
                ) / 6
                retry_reserve = (
                    float(plan["phase_budgets"]["one_startup_retry_contingency"])
                    if startup_retries == 0 else 0.0
                )
                if self.monotonic() + remaining_blocks * block_budget + retry_reserve > work_deadline:
                    raise LifecycleError("insufficient remaining lifetime for worst-case blocks and cleanup")
                startup_deadline = min(
                    work_deadline,
                    self.monotonic() + float(plan["phase_budgets"]["six_runtime_startups"]) / 6,
                )
                attestation = self.runtime.attest_allocation(
                    allocation, plan, deadline_monotonic=startup_deadline
                )
                identity = _identity(attestation)
                if stable_device is None:
                    stable_device = identity
                    baseline = dict(zip((
                        "gpu_uuid", "gpu_pci", "driver_version", "boot_id",
                        "build_attestation_sha256", "installed_material_sha256", "gpu_count",
                        "gpu_total_memory_mib", "compute_capability",
                    ), identity))
                    baseline["used_memory_mib"] = attestation["used_memory_mib"]
                elif identity != stable_device:
                    raise LifecycleError("allocation identity changed between paired blocks")
                self.capture.boundary("block-attested", {"block_id": block["block_id"], "runtime": block["runtime"]})
                block_attempt = 0
                while True:
                    block_attempt += 1
                    startup_attempt_id = f"{block['block_id']}-attempt-{block_attempt}"
                    failure_stage = "runtime_start"
                    try:
                        block_telemetry = self.telemetry_factory(
                            plan, block, self.capture.contract.attempt_id,
                            startup_attempt_id, block_attempt, allocation, self.capture
                        )
                        if (block_telemetry.run_attempt_id != self.capture.contract.attempt_id
                                or block_telemetry.startup_attempt_id != startup_attempt_id
                                or block_telemetry.block_attempt != block_attempt):
                            raise LifecycleError("telemetry factory changed its attempt binding")
                        sampler = SystemSamplingLoop(
                            runtime=self.runtime, allocation=allocation, plan=plan,
                            block=block,
                            run_id=self.capture.contract.run_id,
                            attempt_id=block_telemetry.run_attempt_id,
                            startup_attempt_id=startup_attempt_id,
                            emit=block_telemetry.system_sample,
                            cancel_event=monitor.teardown_now,
                            monotonic=self.monotonic,
                            hard_deadline=work_deadline,
                            interval_seconds=float(plan["capture"]["telemetry_cadence_seconds"]),
                        )
                        sampler.start(deadline_monotonic=startup_deadline)
                        sampler.set_phase("startup")
                        active = self.runtime.start(
                            allocation, block, plan, deadline_monotonic=startup_deadline
                        )
                        sampler.set_phase("startup", active)
                        block_telemetry.start(active, deadline_monotonic=startup_deadline)
                        failure_stage = "readiness_probe"
                        probe = self.runtime.wait_ready_and_probe(
                            allocation, active, plan, deadline_monotonic=startup_deadline
                        )
                        if probe.get("exact_tokens") is not True or probe.get("effective_flags") is not True:
                            raise LifecycleError("runtime readiness probe did not verify exact work and flags")
                        startup_hash, process_id_hash, process_start_hash, _ = _attempt_hashes(
                            str(block["block_id"]), block_attempt, active
                        )
                        image_digest = next(
                            item["derived_image_digest"] for item in plan["runtime_builds"]
                            if item["runtime"] == block["runtime"]
                        )
                        self.capture.block_start(
                            str(block["block_id"]), str(block["runtime"]),
                            block_attempt=block_attempt,
                            startup_attempt_id_sha256=startup_hash,
                            process_id_sha256=process_id_hash,
                            process_start_identity_sha256=process_start_hash,
                            image_digest=image_digest,
                        )
                        break
                    except BaseException as startup_error:
                        startup_hash, _, _, process_identity_hash = _attempt_hashes(
                            str(block["block_id"]), block_attempt, active
                        )
                        capture_error: BaseException | None = None
                        try:
                            self.capture.startup_failed(
                                str(block["block_id"]), str(block["runtime"]),
                                block_attempt=block_attempt,
                                startup_attempt_id_sha256=startup_hash,
                                process_identity_sha256=process_identity_hash,
                                failure_stage=failure_stage,
                            )
                        except BaseException as exc:
                            capture_error = exc
                        retry_deadline = min(
                            work_deadline,
                            self.monotonic() + float(plan["phase_budgets"]["one_startup_retry_contingency"]),
                        )
                        if sampler is not None:
                            sampler.set_phase("drain", active)
                            sampler.finish(deadline_monotonic=retry_deadline)
                            sampler = None
                        if block_telemetry is not None:
                            block_telemetry.abort(deadline_monotonic=retry_deadline)
                            block_telemetry = None
                        descendants_absent = False
                        memory_recovered = False
                        if active is not None:
                            self.runtime.stop(
                                allocation, active, deadline_monotonic=retry_deadline
                            )
                            descendants_absent = self.runtime.descendants_absent(
                                allocation, active, deadline_monotonic=retry_deadline
                            )
                            if not descendants_absent:
                                raise LifecycleError("failed startup left runtime descendants")
                            memory_recovered = baseline is not None and self.runtime.memory_recovered(
                                allocation, baseline, deadline_monotonic=retry_deadline
                            )
                            if not memory_recovered:
                                raise LifecycleError("failed startup did not restore GPU memory")
                            active = None
                        else:
                            if baseline is None:
                                raise LifecycleError("startup failed before a recovery baseline was bound")
                            cleanup = self.runtime.cleanup_failed_start(
                                allocation, block, baseline, deadline_monotonic=retry_deadline
                            )
                            if cleanup.get("descendants_absent") is not True or cleanup.get("memory_recovered") is not True:
                                raise LifecycleError("unidentified failed startup did not restore process and GPU state")
                            descendants_absent = True
                            memory_recovered = True
                        self.capture.failed_start_cleanup(
                            str(block["block_id"]), str(block["runtime"]),
                            block_attempt=block_attempt,
                            startup_attempt_id_sha256=startup_hash,
                            process_identity_sha256=process_identity_hash,
                            descendants_absent=descendants_absent,
                            memory_recovered=memory_recovered,
                        )
                        if capture_error is not None:
                            raise capture_error from startup_error
                        if startup_retries >= int(plan["budget"]["startup_retry_limit"]):
                            raise startup_error
                        startup_retries += 1
                        startup_deadline = retry_deadline
                        monitor.check_new_work()
                        self.capture.boundary("startup-retry", {"attempt": startup_retries})
                self.capture.boundary("runtime-ready", {"block_id": block["block_id"], "runtime": block["runtime"]})
                assert sampler is not None
                sampler.set_phase("warmup", active)
                cancel_event = monitor.teardown_now
                cell_by_id = {str(cell["id"]): dict(cell) for cell in CELLS}
                warmup_deadline = min(
                    work_deadline,
                    self.monotonic() + float(plan["phase_budgets"]["six_warmup_sets"]) / 6,
                )
                # Warm every declared shape before any measurement in this block.
                for cell_id in block["cell_order"]:
                    monitor.check_new_work()
                    outcome = self.cells.run_cell(
                        allocation=allocation, block=block, cell=cell_by_id[cell_id], warmup=True,
                        evidence_class="provider_candidate", cancel_event=cancel_event,
                        record=self.capture.request,
                        request_lifecycle=self.capture.request_lifecycle,
                        deadline_monotonic=warmup_deadline,
                    )
                    sampler.check()
                    if outcome.get("scheduled") != cell_by_id[cell_id]["warmups"] or outcome.get("failed", 0):
                        raise LifecycleError("warmup did not complete exactly as declared")
                    _, _, _, process_identity_hash = _attempt_hashes(
                        str(block["block_id"]), block_attempt, active
                    )
                    self.capture.cell_complete(
                        str(block["block_id"]), cell_id, warmup=True,
                        startup_attempt_id_sha256=startup_hash,
                        process_identity_sha256=process_identity_hash,
                    )
                measured_deadline = min(
                    work_deadline,
                    self.monotonic() + float(plan["phase_budgets"]["six_measured_blocks"]) / 6,
                )
                sampler.set_phase("measurement", active)
                sampler.measurement_boundary(
                    "measurement_start_boundary", deadline_monotonic=measured_deadline
                )
                for cell_id in block["cell_order"]:
                    monitor.check_new_work()
                    outcome = self.cells.run_cell(
                        allocation=allocation, block=block, cell=cell_by_id[cell_id], warmup=False,
                        evidence_class="provider_candidate", cancel_event=cancel_event,
                        record=lambda value: (
                            self.capture.request(value),
                            block_telemetry.observe_request(value, warmup=False),
                        ),
                        request_lifecycle=self.capture.request_lifecycle,
                        deadline_monotonic=measured_deadline,
                    )
                    sampler.check()
                    if outcome.get("scheduled") != cell_by_id[cell_id]["requests"]:
                        raise LifecycleError("cell driver lost scheduled attempts")
                    if cancel_event.is_set():
                        raise LifecycleError("active cell cancelled for teardown")
                    self.capture.cell_complete(
                        str(block["block_id"]), cell_id, warmup=False,
                        startup_attempt_id_sha256=startup_hash,
                        process_identity_sha256=process_identity_hash,
                    )
                sampler.measurement_boundary(
                    "measurement_end_boundary", deadline_monotonic=measured_deadline
                )
                sampler.set_phase("drain", active)
                sampler.finish(deadline_monotonic=work_deadline)
                sampler = None
                if block_telemetry is not None:
                    block_telemetry.finish(deadline_monotonic=work_deadline)
                    block_telemetry = None
                stopped = self.runtime.stop(
                    allocation, active, deadline_monotonic=work_deadline
                )
                self.capture.boundary("runtime-stopped", {"block_id": block["block_id"], **dict(stopped)})
                descendants_absent = self.runtime.descendants_absent(
                    allocation, active, deadline_monotonic=work_deadline
                )
                if not descendants_absent:
                    raise LifecycleError("previous runtime descendants remain")
                memory_recovered = baseline is not None and self.runtime.memory_recovered(
                    allocation, baseline, deadline_monotonic=work_deadline
                )
                if not memory_recovered:
                    raise LifecycleError("GPU memory did not recover to the attested baseline")
                self.capture.block_complete(
                    str(block["block_id"]), str(block["runtime"]),
                    descendants_absent=descendants_absent,
                    memory_recovered=memory_recovered,
                    startup_attempt_id_sha256=startup_hash,
                    process_identity_sha256=process_identity_hash,
                )
                active = None
                completed_blocks += 1
        except BaseException as exc:
            primary_error = exc
        finally:
            if sampler is not None:
                try:
                    sampler.set_phase("drain", active)
                    sampler.finish(deadline_monotonic=runtime_stop_deadline)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if block_telemetry is not None:
                try:
                    block_telemetry.abort(deadline_monotonic=runtime_stop_deadline)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if cells_started:
                try:
                    self.cells.close(deadline_monotonic=runtime_stop_deadline)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if monitor is not None:
                try:
                    monitor.stop(deadline_monotonic=monitor_stop_deadline)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            cleanup_target = allocation if allocation is not None else deletion_authority
            if cleanup_target is not None:
                if active is not None:
                    try:
                        stopped = self.runtime.stop(
                            allocation, active, deadline_monotonic=runtime_stop_deadline
                        )
                        self._safe_boundary("runtime-stopped-on-abort", dict(stopped))
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                        self._safe_boundary("runtime-stop-failed", {"error_class": type(exc).__name__})
                try:
                    export_operation_deadline = min(
                        export_deadline,
                        self.monotonic() + float(plan["budget"]["export_seconds"]),
                    )
                    self.capture.export_essential(
                        deadline_monotonic=export_operation_deadline
                    )
                except BaseException as exc:
                    cleanup_errors.append(exc)
                    self._safe_boundary("essential-export-failed", {"error_class": type(exc).__name__})
                try:
                    delete_operation_deadline = min(
                        hard_deadline,
                        self.monotonic()
                        + float(plan["budget"]["delete_verification_seconds"]),
                    )
                    self._delete_and_verify(
                        cleanup_target, deadline_monotonic=delete_operation_deadline
                    )
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                self.capture.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if primary_error is not None or cleanup_errors:
            errors = ([primary_error] if primary_error is not None else []) + cleanup_errors
            if len(errors) == 1:
                raise errors[0]
            raise BaseExceptionGroup("Episode 1 execution and cleanup failed", errors)
        return {
            "completed_blocks": completed_blocks,
            "startup_retries": startup_retries,
            "warmups": 72,
            "measured_requests": 528,
            "deletion_verified": True,
        }
