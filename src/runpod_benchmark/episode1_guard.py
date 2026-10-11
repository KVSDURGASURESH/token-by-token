"""Fail-closed Episode 1 local-watchdog binding and receipt validation.

This module does not launch a provider operation. It validates the durable
handshake produced by two independently launched watchdog processes and makes
stale or cross-run evidence unusable after an orchestrator restart.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .episode1 import canonical_json


class GuardError(RuntimeError):
    """The watchdog binding, arming receipt, or heartbeat is invalid."""


_ROLES = ("primary", "secondary")


def _digest(value: str, label: str) -> str:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise GuardError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _finite(value: object, label: str, *, allow_string: bool = False) -> float:
    admitted = (int, float, str) if allow_string else (int, float)
    if isinstance(value, bool) or not isinstance(value, admitted):
        raise GuardError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GuardError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise GuardError(f"{label} must be a finite number")
    return result


@dataclass(frozen=True)
class GuardBinding:
    schema_version: str
    plan_sha256: str
    watchdog_plan_sha256: str
    run_nonce: str
    unique_name_sha256: str
    allocation_id_sha256: str
    ownership_token_sha256: str
    original_t0_monotonic: float
    teardown_deadline_monotonic: float
    hard_deadline_monotonic: float
    clock_domain: str
    primary_script_sha256: str
    secondary_script_sha256: str

    def validate(self) -> None:
        if self.schema_version != "episode1.guard-binding.v1":
            raise GuardError("unsupported guard binding schema")
        for field in (
            "plan_sha256", "watchdog_plan_sha256", "unique_name_sha256",
            "allocation_id_sha256", "ownership_token_sha256",
            "primary_script_sha256", "secondary_script_sha256",
        ):
            _digest(getattr(self, field), f"binding.{field}")
        if len(self.run_nonce) != 64 or any(c not in "0123456789abcdef" for c in self.run_nonce):
            raise GuardError("binding.run_nonce must be 32 random bytes in hex")
        if not self.clock_domain:
            raise GuardError("binding.clock_domain is required")
        start = _finite(self.original_t0_monotonic, "binding.original_t0_monotonic")
        teardown = _finite(self.teardown_deadline_monotonic, "binding.teardown_deadline_monotonic")
        hard = _finite(self.hard_deadline_monotonic, "binding.hard_deadline_monotonic")
        if not start < teardown < hard:
            raise GuardError("guard deadlines must preserve original_t0 < teardown < hard")

    def document(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.document()).encode()).hexdigest()


def make_guard_binding(
    *, plan: Mapping[str, Any], unique_name: str, allocation_id: str,
    ownership_token: str, original_t0_monotonic: float,
    hard_deadline_monotonic: float, clock_domain: str,
    primary_script_sha256: str, secondary_script_sha256: str,
    run_nonce: str | None = None,
) -> GuardBinding:
    lifetime = _finite(
        plan["budget"]["maximum_lifetime_seconds"], "maximum lifetime", allow_string=True
    )
    fraction = _finite(
        plan["budget"]["teardown_fraction"], "teardown fraction", allow_string=True
    )
    if not 0 < fraction < 1:
        raise GuardError("teardown fraction must be between zero and one")
    expected_hard = original_t0_monotonic + lifetime
    if not math.isclose(hard_deadline_monotonic, expected_hard, rel_tol=0, abs_tol=1e-6):
        raise GuardError("hard deadline is not derived from the original pre-create t0")
    token = run_nonce or secrets.token_hex(32)
    digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
    binding = GuardBinding(
        schema_version="episode1.guard-binding.v1",
        plan_sha256=plan["plan_sha256"],
        watchdog_plan_sha256=plan["guard"]["local_watchdog_plan_sha256"],
        run_nonce=token,
        unique_name_sha256=digest(unique_name),
        allocation_id_sha256=digest(allocation_id),
        ownership_token_sha256=digest(ownership_token),
        original_t0_monotonic=original_t0_monotonic,
        teardown_deadline_monotonic=original_t0_monotonic + lifetime * fraction,
        hard_deadline_monotonic=hard_deadline_monotonic,
        clock_domain=clock_domain,
        primary_script_sha256=primary_script_sha256,
        secondary_script_sha256=secondary_script_sha256,
    )
    binding.validate()
    return binding


def _load_closed(path: Path, keys: set[str]) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise GuardError(f"guard receipt {path.name} contains duplicate JSON keys")
            result[key] = item
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _item: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise GuardError(f"cannot read valid guard receipt {path.name}") from exc
    if not isinstance(value, dict) or set(value) != keys:
        raise GuardError(f"guard receipt {path.name} has an open or incomplete schema")
    return value


class FileReceiptGuard:
    """Concrete two-process guard using durable arming and heartbeat receipts."""

    def __init__(
        self, directory: Path, *,
        launcher: Callable[[GuardBinding, Path, float], Sequence[int]],
        process_alive: Callable[[int], bool], monotonic: Callable[[], float],
        heartbeat_max_age_seconds: float = 10.0,
    ) -> None:
        if heartbeat_max_age_seconds <= 0:
            raise ValueError("heartbeat age must be positive")
        self.directory = directory
        self.launcher = launcher
        self.process_alive = process_alive
        self.monotonic = monotonic
        self.heartbeat_max_age_seconds = heartbeat_max_age_seconds
        self.binding: GuardBinding | None = None
        self._pids: tuple[int, int] | None = None

    def _persist_binding(self, binding: GuardBinding) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(self.directory, 0o700)
        path = self.directory / "binding.json"
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (canonical_json(binding.document()) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory_descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def _validate_receipt(self, role: str, *, armed: bool) -> dict[str, Any]:
        if self.binding is None:
            raise GuardError("guard is not bound")
        suffix = "armed" if armed else "heartbeat"
        keys = {
            "schema_version", "role", "binding_sha256", "run_nonce", "pid",
            "observed_monotonic", "initial_provider_poll_ok", "script_sha256",
        }
        value = _load_closed(self.directory / f"{suffix}-{role}.json", keys)
        if value["schema_version"] != f"episode1.guard-{suffix}.v1" or value["role"] != role:
            raise GuardError(f"invalid {role} {suffix} identity")
        expected_script = getattr(self.binding, f"{role}_script_sha256")
        if (
            value["binding_sha256"] != self.binding.sha256
            or not secrets.compare_digest(value["run_nonce"], self.binding.run_nonce)
            or value["script_sha256"] != expected_script
            or value["initial_provider_poll_ok"] is not True
        ):
            raise GuardError(f"{role} {suffix} is not bound to this run")
        pid = value["pid"]
        observed = _finite(value["observed_monotonic"], f"{role} {suffix} time")
        now = _finite(self.monotonic(), f"{role} receipt verification time")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
            raise GuardError(f"{role} {suffix} PID is invalid")
        if observed < self.binding.original_t0_monotonic or observed > now:
            raise GuardError(f"{role} {suffix} clock is outside the bound run")
        if not armed and now - observed > self.heartbeat_max_age_seconds:
            raise GuardError(f"{role} heartbeat is stale")
        if not self.process_alive(pid):
            raise GuardError(f"{role} watchdog process is absent")
        return value

    def arm(self, binding: GuardBinding, *, deadline_monotonic: float) -> Mapping[str, Any]:
        if self.binding is not None:
            raise GuardError("guard instance cannot be rebound")
        binding.validate()
        now = _finite(self.monotonic(), "guard arming time")
        deadline = _finite(deadline_monotonic, "guard arming deadline")
        if now >= deadline:
            raise GuardError("guard arming deadline already reached")
        self._persist_binding(binding)
        self.binding = binding
        pids = tuple(self.launcher(binding, self.directory, deadline_monotonic))
        if len(pids) != 2 or len(set(pids)) != 2:
            raise GuardError("launcher did not return two distinct watchdog PIDs")
        receipts = [self._validate_receipt(role, armed=True) for role in _ROLES]
        if tuple(value["pid"] for value in receipts) != pids:
            raise GuardError("arming receipt PIDs differ from launched watchdogs")
        self._pids = (pids[0], pids[1])
        return {
            "schema_version": "episode1.guard-arm-result.v1",
            "binding_sha256": binding.sha256, "roles": list(_ROLES), "armed": True,
        }

    def healthy(self, binding: GuardBinding, *, deadline_monotonic: float) -> bool:
        if self.binding is None or binding.sha256 != self.binding.sha256:
            return False
        try:
            now = _finite(self.monotonic(), "guard health time")
            deadline = _finite(deadline_monotonic, "guard health deadline")
        except GuardError:
            return False
        if now >= min(deadline, binding.hard_deadline_monotonic):
            return False
        try:
            receipts = [self._validate_receipt(role, armed=False) for role in _ROLES]
        except GuardError:
            return False
        return self._pids == tuple(value["pid"] for value in receipts)


def restart_disposition(
    binding: GuardBinding, *, current_plan_sha256: str, current_clock_domain: str,
    now_monotonic: float, owned_resource_journal_present: bool,
    both_watchdogs_healthy: bool, lifecycle_complete: bool,
) -> str:
    """Require cleanup after every controller restart."""

    binding.validate()
    _ = (
        current_plan_sha256, current_clock_domain, owned_resource_journal_present,
        both_watchdogs_healthy, lifecycle_complete,
    )
    _finite(now_monotonic, "restart reconciliation time")
    return "cleanup_only"
