"""Closed application seam for one approved Episode 1 execution.

This module owns no credentials and performs no provider operation on import.
Callers must supply the concrete provider, guard, and allocation-bound control
factories.  One immutable :class:`RunContext` binds preflight inputs, clocks,
capture, and orchestration before the provider can be called.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .episode1 import CELLS, canonical_json, validate_observation
from .episode1_authorization import verify_authorization_receipt
from .episode1_capture import EvidenceCaptureV2, RunContract
from .episode1_execution import verify_execution_candidate, verify_fresh_for_create
from .episode1_orchestrator import (
    Allocation,
    CellFactory,
    Episode1Orchestrator,
    GuardControl,
    ProviderControl,
    RuntimeFactory,
    TelemetryFactory,
)


_PROMOTION_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,79}\Z")
_CAPTURE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


def _promotion_id(value: str, label: str) -> str:
    if not isinstance(value, str) or _PROMOTION_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is not a safe opaque identifier")
    return value


def _capture_id(value: str, label: str) -> str:
    if not isinstance(value, str) or _CAPTURE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is not a valid capture identifier")
    return value


def _request_counts(plan: Mapping[str, Any]) -> dict[str, int]:
    cells = {str(cell["id"]): cell for cell in CELLS}
    result: dict[str, int] = {}
    for block in plan["blocks"]:
        block_id = str(block["block_id"])
        for cell_id in block["cell_order"]:
            cell = cells[str(cell_id)]
            result[f"{block_id}|{cell_id}|1"] = int(cell["warmups"])
            result[f"{block_id}|{cell_id}|0"] = int(cell["requests"])
    return result


@dataclass(frozen=True)
class RunContext:
    """Immutable, digest-bound inputs and the single pre-create clock boundary."""

    run_id: str
    attempt_id: str
    _plan_canonical: bytes
    _authorization_receipt_canonical: bytes
    plan_file_bytes: bytes
    material_file_bytes: bytes
    material_files: tuple[tuple[str, bytes], ...]
    observed_source_commit: str
    authorization_source_bytes: bytes
    unique_name: str
    telemetry_series: tuple[str, ...]
    original_t0_monotonic: float
    original_t0_utc_ns: int
    hard_deadline_monotonic: float
    teardown_deadline_monotonic: float
    clock_domain: str
    boot_id: str

    @property
    def plan(self) -> Mapping[str, Any]:
        """Return a detached copy of the preflighted plan."""
        return json.loads(self._plan_canonical)

    @property
    def authorization_receipt(self) -> Mapping[str, Any]:
        """Return a detached copy of the preflighted authorization receipt."""
        return json.loads(self._authorization_receipt_canonical)

    @property
    def plan_sha256(self) -> str:
        return str(self.plan["plan_sha256"])

    @classmethod
    def create(
        cls,
        *,
        plan: Mapping[str, Any],
        authorization_receipt: Mapping[str, Any],
        plan_file_bytes: bytes,
        material_file_bytes: bytes,
        material_files: Mapping[str, bytes],
        observed_source_commit: str,
        authorization_source_bytes: bytes,
        unique_name: str,
        telemetry_series: Sequence[str],
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        run_id: str | None = None,
        attempt_id: str = "attempt-01",
        clock_domain: str = "process-monotonic-domain",
        boot_id: str = "local-boot",
    ) -> "RunContext":
        frozen_plan = copy.deepcopy(dict(plan))
        frozen_receipt = copy.deepcopy(dict(authorization_receipt))
        frozen_material = tuple(sorted((str(path), bytes(value)) for path, value in material_files.items()))
        verify_execution_candidate(frozen_plan)
        verification_time = utc_now()
        verify_authorization_receipt(
            frozen_plan,
            frozen_receipt,
            plan_file_bytes=bytes(plan_file_bytes),
            material_file_bytes=bytes(material_file_bytes),
            material_files=dict(frozen_material),
            observed_source_commit=observed_source_commit,
            source_record_bytes=bytes(authorization_source_bytes),
            verification_time=verification_time,
        )
        verify_fresh_for_create(frozen_plan, now=verification_time)
        if hashlib.sha256(bytes(plan_file_bytes)).hexdigest() != frozen_receipt["plan_file_sha256"]:
            raise ValueError("plan bytes changed after authorization preflight")
        if hashlib.sha256(bytes(material_file_bytes)).hexdigest() != frozen_receipt["material_file_sha256"]:
            raise ValueError("material manifest changed after authorization preflight")
        series = tuple(str(item) for item in telemetry_series)
        if not series or len(series) != len(set(series)) or any(not item for item in series):
            raise ValueError("telemetry series must be nonempty and unique")
        started_utc = utc_now()
        started = monotonic()
        if isinstance(started, bool) or not isinstance(started, (int, float)) or not math.isfinite(started):
            raise ValueError("monotonic clock returned an invalid value")
        if started_utc.tzinfo is None or started_utc.utcoffset() is None:
            raise ValueError("UTC anchor must be timezone-aware")
        lifetime = float(frozen_plan["budget"]["maximum_lifetime_seconds"])
        teardown_fraction = float(frozen_plan["budget"]["teardown_fraction"])
        generated_run_id = run_id or f"run-{secrets.token_hex(8)}"
        if not unique_name.startswith(f"episode1-{frozen_plan['candidate_id']}-"):
            raise ValueError("unique allocation name is not bound to the candidate")
        return cls(
            run_id=_promotion_id(generated_run_id, "run id"),
            attempt_id=_promotion_id(attempt_id, "attempt id"),
            _plan_canonical=canonical_json(frozen_plan).encode(),
            _authorization_receipt_canonical=canonical_json(frozen_receipt).encode(),
            plan_file_bytes=bytes(plan_file_bytes),
            material_file_bytes=bytes(material_file_bytes),
            material_files=frozen_material,
            observed_source_commit=str(observed_source_commit),
            authorization_source_bytes=bytes(authorization_source_bytes),
            unique_name=_capture_id(unique_name, "unique name"),
            telemetry_series=series,
            original_t0_monotonic=float(started),
            original_t0_utc_ns=int(started_utc.timestamp() * 1_000_000_000),
            hard_deadline_monotonic=float(started) + lifetime,
            teardown_deadline_monotonic=float(started) + lifetime * teardown_fraction,
            clock_domain=_capture_id(clock_domain, "clock domain"),
            boot_id=_capture_id(boot_id, "boot id"),
        )

    def capture_contract(self) -> RunContract:
        blocks = tuple((str(block["block_id"]), str(block["runtime"])) for block in self.plan["blocks"])
        contract = RunContract(
            run_id=self.run_id,
            attempt_id=self.attempt_id,
            plan_sha256=self.plan_sha256,
            source_sha256=hashlib.sha256(self.authorization_source_bytes).hexdigest(),
            material_sha256=str(self.plan["material_sha256"]),
            blocks=blocks,
            request_counts=_request_counts(self.plan),
            telemetry_series=self.telemetry_series,
            original_t0_monotonic_ns=int(self.original_t0_monotonic * 1_000_000_000),
            original_t0_utc_ns=self.original_t0_utc_ns,
            hard_deadline_monotonic_ns=int(self.hard_deadline_monotonic * 1_000_000_000),
            teardown_deadline_monotonic_ns=int(self.teardown_deadline_monotonic * 1_000_000_000),
            clock_domain=self.clock_domain,
            boot_id=self.boot_id,
        )
        return contract.checked()


@dataclass(frozen=True)
class ExecutionResult:
    summary: Mapping[str, Any]
    capture: EvidenceCaptureV2
    context: RunContext


def execute_episode1(
    *,
    context: RunContext,
    private_evidence_directory: Path,
    provider: ProviderControl,
    guard: GuardControl,
    runtime_factory: RuntimeFactory,
    cell_factory: CellFactory,
    telemetry_factory: TelemetryFactory,
    monotonic: Callable[[], float] = time.monotonic,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    utc_ns: Callable[[], int] = time.time_ns,
    utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    observation_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]] = validate_observation,
    monitor_poll_seconds: float = 1.0,
    primary_watchdog_sha256: str | None = None,
    secondary_watchdog_sha256: str | None = None,
) -> ExecutionResult:
    """Execute the preflighted context through real capture and orchestration.

    The evidence directory is created only after all pure context validation has
    completed. Allocation-bound factories are invoked only after exact provider
    ownership and readback have been durably captured.
    """

    contract = context.capture_contract()
    capture = EvidenceCaptureV2(
        private_evidence_directory,
        contract,
        monotonic_ns=monotonic_ns,
        utc_ns=utc_ns,
        observation_validator=observation_validator,
    )
    orchestrator = Episode1Orchestrator(
        provider=provider,
        guard=guard,
        runtime_factory=runtime_factory,
        cell_factory=cell_factory,
        capture=capture,
        monotonic=monotonic,
        utc_now=utc_now,
        monitor_poll_seconds=monitor_poll_seconds,
        clock_domain=context.clock_domain,
        primary_watchdog_sha256=primary_watchdog_sha256,
        secondary_watchdog_sha256=secondary_watchdog_sha256,
        telemetry_factory=telemetry_factory,
        run_context=context,
    )
    summary = orchestrator.run(
        plan=context.plan,
        authorization_receipt=context.authorization_receipt,
        plan_file_bytes=context.plan_file_bytes,
        material_file_bytes=context.material_file_bytes,
        material_files=dict(context.material_files),
        observed_source_commit=context.observed_source_commit,
        authorization_source_bytes=context.authorization_source_bytes,
        unique_name=context.unique_name,
    )
    return ExecutionResult(summary=summary, capture=capture, context=context)
