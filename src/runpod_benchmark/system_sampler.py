"""Bounded Linux/NVIDIA system telemetry for Episode 1 private evidence.

The module does not discover processes or GPUs.  The caller supplies the
expected PID/start ticks and the fixed nvidia-smi binary/device selector.
All unavailable observations are represented by ``value=None`` plus a reason.
"""

from __future__ import annotations

import csv
import errno
import io
import math
import os
import re
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

MAX_COMMAND_BYTES = 128 * 1024
NVIDIA_FIELDS = (
    "uuid", "utilization.gpu", "memory.used", "memory.total", "power.draw",
    "temperature.gpu", "clocks.current.sm", "clocks.current.memory",
    "clocks.current.graphics", "clocks_throttle_reasons.active",
)
NVIDIA_UNITS = (None, "percent", "MiB", "MiB", "W", "C", "MHz", "MHz", "MHz", "bitmask")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,255}\Z")


class SampleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Binding:
    run_id: str
    attempt_id: str
    block: str
    source_boot_id: str
    clock_domain: str = "linux-clock-monotonic"

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not _ID.fullmatch(v) for v in vars(self).values()):
            raise ValueError("binding values must be closed opaque identifiers")


@dataclass(frozen=True)
class ProcessTarget:
    pid: int
    start_ticks: int
    role: str

    def __post_init__(self) -> None:
        if (isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0
                or isinstance(self.start_ticks, bool) or not isinstance(self.start_ticks, int)
                or self.start_ticks < 0):
            raise ValueError("invalid process identity")
        if not isinstance(self.role, str) or not _ID.fullmatch(self.role):
            raise ValueError("invalid process role")


@dataclass(frozen=True)
class CommandResult:
    status: str
    reason: str | None
    stdout: bytes
    returncode: int | None


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _cleanup_group(process: subprocess.Popen[bytes], cleanup_deadline_ns: int,
                   monotonic_ns: Callable[[], int]) -> None:
    pgid = process.pid
    start = monotonic_ns()
    remaining = max(0, cleanup_deadline_ns - start)
    term_deadline = start + remaining * 2 // 5
    kill_deadline = start + remaining * 4 // 5

    def reap_leader_until(deadline: int) -> None:
        while process.poll() is None:
            wait_ns = deadline - monotonic_ns()
            if wait_ns <= 0:
                break
            try:
                process.wait(timeout=min(0.02, wait_ns / 1e9))
            except subprocess.TimeoutExpired:
                pass

    if _group_exists(pgid):
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    reap_leader_until(term_deadline)
    while _group_exists(pgid) and monotonic_ns() < term_deadline:
        time.sleep(min(0.005, max(0.0, (term_deadline - monotonic_ns()) / 1e9)))
    if _group_exists(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    reap_leader_until(kill_deadline)
    while _group_exists(pgid) and monotonic_ns() < cleanup_deadline_ns:
        time.sleep(min(0.005, max(0.0, (cleanup_deadline_ns - monotonic_ns()) / 1e9)))
    reap_leader_until(cleanup_deadline_ns)
    if process.poll() is None:
        raise SampleError("command leader remains after cleanup")
    if _group_exists(pgid):
        raise SampleError("command process group remains after cleanup")


def run_command(argv: Sequence[str], absolute_deadline_ns: int, *,
                cleanup_reserve_ns: int = 250_000_000,
                max_bytes: int = MAX_COMMAND_BYTES,
                monotonic_ns: Callable[[], int] = time.monotonic_ns) -> CommandResult:
    """Run a fixed executable with bounded output and whole-operation deadline."""
    if (not argv or any(not isinstance(x, str) or "\x00" in x for x in argv)
            or not os.path.isabs(argv[0])):
        raise ValueError("command executable must be an absolute path")
    if any(isinstance(x, bool) or not isinstance(x, int) or x <= 0
           for x in (absolute_deadline_ns, cleanup_reserve_ns, max_bytes)):
        raise ValueError("invalid command bound")
    work_deadline = absolute_deadline_ns - cleanup_reserve_ns
    if monotonic_ns() >= work_deadline:
        return CommandResult("unavailable", "deadline_exhausted", b"", None)
    try:
        process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, close_fds=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
        )
    except OSError:
        return CommandResult("unavailable", "spawn_failed", b"", None)
    selector: selectors.BaseSelector | None = None
    buffers: dict[int, bytearray] = {}
    stdout_fd: int | None = None
    try:
        assert process.stdout is not None and process.stderr is not None
        selector = selectors.DefaultSelector()
        stdout_fd = process.stdout.fileno()
        buffers = {stdout_fd: bytearray(), process.stderr.fileno(): bytearray()}
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = work_deadline - monotonic_ns()
            if remaining <= 0:
                return CommandResult("unavailable", "command_timeout", bytes(buffers[stdout_fd]), None)
            events = selector.select(remaining / 1e9)
            if not events:
                return CommandResult("unavailable", "command_timeout", bytes(buffers[stdout_fd]), None)
            for key, _mask in events:
                try:
                    chunk = os.read(key.fd, 16_384)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if sum(len(x) for x in buffers.values()) + len(chunk) > max_bytes:
                    return CommandResult("unavailable", "output_limit", bytes(buffers[stdout_fd]), None)
                buffers[key.fd].extend(chunk)
        remaining = work_deadline - monotonic_ns()
        if remaining <= 0:
            return CommandResult("unavailable", "command_timeout", bytes(buffers[stdout_fd]), None)
        try:
            returncode = process.wait(timeout=remaining / 1e9)
        except subprocess.TimeoutExpired:
            return CommandResult("unavailable", "command_timeout", bytes(buffers[stdout_fd]), None)
        if returncode != 0:
            return CommandResult("unavailable", "command_failed", bytes(buffers[stdout_fd]), returncode)
        return CommandResult("ok", None, bytes(buffers[stdout_fd]), returncode)
    finally:
        if selector is not None:
            selector.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        # Check and clean even after a successful leader exit: a child may hold
        # inherited descriptors closed while remaining in the process group.
        _cleanup_group(process, absolute_deadline_ns, monotonic_ns)


