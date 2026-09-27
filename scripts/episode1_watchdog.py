"""Episode 1 local watchdog producer and restart cleanup primitives.

The module never creates provider resources. Provider access, clocks, sleeping, and
process launching are injected so its state machine can be tested without a network.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import math
import os
import secrets
import signal
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


class WatchdogError(RuntimeError):
    pass


ROLES = ("primary", "secondary")
HEX64 = set("0123456789abcdef")
MAX_STATE_BYTES = 1024 * 1024
DEFAULT_PROVIDER_POLL_TIMEOUT_SECONDS = 10.0


def observe_clock_domain() -> str:
    """Return a boot-scoped identity for the local monotonic clock."""
    if sys.platform.startswith("linux"):
        try:
            raw = Path("/proc/sys/kernel/random/boot_id").read_bytes()
        except OSError as exc:
            raise WatchdogError("cannot observe Linux boot clock domain") from exc
        if len(raw) > 128:
            raise WatchdogError("Linux boot clock domain is oversized")
        try:
            boot_id = raw.decode("ascii").strip().lower()
        except UnicodeError as exc:
            raise WatchdogError("Linux boot clock domain is malformed") from exc
        if (len(boot_id) != 36 or boot_id[8] != "-" or boot_id[13] != "-" or
                boot_id[18] != "-" or boot_id[23] != "-" or
                any(char not in "0123456789abcdef-" for char in boot_id)):
            raise WatchdogError("Linux boot clock domain is malformed")
        return f"linux-boot-id:{boot_id}:monotonic"
    if sys.platform == "darwin":
        import re
        try:
            result = subprocess.run(
                ("/usr/sbin/sysctl", "-n", "kern.boottime"), check=True,
                capture_output=True, text=True, timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WatchdogError("cannot observe Darwin boot clock domain") from exc
        match = re.fullmatch(
            r"\{\s*sec\s*=\s*(\d+)\s*,\s*usec\s*=\s*(\d+)\s*\}\s*\S.*\n?",
            result.stdout,
        )
        if match is None:
            raise WatchdogError("Darwin boot clock domain is malformed")
        return f"darwin-kern-boottime:{match.group(1)}:{match.group(2)}:monotonic"
    raise WatchdogError("unsupported platform for boot clock-domain observation")


def _poll_deadline(*, observed: float, timeout: float, ceiling: float) -> float:
    now = _number(observed, "provider poll start time")
    bound = _number(timeout, "provider poll timeout")
    limit = _number(ceiling, "provider poll deadline ceiling")
    if bound <= 0:
        raise WatchdogError("provider poll timeout must be positive")
    if now >= limit:
        raise WatchdogError("provider poll deadline already expired")
    return min(limit, now + bound)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - HEX64:
        raise WatchdogError(f"{label} must be a lowercase SHA-256")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise WatchdogError(f"{label} must be a nonempty string")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WatchdogError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise WatchdogError(f"{label} must be a finite number")
    return result


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WatchdogError(f"{label} must be an integer >= {minimum}")
    return value


def _closed(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise WatchdogError(f"{label} has an open or incomplete schema")
    return value


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WatchdogError("duplicate JSON key")
        result[key] = value
    return result


def load_json(path: Path, *, keys: set[str], label: str) -> Mapping[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise WatchdogError(f"{label} must be a regular non-symlink")
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise WatchdogError(f"{label} permissions expose private state")
            if info.st_size > MAX_STATE_BYTES:
                raise WatchdogError(f"{label} exceeds the state size bound")
            chunks: list[bytes] = []
            remaining = MAX_STATE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > MAX_STATE_BYTES:
                raise WatchdogError(f"{label} exceeds the state size bound")
        finally:
            os.close(descriptor)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except WatchdogError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise WatchdogError(f"cannot read {label}") from exc
    return _closed(value, keys, label)


def atomic_json(path: Path, value: Mapping[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_info = path.parent.lstat()
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise WatchdogError("state parent must be a real directory")
    if stat.S_IMODE(parent_info.st_mode) & 0o077:
        raise WatchdogError("state parent permissions expose private state")
    encoded = (canonical(dict(value)) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        try:
            offset = 0
            while offset < len(encoded):
                written = os.write(fd, encoded[offset:])
                if not isinstance(written, int) or written <= 0:
                    raise OSError("short state write made no progress")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        if exclusive:
            os.link(temporary, path, follow_symlinks=False)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class LaunchPermit:
    schema_version: str
    plan_sha256: str
    watchdog_plan_sha256: str
    run_nonce: str
    unique_name_sha256: str
    ownership_token_sha256: str
    original_t0_monotonic: float
    arm_deadline_monotonic: float
    teardown_deadline_monotonic: float
    hard_deadline_monotonic: float
    clock_domain: str
    entrypoint_sha256: str
    library_sha256: str
    restart_entrypoint_sha256: str
    adapter_sha256: str

    def validate(self) -> None:
        if self.schema_version != "episode1.watchdog-launch-permit.v1":
            raise WatchdogError("unsupported launch permit")
        for field in ("plan_sha256", "watchdog_plan_sha256", "unique_name_sha256",
                      "ownership_token_sha256", "entrypoint_sha256", "library_sha256",
                      "restart_entrypoint_sha256", "adapter_sha256"):
            _digest(getattr(self, field), field)
        _digest(self.run_nonce, "run_nonce")
        _string(self.clock_domain, "clock_domain")
        start = _number(self.original_t0_monotonic, "original_t0_monotonic")
        arm = _number(self.arm_deadline_monotonic, "arm_deadline_monotonic")
        teardown = _number(self.teardown_deadline_monotonic, "teardown_deadline_monotonic")
        hard = _number(self.hard_deadline_monotonic, "hard_deadline_monotonic")
        if not start < arm < teardown < hard:
            raise WatchdogError("launch deadlines must preserve t0 < arm < teardown < hard")

    @property
    def document(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical(self.document).encode())


PERMIT_KEYS = set(LaunchPermit.__annotations__)


def prepare_launch(*, directory: Path, plan_sha256: str, watchdog_plan_sha256: str,
                   unique_name: str, ownership_token: str, original_t0_monotonic: float,
                   arm_deadline_monotonic: float, teardown_deadline_monotonic: float,
                   hard_deadline_monotonic: float, clock_domain: str,
                   entrypoint: Path, library_path: Path, restart_entrypoint: Path,
                   adapter_source: Path, now: Callable[[], float] = time.monotonic,
                   run_nonce: str | None = None) -> LaunchPermit:
    """Persist a one-use permit before create. No provider operation occurs here."""
    current = _number(now(), "current monotonic")
    if current >= arm_deadline_monotonic:
        raise WatchdogError("arming permit expired before provider create")
    try:
        entry_bytes = entrypoint.read_bytes()
        library_bytes = library_path.read_bytes()
        restart_bytes = restart_entrypoint.read_bytes()
        adapter_bytes = adapter_source.read_bytes()
    except OSError as exc:
        raise WatchdogError("cannot read exact watchdog sources") from exc
    digest = lambda text: sha256_bytes(text.encode())
    permit = LaunchPermit(
        "episode1.watchdog-launch-permit.v1", _digest(plan_sha256, "plan_sha256"),
        _digest(watchdog_plan_sha256, "watchdog_plan_sha256"),
        run_nonce or secrets.token_hex(32), digest(unique_name), digest(ownership_token),
        original_t0_monotonic, arm_deadline_monotonic, teardown_deadline_monotonic,
        hard_deadline_monotonic, clock_domain, sha256_bytes(entry_bytes), sha256_bytes(library_bytes),
        sha256_bytes(restart_bytes), sha256_bytes(adapter_bytes),
    )
    permit.validate()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    atomic_json(directory / "launch-permit.json", permit.document, exclusive=True)
    return permit


def read_permit(path: Path) -> LaunchPermit:
    value = load_json(path, keys=PERMIT_KEYS, label="launch permit")
    try:
        permit = LaunchPermit(**value)
    except TypeError as exc:
        raise WatchdogError("launch permit types are invalid") from exc
    permit.validate()
    return permit


@dataclass(frozen=True)
class Authority:
    schema_version: str
    permit_sha256: str
    plan_sha256: str
    run_nonce: str
    private_id: str
    unique_name: str
    ownership_token: str
    billing_started_monotonic: float | None
    original_t0_monotonic: float
    teardown_deadline_monotonic: float
    hard_deadline_monotonic: float
    clock_domain: str

    def validate(self, permit: LaunchPermit) -> None:
        if self.schema_version != "episode1.watchdog-authority.v1":
            raise WatchdogError("unsupported authority")
        if self.permit_sha256 != permit.sha256 or self.plan_sha256 != permit.plan_sha256:
            raise WatchdogError("authority does not bind permit and plan")
        if self.run_nonce != permit.run_nonce:
            raise WatchdogError("authority nonce mismatch")
        _string(self.private_id, "private_id")
        name = _string(self.unique_name, "unique_name")
        token = _string(self.ownership_token, "ownership_token")
        if sha256_bytes(name.encode()) != permit.unique_name_sha256:
            raise WatchdogError("authority unique name mismatch")
        if not secrets.compare_digest(sha256_bytes(token.encode()), permit.ownership_token_sha256):
            raise WatchdogError("authority ownership token mismatch")
        if self.billing_started_monotonic is not None:
            _number(self.billing_started_monotonic, "billing_started_monotonic")
        if (self.original_t0_monotonic != permit.original_t0_monotonic or
            self.teardown_deadline_monotonic != permit.teardown_deadline_monotonic or
            self.hard_deadline_monotonic != permit.hard_deadline_monotonic or
            self.clock_domain != permit.clock_domain):
            raise WatchdogError("authority deadline or clock binding mismatch")

    @property
    def document(self) -> dict[str, Any]:
        return asdict(self)


AUTHORITY_KEYS = set(Authority.__annotations__)


def persist_authority(path: Path, permit: LaunchPermit, *, private_id: str, unique_name: str,
                      ownership_token: str, billing_started_monotonic: float | None) -> Authority:
    authority = Authority(
        "episode1.watchdog-authority.v1", permit.sha256, permit.plan_sha256, permit.run_nonce,
        private_id, unique_name, ownership_token, billing_started_monotonic,
        permit.original_t0_monotonic, permit.teardown_deadline_monotonic,
        permit.hard_deadline_monotonic, permit.clock_domain,
    )
    authority.validate(permit)
    atomic_json(path, authority.document, exclusive=True)
    return authority


def read_authority(path: Path, permit: LaunchPermit) -> Authority:
    value = load_json(path, keys=AUTHORITY_KEYS, label="deletion authority")
    try:
        authority = Authority(**value)
    except TypeError as exc:
        raise WatchdogError("authority types are invalid") from exc
    authority.validate(permit)
    return authority


class CleanupProvider(Protocol):
    def poll_owned(self, authority: Authority, *, deadline_monotonic: float) -> bool: ...
    def delete_owned(self, authority: Authority, *, deadline_monotonic: float) -> bool: ...
    def inventory_absent(self, authority: Authority, *, deadline_monotonic: float) -> bool: ...
    def direct_not_found(self, authority: Authority, *, deadline_monotonic: float) -> bool: ...


def _receipt(role: str, binding: Mapping[str, Any], script_sha256: str, pid: int,
             observed: float, suffix: str) -> dict[str, Any]:
    return {
        "schema_version": f"episode1.guard-{suffix}.v1", "role": role,
        "binding_sha256": _digest(binding["binding_sha256"], "binding_sha256"),
        "run_nonce": _digest(binding["run_nonce"], "run_nonce"), "pid": pid,
        "observed_monotonic": observed, "initial_provider_poll_ok": True,
        "script_sha256": _digest(script_sha256, "script_sha256"),
    }


def _cleanup(provider: CleanupProvider, authority: Authority, *, deadline: float,
             monotonic: Callable[[], float], sleep: Callable[[float], None],
             retry_delays: Sequence[float]) -> dict[str, Any]:
    if not retry_delays:
        raise WatchdogError("cleanup retry schedule must not be empty")
    checked_delays = tuple(_number(value, "cleanup retry delay") for value in retry_delays)
    if any(value < 0 for value in checked_delays):
        raise WatchdogError("cleanup retry delays must be nonnegative")
    attempts: list[dict[str, Any]] = []
    acknowledged = absent = not_found = False
    for delay in checked_delays:
        now = _number(monotonic(), "cleanup time")
        if now >= deadline:
            break
        if delay:
            sleep(min(float(delay), max(0.0, deadline - now)))
        if monotonic() >= deadline:
            break
        # Proof is atomic per attempt: no fact from a previous attempt can be
        # combined with later reads or retained after an exception.
        acknowledged = absent = not_found = False
        item: dict[str, Any] = {"attempt": len(attempts) + 1}
        calls = (
            ("delete", "delete_acknowledged", provider.delete_owned),
            ("inventory", "inventory_absent", provider.inventory_absent),
            ("direct", "direct_not_found", provider.direct_not_found),
        )
        values: list[bool] = []
        for label, field, operation in calls:
            if _number(monotonic(), "cleanup time") >= deadline:
                item["deadline_exceeded"] = True
                break
            try:
                answer = operation(authority, deadline_monotonic=deadline)
                if not isinstance(answer, bool):
                    raise WatchdogError(f"provider {label} result must be boolean")
                if _number(monotonic(), "cleanup time") >= deadline:
                    item["deadline_exceeded"] = True
                    break
                item[field] = answer
                values.append(answer)
            except Exception as exc:
                item[f"{label}_error"] = type(exc).__name__
                values.append(False)
                # Inventory and direct evidence would no longer form one clean
                # ordered attempt, so retry the whole sequence.
                break
        if len(values) == 3 and not item.get("deadline_exceeded"):
            acknowledged, absent, not_found = values
        attempts.append(item)
        if _number(monotonic(), "cleanup time") >= deadline:
            acknowledged = absent = not_found = False
            item["deadline_exceeded"] = True
            break
        if acknowledged and absent and not_found:
            break
    return {"attempts": attempts, "delete_acknowledged": acknowledged,
            "inventory_absent": absent, "direct_not_found": not_found,
            "verified": acknowledged and absent and not_found,
            "status": "verified-cleanup" if acknowledged and absent and not_found
                      else "cleanup-unverified"}


def run_guard(*, role: str, permit_path: Path, authority_path: Path, binding_path: Path,
              entrypoint_path: Path, library_path: Path, adapter_source: Path,
              provider: CleanupProvider,
              heartbeat_seconds: float, retry_delays: Sequence[float],
              poll_timeout_seconds: float = DEFAULT_PROVIDER_POLL_TIMEOUT_SECONDS,
              clock_domain: Callable[[], str] = observe_clock_domain,
              monotonic: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep, pid: int | None = None) -> Mapping[str, Any]:
    """Run one watchdog. This function only polls and deletes an already-owned resource."""
    if role not in ROLES:
        raise WatchdogError("invalid watchdog role")
    permit = read_permit(permit_path)
    if sha256_bytes(entrypoint_path.read_bytes()) != permit.entrypoint_sha256:
        raise WatchdogError("executed entrypoint bytes differ from pre-create permit")
    if sha256_bytes(library_path.read_bytes()) != permit.library_sha256:
        raise WatchdogError("watchdog library bytes differ from pre-create permit")
    if sha256_bytes(adapter_source.read_bytes()) != permit.adapter_sha256:
        raise WatchdogError("provider adapter bytes differ from pre-create permit")
    authority = read_authority(authority_path, permit)
    current_clock_domain = _string(clock_domain(), "observed clock_domain")
    if current_clock_domain != permit.clock_domain:
        raise WatchdogError("clock domain changed; stored monotonic deadlines are invalid")
    binding_keys = {"schema_version", "binding_sha256", "plan_sha256", "run_nonce",
                    "allocation_id_sha256", "clock_domain", "hard_deadline_monotonic",
                    "teardown_deadline_monotonic", "script_sha256"}
    binding = load_json(binding_path, keys=binding_keys, label="worker binding")
    if (binding["schema_version"] != "episode1.watchdog-worker-binding.v1" or
        binding["plan_sha256"] != permit.plan_sha256 or binding["run_nonce"] != permit.run_nonce or
        binding["allocation_id_sha256"] != sha256_bytes(authority.private_id.encode()) or
        binding["clock_domain"] != permit.clock_domain or
        binding["hard_deadline_monotonic"] != permit.hard_deadline_monotonic or
        binding["teardown_deadline_monotonic"] != permit.teardown_deadline_monotonic or
        binding["script_sha256"] != permit.entrypoint_sha256):
        raise WatchdogError("worker binding does not match durable authority")
    process_id = pid if pid is not None else os.getpid()
    _integer(process_id, "pid", 2)
    heartbeat = _number(heartbeat_seconds, "heartbeat_seconds")
    poll_timeout = _number(poll_timeout_seconds, "poll_timeout_seconds")
    if heartbeat <= 0:
        raise WatchdogError("heartbeat_seconds must be positive")
    if poll_timeout <= 0:
        raise WatchdogError("poll_timeout_seconds must be positive")
    observed = _number(monotonic(), "watchdog arming time")
    arm_ceiling = min(permit.arm_deadline_monotonic, permit.teardown_deadline_monotonic)
    if observed >= arm_ceiling:
        raise WatchdogError("watchdog did not arm before the pre-create expiry")
    poll_deadline = _poll_deadline(observed=observed, timeout=poll_timeout, ceiling=arm_ceiling)
    answer = provider.poll_owned(authority, deadline_monotonic=poll_deadline)
    if not isinstance(answer, bool) or not answer:
        raise WatchdogError("initial provider ownership poll failed")
    observed = _number(monotonic(), "arming poll completion time")
    if observed >= poll_deadline:
        raise WatchdogError("initial provider poll completed after arming expiry")
    cleanup_started = False
    cleanup_result: Mapping[str, Any] | None = None
    cleanup_receipt_written = False

    def cleanup_and_record() -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        nonlocal cleanup_started, cleanup_result, cleanup_receipt_written
        cleanup_started = True
        cleanup_result = _cleanup(
            provider, authority, deadline=permit.hard_deadline_monotonic,
            monotonic=monotonic, sleep=sleep, retry_delays=retry_delays,
        )
        proof = {
            "schema_version": "episode1.watchdog-cleanup.v1",
            "role": role,
            "permit_sha256": permit.sha256,
            "plan_sha256": permit.plan_sha256,
            "run_nonce": permit.run_nonce,
            "private_id_sha256": sha256_bytes(authority.private_id.encode()),
            "clock_domain": permit.clock_domain,
            "hard_deadline_monotonic": permit.hard_deadline_monotonic,
            **cleanup_result,
        }
        atomic_json(binding_path.parent / f"cleanup-{role}.json", proof)
        cleanup_receipt_written = True
        return cleanup_result, proof

    try:
        atomic_json(binding_path.parent / f"armed-{role}.json",
                    _receipt(role, binding, permit.entrypoint_sha256, process_id, observed, "armed"))
        while True:
            observed = _number(monotonic(), "watchdog time")
            if observed >= permit.teardown_deadline_monotonic:
                break
            poll_deadline = _poll_deadline(
                observed=observed, timeout=poll_timeout,
                ceiling=permit.teardown_deadline_monotonic,
            )
            try:
                answer = provider.poll_owned(authority, deadline_monotonic=poll_deadline)
            except Exception:
                answer = False
            if not isinstance(answer, bool):
                raise WatchdogError("provider ownership poll result must be boolean")
            observed = _number(monotonic(), "watchdog poll completion time")
            if observed >= poll_deadline:
                answer = False
            if observed >= permit.teardown_deadline_monotonic:
                break
            if answer:
                atomic_json(binding_path.parent / f"heartbeat-{role}.json",
                            _receipt(role, binding, permit.entrypoint_sha256, process_id,
                                     observed, "heartbeat"))
            sleep(min(heartbeat, max(0.0, permit.teardown_deadline_monotonic - monotonic())))
        result, proof = cleanup_and_record()
        if not result["verified"]:
            raise WatchdogError("watchdog cleanup was not verified")
        return proof
    except BaseException as primary:
        if not cleanup_started:
            try:
                cleanup_and_record()
            except BaseException as cleanup_error:
                raise WatchdogError(
                    "watchdog failed and cleanup is not verified: "
                    f"{type(cleanup_error).__name__}"
                ) from primary
        if (cleanup_result is None or not cleanup_result["verified"] or
                not cleanup_receipt_written):
            raise WatchdogError("watchdog failed and cleanup is not verified") from primary
        raise


def worker_binding_document(*, permit: LaunchPermit, authority: Authority,
                            guard_binding_sha256: str) -> dict[str, Any]:
    return {"schema_version": "episode1.watchdog-worker-binding.v1",
            "binding_sha256": _digest(guard_binding_sha256, "guard_binding_sha256"),
            "plan_sha256": permit.plan_sha256, "run_nonce": permit.run_nonce,
            "allocation_id_sha256": sha256_bytes(authority.private_id.encode()),
            "clock_domain": permit.clock_domain,
            "hard_deadline_monotonic": permit.hard_deadline_monotonic,
            "teardown_deadline_monotonic": permit.teardown_deadline_monotonic,
            "script_sha256": permit.entrypoint_sha256}


def restart_cleanup(*, permit_path: Path, authority_path: Path, provider: CleanupProvider,
                    current_plan_sha256: str, current_clock_domain: str | None = None,
                    restart_entrypoint_path: Path, library_path: Path,
                    clock_domain: Callable[[], str] = observe_clock_domain,
                    monotonic: Callable[[], float] = time.monotonic,
                    sleep: Callable[[float], None] = time.sleep,
                    retry_delays: Sequence[float] = (0, 1, 2)) -> Mapping[str, Any]:
    """Cleanup-only recovery. There is deliberately no create capability in its protocol."""
    permit = read_permit(permit_path)
    if current_plan_sha256 != permit.plan_sha256:
        raise WatchdogError("restart plan differs from durable authority")
    if sha256_bytes(restart_entrypoint_path.read_bytes()) != permit.restart_entrypoint_sha256:
        raise WatchdogError("restart entrypoint bytes differ from pre-create permit")
    if sha256_bytes(library_path.read_bytes()) != permit.library_sha256:
        raise WatchdogError("watchdog library bytes differ from pre-create permit")
    authority = read_authority(authority_path, permit)
    observed_clock_domain = _string(clock_domain(), "observed clock_domain")
    if current_clock_domain is not None and current_clock_domain != observed_clock_domain:
        raise WatchdogError("supplied clock domain is not the independently observed domain")
    if observed_clock_domain != permit.clock_domain:
        raise WatchdogError("clock domain changed; original monotonic deadline cannot be extended")
    now = _number(monotonic(), "restart time")
    result = _cleanup(provider, authority, deadline=permit.hard_deadline_monotonic,
                      monotonic=monotonic, sleep=sleep, retry_delays=retry_delays)
    receipt = {"schema_version": "episode1.restart-cleanup.v1", "permit_sha256": permit.sha256,
               "plan_sha256": permit.plan_sha256, "run_nonce": permit.run_nonce,
               "clock_domain": permit.clock_domain, "observed_monotonic": now,
               "hard_deadline_monotonic": permit.hard_deadline_monotonic, **result}
    atomic_json(permit_path.parent / "restart-cleanup.json", receipt)
    if not result["verified"]:
        raise WatchdogError("restart cleanup was not verified before the original deadline")
    return receipt


def build_guard_commands(*, python: Path, entrypoint: Path, state_directory: Path,
                         guard_directory: Path, adapter_spec: str, adapter_source: Path,
                         heartbeat_seconds: float, poll_timeout_seconds: float,
                         retry_delays: Sequence[float],
                         sleep_preventer: Sequence[str]
                         ) -> tuple[Mapping[str, tuple[str, ...]], tuple[str, ...]]:
    """Build direct worker commands plus a separately tracked sleep inhibitor."""
    heartbeat = _number(heartbeat_seconds, "heartbeat_seconds")
    poll_timeout = _number(poll_timeout_seconds, "poll_timeout_seconds")
    if heartbeat <= 0 or poll_timeout <= 0 or not sleep_preventer:
        raise WatchdogError("positive heartbeat, poll timeout, and sleep prevention command are required")
    if sum(item == "{worker_pid}" for item in sleep_preventer) != 1:
        raise WatchdogError("sleep prevention command needs one {worker_pid} placeholder")
    delays = tuple(_number(value, "retry delay") for value in retry_delays)
    if not delays or any(value < 0 for value in delays):
        raise WatchdogError("nonnegative cleanup retry delays are required")
    for path, label in ((python, "python"), (entrypoint, "entrypoint"),
                        (state_directory, "state directory"),
                        (guard_directory, "guard directory"),
                        (adapter_source, "adapter source")):
        if not path.is_absolute():
            raise WatchdogError(f"{label} must be an absolute path")
    commands: dict[str, tuple[str, ...]] = {}
    for role in ROLES:
        command = [str(python), str(entrypoint), "--role", role,
                   "--state-directory", str(state_directory), "--guard-directory",
                   str(guard_directory), "--adapter", adapter_spec,
                   "--adapter-source", str(adapter_source), "--heartbeat-seconds", str(heartbeat),
                   "--poll-timeout-seconds", str(poll_timeout)]
        for delay in delays:
            command.extend(("--retry-delay", str(delay)))
        commands[role] = tuple(command)
    return commands, tuple(_string(item, "sleep prevention argument") for item in sleep_preventer)


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_owned_groups(children: Sequence[subprocess.Popen[bytes]], *, deadline: float,
                            monotonic: Callable[[], float]) -> bool:
    """TERM/CONT, KILL, reap leaders, and prove every owned session absent."""
    groups = tuple(child.pid for child in children)
    for group in groups:
        for sig in (signal.SIGCONT, signal.SIGTERM):
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                break
    remaining = max(0.0, deadline - monotonic())
    term_until = monotonic() + min(0.25, remaining / 2.0)
    while monotonic() < term_until:
        for child in children:
            child.poll()
        if not any(_group_exists(group) for group in groups):
            return all(child.poll() is not None for child in children)
        time.sleep(min(0.01, max(0.0, term_until - monotonic())))
    for group in groups:
        for sig in (signal.SIGCONT, signal.SIGKILL):
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                break
    while monotonic() < deadline:
        for child in children:
            child.poll()
        if not any(_group_exists(group) for group in groups):
            return all(child.poll() is not None for child in children)
        time.sleep(min(0.01, max(0.0, deadline - monotonic())))
    for child in children:
        child.poll()
    return all(child.poll() is not None for child in children) and not any(
        _group_exists(group) for group in groups)


class ProcessLauncher:
    """Concrete two-process launcher with partial-arm rollback."""
    def __init__(self, *, permit_path: Path, authority_path: Path,
                 commands: Mapping[str, Sequence[str]], cleanup_partial: Callable[[float], None],
                 sleep_preventer: Sequence[str] = (),
                 monotonic: Callable[[], float] = time.monotonic,
                 popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen) -> None:
        if set(commands) != set(ROLES):
            raise WatchdogError("launcher needs exactly primary and secondary commands")
        if sleep_preventer and sum(item == "{worker_pid}" for item in sleep_preventer) != 1:
            raise WatchdogError("sleep prevention command needs one {worker_pid} placeholder")
        self.commands = {role: tuple(commands[role]) for role in ROLES}
        self.sleep_preventer = tuple(sleep_preventer)
        self.permit_path, self.authority_path = permit_path, authority_path
        self.cleanup_partial = cleanup_partial
        self.monotonic, self.popen = monotonic, popen

    def __call__(self, binding: Any, directory: Path, deadline_monotonic: float) -> Sequence[int]:
        hard_deadline = _number(getattr(binding, "hard_deadline_monotonic", None),
                                "guard hard deadline")
        children: list[subprocess.Popen[bytes]] = []
        workers: list[subprocess.Popen[bytes]] = []
        permit: LaunchPermit | None = None
        try:
            permit = read_permit(self.permit_path)
            if hard_deadline != permit.hard_deadline_monotonic:
                raise WatchdogError("candidate guard hard deadline differs from pre-create permit")
            if self.monotonic() >= min(deadline_monotonic, permit.arm_deadline_monotonic):
                raise WatchdogError("arming expired before watchdog launch")
            authority = read_authority(self.authority_path, permit)
            guard_sha = _string(getattr(binding, "sha256"), "guard binding digest")
            if getattr(binding, "run_nonce") != permit.run_nonce:
                raise WatchdogError("candidate guard nonce must consume pre-create permit nonce")
            atomic_json(directory / "worker-binding.json",
                        worker_binding_document(permit=permit, authority=authority,
                                                guard_binding_sha256=guard_sha), exclusive=True)
            for role in ROLES:
                child = self.popen(self.commands[role], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
                children.append(child)
                workers.append(child)
                if self.sleep_preventer:
                    inhibitor = tuple(str(child.pid) if item == "{worker_pid}" else item
                                      for item in self.sleep_preventer)
                    children.append(self.popen(
                        inhibitor, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True))
            while self.monotonic() < min(deadline_monotonic, permit.arm_deadline_monotonic):
                if any(child.poll() is not None for child in children):
                    raise WatchdogError("watchdog exited while arming")
                if all((directory / f"armed-{role}.json").exists() for role in ROLES):
                    return [child.pid for child in workers]
                time.sleep(.01)
            raise WatchdogError("watchdogs failed to arm before bound expiry")
        except BaseException as primary:
            process_cleanup_deadline = min(
                permit.teardown_deadline_monotonic if permit is not None else hard_deadline,
                hard_deadline,
            )
            processes_absent = _terminate_owned_groups(
                children, deadline=process_cleanup_deadline, monotonic=self.monotonic)
            try:
                self.cleanup_partial(hard_deadline)
            except BaseException as cleanup_error:
                raise WatchdogError(
                    f"partial-arm provider cleanup failed: {type(cleanup_error).__name__}"
                ) from primary
            if not processes_absent:
                raise WatchdogError("partial watchdog process groups remain live") from primary
            raise


def load_provider_factory(spec: str, expected_source: Path, expected_sha256: str) -> CleanupProvider:
    """Entrypoint glue: import a digest-bound local provider factory."""
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise WatchdogError("adapter must be module:function")
    if sha256_bytes(expected_source.read_bytes()) != expected_sha256:
        raise WatchdogError("provider adapter source digest mismatch")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise WatchdogError("provider adapter factory is not callable")
    source = inspect.getsourcefile(factory)
    if source is None or Path(source).resolve() != expected_source.resolve():
        raise WatchdogError("imported provider adapter is not the bound source")
    provider = factory()
    for forbidden in ("create", "create_pod", "create_allocation"):
        if callable(getattr(provider, forbidden, None)):
            raise WatchdogError("cleanup worker adapter exposes a forbidden create capability")
    return provider