def _metric(source: str, name: str, unit: str, value: int | float | str | None,
            status: str = "ok", reason: str | None = None, scope: str = "device") -> dict[str, object]:
    if value is None and status == "ok":
        raise ValueError("unavailable metric needs explicit status")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite metric")
    return {"source": source, "name": name, "unit": unit, "scope": scope,
            "value": value, "status": status, "reason": reason}


class NvidiaSmiAdapter:
    def __init__(self, binary: Path, device_selector: str,
                 runner: Callable[..., CommandResult] = run_command) -> None:
        if not binary.is_absolute() or not device_selector or len(device_selector) > 128:
            raise ValueError("nvidia-smi path/device selector must be explicit")
        self.binary, self.device_selector, self.runner = binary, device_selector, runner

    def collect(self, deadline_ns: int) -> list[dict[str, object]]:
        argv = [str(self.binary), f"--id={self.device_selector}",
                "--query-gpu=" + ",".join(NVIDIA_FIELDS), "--format=csv,noheader,nounits"]
        result = self.runner(argv, deadline_ns)
        if result.status != "ok":
            return [_metric("nvidia-smi", name, unit or "opaque", None,
                            "unavailable", result.reason, "device")
                    for name, unit in zip(NVIDIA_FIELDS, NVIDIA_UNITS)]
        try:
            text = result.stdout.decode("utf-8", "strict")
            rows = list(csv.reader(io.StringIO(text)))
        except (UnicodeDecodeError, csv.Error):
            rows = []
        if len(rows) != 1 or len(rows[0]) != len(NVIDIA_FIELDS):
            return [_metric("nvidia-smi", name, unit or "opaque", None,
                            "unavailable", "parse_failed", "device")
                    for name, unit in zip(NVIDIA_FIELDS, NVIDIA_UNITS)]
        values: list[dict[str, object]] = []
        for name, unit, raw in zip(NVIDIA_FIELDS, NVIDIA_UNITS, rows[0]):
            raw = raw.strip()
            if raw.lower() in {"n/a", "[not supported]", "not supported", ""}:
                values.append(_metric("nvidia-smi", name, unit or "opaque", None,
                                      "unavailable", "not_supported", "device"))
                continue
            try:
                value: object = raw if name in {"uuid", "clocks_throttle_reasons.active"} else float(raw)
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError
            except ValueError:
                values.append(_metric("nvidia-smi", name, unit or "opaque", None,
                                      "unavailable", "parse_failed", "device"))
            else:
                values.append(_metric("nvidia-smi", name, unit or "opaque", value, scope="device"))
        return values


def _read_bounded(path: Path, maximum: int = 1024 * 1024) -> str:
    try:
        with path.open("rb", buffering=0) as stream:
            data = stream.read(maximum + 1)
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError) as exc:
        raise SampleError("proc_unavailable") from exc
    if len(data) > maximum:
        raise SampleError("proc_oversize")
    try:
        return data.decode("ascii", "strict")
    except UnicodeDecodeError as exc:
        raise SampleError("proc_parse_failed") from exc


def parse_proc_stat(text: str) -> dict[str, int | str]:
    close = text.rfind(")")
    if not text.startswith("(") and " (" not in text:
        raise SampleError("proc_parse_failed")
    if close < 2:
        raise SampleError("proc_parse_failed")
    head, tail = text[:close + 1], text[close + 1:].split()
    prefix = head.split(" ", 1)
    if len(prefix) != 2 or len(tail) < 22:
        raise SampleError("proc_parse_failed")
    try:
        return {"pid": int(prefix[0]), "state": tail[0], "utime_ticks": int(tail[11]),
                "stime_ticks": int(tail[12]), "start_ticks": int(tail[19]),
                "rss_pages": int(tail[21])}
    except (ValueError, IndexError) as exc:
        raise SampleError("proc_parse_failed") from exc


class ProcAdapter:
    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self.root = proc_root

    def identity(self, target: ProcessTarget) -> tuple[int, int]:
        stat = parse_proc_stat(_read_bounded(self.root / str(target.pid) / "stat", 64 * 1024))
        return int(stat["pid"]), int(stat["start_ticks"])

    def collect(self, target: ProcessTarget | None) -> tuple[list[dict[str, object]], tuple[int, int] | None]:
        metrics: list[dict[str, object]] = []
        observed: tuple[int, int] | None = None
        if target is None:
            for name, unit in (("process.cpu_ticks", "ticks"),
                               ("process.cpu.clock_ticks_per_second", "ticks/s"),
                               ("process.rss", "bytes"),
                               ("process.read", "bytes"), ("process.write", "bytes")):
                metrics.append(_metric("procfs", name, unit, None, "unavailable", "prestart", "process"))
        else:
            try:
                stat = parse_proc_stat(_read_bounded(self.root / str(target.pid) / "stat", 64 * 1024))
                observed = (int(stat["pid"]), int(stat["start_ticks"]))
                if observed != (target.pid, target.start_ticks):
                    raise SampleError("identity_changed")
                page_size = os.sysconf("SC_PAGE_SIZE")
                metrics += [
                    _metric("procfs", "process.cpu_ticks", "ticks",
                            int(stat["utime_ticks"]) + int(stat["stime_ticks"]), scope="process"),
                    _metric("sysconf", "process.cpu.clock_ticks_per_second", "ticks/s",
                            int(os.sysconf("SC_CLK_TCK")), scope="process"),
                    _metric("procfs", "process.rss", "bytes", int(stat["rss_pages"]) * page_size, scope="process"),
                ]
                io_values: dict[str, int] = {}
                for line in _read_bounded(self.root / str(target.pid) / "io", 64 * 1024).splitlines():
                    key, sep, value = line.partition(":")
                    if sep and value.strip().isdigit():
                        io_values[key] = int(value.strip())
                for key, name in (("read_bytes", "process.read"), ("write_bytes", "process.write")):
                    if key in io_values:
                        metrics.append(_metric("procfs", name, "bytes", io_values[key], scope="process"))
                    else:
                        metrics.append(_metric("procfs", name, "bytes", None, "unavailable", "not_reported", "process"))
            except SampleError as exc:
                reason = str(exc) if str(exc) in {"identity_changed", "proc_oversize"} else "process_unavailable"
                observed = None
                metrics = [_metric("procfs", name, unit, None, "unavailable", reason, "process")
                           for name, unit in (("process.cpu_ticks", "ticks"),
                                              ("process.cpu.clock_ticks_per_second", "ticks/s"),
                                              ("process.rss", "bytes"),
                                              ("process.read", "bytes"), ("process.write", "bytes"))]
        metrics.extend(self._host())
        return metrics, observed

    def _host(self) -> list[dict[str, object]]:
        cpu_names = (
            "user_including_guest", "nice_including_guest_nice", "system", "idle",
            "iowait", "irq", "softirq", "steal", "guest", "guest_nice",
        )
        specs = tuple((f"host.cpu.{name}_ticks", "ticks") for name in cpu_names) + (
                 ("host.cpu.total_excluding_guest_duplicates_ticks", "ticks"),
                 ("host.cpu.busy_excluding_idle_iowait_ticks", "ticks"),
                 ("host.cpu.logical_count", "count"),
                 ("host.memory.total", "bytes"),
                 ("host.memory.available", "bytes"), ("host.network.rx", "bytes"),
                 ("host.network.tx", "bytes"))
        try:
            cpu_line = _read_bounded(self.root / "stat").splitlines()[0].split()
            if not cpu_line or cpu_line[0] != "cpu":
                raise SampleError("proc_parse_failed")
            cpu_parts = [int(v) for v in cpu_line[1:11]]
            if len(cpu_parts) < 10:
                raise SampleError("proc_parse_failed")
            # Linux user/nice already include guest/guest_nice. Do not add the
            # guest fields again when constructing total or busy time.
            total = sum(cpu_parts[:8])
            busy = total - cpu_parts[3] - cpu_parts[4]
            mem: dict[str, int] = {}
            for line in _read_bounded(self.root / "meminfo").splitlines():
                key, sep, rest = line.partition(":")
                fields = rest.split()
                if sep and fields and fields[0].isdigit():
                    mem[key] = int(fields[0]) * (1024 if len(fields) > 1 and fields[1] == "kB" else 1)
            rx = tx = 0
            lines = _read_bounded(self.root / "net" / "dev").splitlines()[2:]
            for line in lines:
                _interface, sep, values = line.partition(":")
                fields = values.split()
                if not sep or len(fields) < 9:
                    raise SampleError("proc_parse_failed")
                rx += int(fields[0]); tx += int(fields[8])
            logical_count = os.cpu_count()
            if logical_count is None or logical_count <= 0:
                raise SampleError("proc_parse_failed")
            raw = tuple(cpu_parts) + (total, busy, logical_count,
                                      mem["MemTotal"], mem["MemAvailable"], rx, tx)
            return [_metric("procfs", name, unit, value, scope="host")
                    for (name, unit), value in zip(specs, raw)]
        except (SampleError, KeyError, ValueError, IndexError):
            return [_metric("procfs", name, unit, None, "unavailable", "host_unavailable", "host")
                    for name, unit in specs]


class SystemSampler:
    def __init__(self, binding: Binding, gpu: NvidiaSmiAdapter, proc: ProcAdapter, *,
                 interval_ns: int = 1_000_000_000, command_budget_ns: int = 750_000_000,
                 monotonic_ns: Callable[[], int] = time.monotonic_ns,
                 utc_ns: Callable[[], int] = time.time_ns) -> None:
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
               for v in (interval_ns, command_budget_ns)) or command_budget_ns >= interval_ns:
            raise ValueError("invalid sampling cadence/budget")
        self.binding, self.gpu, self.proc = binding, gpu, proc
        self.interval_ns, self.command_budget_ns = interval_ns, command_budget_ns
        self.monotonic_ns, self.utc_ns = monotonic_ns, utc_ns
        self.sequence = 0
        self.last_scheduled_ns: int | None = None
        self.last_observed_ns: int | None = None

    def sample_periodic(self, target: ProcessTarget | None, phase: str, *,
                        hard_deadline_ns: int) -> dict[str, object]:
        """Capture a caller-driven periodic slot at a truthful non-future time.

        Synchronous boundary markers share the ordered stream but must not make
        an immediately following periodic RPC claim a future scheduled time.
        """
        now = self.monotonic_ns()
        scheduled = now if self.last_scheduled_ns is None else max(now, self.last_scheduled_ns + 1)
        return self.sample_slot(scheduled, target, phase,
                                hard_deadline_ns=hard_deadline_ns,
                                slot_kind="periodic")

    def sample_slot(self, scheduled_ns: int, target: ProcessTarget | None,
                    phase: str, *, hard_deadline_ns: int | None = None,
                    slot_kind: str = "periodic") -> dict[str, object]:
        if not isinstance(phase, str) or not _ID.fullmatch(phase):
            raise ValueError("invalid phase")
        if slot_kind not in {"periodic", "measurement_start_boundary", "measurement_end_boundary"}:
            raise ValueError("invalid slot kind")
        if self.last_scheduled_ns is not None and scheduled_ns <= self.last_scheduled_ns:
            raise ValueError("scheduled slots must increase")
        begin = self.monotonic_ns()
        if hard_deadline_ns is not None and begin >= hard_deadline_ns:
            raise TimeoutError("system sampler hard deadline")
        identity_probe_reason = None
        try:
            before_identity = None if target is None else self.proc.identity(target)
        except SampleError as exc:
            before_identity = None
            identity_probe_reason = "identity_changed" if str(exc) == "identity_changed" else "process_unavailable"
        proc_metrics, collected_identity = self.proc.collect(target)
        command_deadline = min(begin + self.command_budget_ns, scheduled_ns + self.interval_ns)
        if hard_deadline_ns is not None:
            command_deadline = min(command_deadline, hard_deadline_ns)
        gpu_metrics = self.gpu.collect(command_deadline)
        try:
            after_identity = None if target is None else self.proc.identity(target)
        except SampleError as exc:
            after_identity = None
            identity_probe_reason = "identity_changed" if str(exc) == "identity_changed" else "process_unavailable"
        end = self.monotonic_ns()
        utc_before = self.utc_ns(); anchor_after = self.monotonic_ns()
        observed = end + (anchor_after - end) // 2
        identity_status = "prestart" if target is None else "ok"
        if target is not None and (identity_probe_reason is not None or before_identity != after_identity or before_identity != collected_identity
                                   or before_identity != (target.pid, target.start_ticks)):
            identity_status = identity_probe_reason or "changed"
            for item in proc_metrics:
                if item["scope"] == "process":
                    item.update(value=None, status="unavailable", reason="identity_changed")
        self.sequence += 1
        missed = max(0, (begin - scheduled_ns) // self.interval_ns)
        record = {
            "schema_version": "episode1.system-sample.v1", "binding": vars(self.binding),
            "sequence": self.sequence, "phase": phase, "slot_kind": slot_kind,
            "scheduled_monotonic_ns": scheduled_ns, "sample_start_monotonic_ns": begin,
            "observed_monotonic_ns": observed,
            "observed_utc_ns": utc_before, "clock_uncertainty_ns": anchor_after - end,
            "schedule_lag_ns": max(0, begin - scheduled_ns), "missed_slots": missed,
            "observed_gap_ns": None if self.last_observed_ns is None else observed - self.last_observed_ns,
            "process_expected": None if target is None else vars(target),
            "process_identity_before": before_identity, "process_identity_after": after_identity,
            "process_identity_status": identity_status,
            "metrics": proc_metrics + gpu_metrics,
        }
        self.last_scheduled_ns, self.last_observed_ns = scheduled_ns, observed
        return record

    def sample_boundary(self, target: ProcessTarget, marker: str, *,
                        hard_deadline_ns: int) -> dict[str, object]:
        """Capture an immediate measured-window boundary without a future slot."""
        if marker not in {"measurement_start", "measurement_end"}:
            raise ValueError("invalid boundary marker")
        now = self.monotonic_ns()
        scheduled = now if self.last_scheduled_ns is None else max(now, self.last_scheduled_ns + 1)
        return self.sample_slot(scheduled, target, "measurement",
                                hard_deadline_ns=hard_deadline_ns,
                                slot_kind=marker + "_boundary")

    def run_until(self, start_ns: int, drain_ns: int, target_for_slot: Callable[[int], ProcessTarget | None],
                  phase_for_slot: Callable[[int], str], emit: Callable[[Mapping[str, object]], None],
                  hard_deadline_ns: int) -> None:
        """Collect inclusive start/drain slots; caller chooses prestart/process phase."""
        if not (start_ns <= drain_ns < hard_deadline_ns):
            raise ValueError("invalid sampling window")
        slot = start_ns
        while slot <= drain_ns:
            now = self.monotonic_ns()
            if now < slot:
                time.sleep((slot - now) / 1e9)
            if self.monotonic_ns() >= hard_deadline_ns:
                raise TimeoutError("system sampler hard deadline")
            emit(self.sample_slot(slot, target_for_slot(slot), phase_for_slot(slot),
                                  hard_deadline_ns=hard_deadline_ns))
            slot += self.interval_ns
