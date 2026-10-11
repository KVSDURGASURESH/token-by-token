"""Bounded native facts used by the Episode 1 remote control service.

The CUDA ABI calls run only in a disposable child process.  Filesystem seams
are injectable for deterministic tests; production reads are capped and check
the caller's original monotonic deadline before and after every operation.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_WORKER_OUTPUT = 16 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_PROC_RECORD_BYTES = 64 * 1024
MAX_PROC_TABLE_BYTES = 8 * 1024 * 1024
MAX_PROCESSES = 131_072
MAX_FDS_PER_PROCESS = 262_144
MAX_TOTAL_FDS = 1_048_576
CLEANUP_RESERVE_NS = 250_000_000
VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,2}$")


class NativeProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerResult:
    status: str
    stdout: bytes
    reason: str | None


def _check_deadline(deadline_ns: int, clock: Callable[[], int], reason: str) -> None:
    if isinstance(deadline_ns, bool) or not isinstance(deadline_ns, int):
        raise NativeProbeError("invalid_deadline")
    if clock() >= deadline_ns:
        raise NativeProbeError(reason)


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _cleanup_group(
    process: subprocess.Popen[bytes], deadline_ns: int, clock: Callable[[], int]
) -> None:
    """Kill the entire owned group and reap its leader within the original deadline."""
    started = clock()
    remaining = max(0, deadline_ns - started)
    term_deadline = started + remaining // 3
    kill_deadline = started + remaining * 2 // 3

    def signal_group(value: int) -> None:
        if _group_exists(process.pid):
            try:
                os.killpg(process.pid, value)
            except ProcessLookupError:
                pass

    def reap_until(limit: int) -> None:
        while process.poll() is None:
            left = limit - clock()
            if left <= 0:
                return
            try:
                process.wait(timeout=min(0.01, left / 1e9))
            except subprocess.TimeoutExpired:
                pass

    signal_group(signal.SIGTERM)
    reap_until(term_deadline)
    while _group_exists(process.pid) and clock() < term_deadline:
        time.sleep(min(0.002, max(0.0, (term_deadline - clock()) / 1e9)))
    signal_group(signal.SIGKILL)
    reap_until(kill_deadline)
    while _group_exists(process.pid) and clock() < deadline_ns:
        time.sleep(min(0.002, max(0.0, (deadline_ns - clock()) / 1e9)))
    reap_until(deadline_ns)
    if process.poll() is None or _group_exists(process.pid):
        raise NativeProbeError("worker_cleanup_incomplete")


def run_worker(
    argv: Sequence[str], deadline_ns: int, *,
    max_bytes: int = MAX_WORKER_OUTPUT,
    cleanup_reserve_ns: int = CLEANUP_RESERVE_NS,
    clock: Callable[[], int] = time.monotonic_ns,
) -> WorkerResult:
    """Run an absolute executable with bounded output and group cleanup.

    Cleanup always inspects the process group, including after a normal leader
    exit, so a forked descendant cannot survive a successful-looking worker.
    """
    if not argv or any(not isinstance(v, str) or "\0" in v for v in argv):
        raise NativeProbeError("invalid_worker_argv")
    if not os.path.isabs(argv[0]):
        raise NativeProbeError("worker_executable_not_absolute")
    for value in (deadline_ns, max_bytes, cleanup_reserve_ns):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise NativeProbeError("invalid_worker_bound")
    work_deadline = deadline_ns - cleanup_reserve_ns
    if clock() >= work_deadline:
        return WorkerResult("unavailable", b"", "deadline_exhausted")
    try:
        process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, close_fds=True,
            env={
                "PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C",
                # Fixed image locations, rather than an ambient caller value.
                # CUDA's dlopened dependencies must remain discoverable after
                # the worker deliberately drops the daemon environment.
                "LD_LIBRARY_PATH": (
                    "/usr/local/cuda/lib64:/usr/local/nvidia/lib:"
                    "/usr/local/nvidia/lib64"
                ),
            },
        )
    except OSError:
        return WorkerResult("unavailable", b"", "spawn_failed")

    selector: selectors.BaseSelector | None = None
    buffers: dict[int, bytearray] = {}
    stdout_fd: int | None = None
    result = WorkerResult("unavailable", b"", "setup_failed")
    cleanup_error: BaseException | None = None
    try:
        assert process.stdout is not None and process.stderr is not None
        selector = selectors.DefaultSelector()
        stdout_fd = process.stdout.fileno()
        buffers = {stdout_fd: bytearray(), process.stderr.fileno(): bytearray()}
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        done = False
        while selector.get_map() and not done:
            remaining = work_deadline - clock()
            if remaining <= 0:
                result = WorkerResult("unavailable", bytes(buffers[stdout_fd]), "worker_timeout")
                break
            events = selector.select(remaining / 1e9)
            if not events:
                result = WorkerResult("unavailable", bytes(buffers[stdout_fd]), "worker_timeout")
                break
            for key, _ in events:
                try:
                    chunk = os.read(key.fd, 16_384)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if sum(len(item) for item in buffers.values()) + len(chunk) > max_bytes:
                    result = WorkerResult("unavailable", bytes(buffers[stdout_fd]), "output_limit")
                    done = True
                    break
                buffers[key.fd].extend(chunk)
        if result.reason == "setup_failed":
            remaining = work_deadline - clock()
            if remaining <= 0:
                result = WorkerResult("unavailable", bytes(buffers[stdout_fd]), "worker_timeout")
            else:
                try:
                    returncode = process.wait(timeout=remaining / 1e9)
                except subprocess.TimeoutExpired:
                    result = WorkerResult("unavailable", bytes(buffers[stdout_fd]), "worker_timeout")
                else:
                    result = (
                        WorkerResult("ok", bytes(buffers[stdout_fd]), None)
                        if returncode == 0 else
                        WorkerResult("unavailable", bytes(buffers[stdout_fd]), "worker_failed")
                    )
    finally:
        if selector is not None:
            selector.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        try:
            _cleanup_group(process, deadline_ns, clock)
        except BaseException as exc:
            cleanup_error = exc
    if cleanup_error is not None:
        raise cleanup_error
    _check_deadline(deadline_ns, clock, "deadline_exhausted_after_worker")
    return result


def query_library_versions(
    deadline_ns: int, *, runner: Callable[..., WorkerResult] = run_worker,
    python: str = sys.executable, worker_path: str | Path | None = None,
) -> Mapping[str, str]:
    # Execute the exact installed helper by absolute path.  The child uses
    # isolated Python flags and run_worker supplies a closed environment, so
    # package discovery never depends on cwd, PYTHONPATH, user site, or .pth.
    helper = os.path.abspath(os.fspath(worker_path or __file__))
    result = runner(
        [python, "-I", "-S", helper, "--ctypes-worker"],
        deadline_ns, max_bytes=MAX_WORKER_OUTPUT,
    )
    if result.status != "ok" or result.reason is not None:
        raise NativeProbeError("ctypes_worker_unavailable")
    def closed_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value
    try:
        value = json.loads(
            result.stdout,
            object_pairs_hook=closed_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise NativeProbeError("ctypes_worker_invalid_json") from exc
    if not isinstance(value, dict) or set(value) != {"cuda_runtime_version", "nvrtc_version"}:
        raise NativeProbeError("ctypes_worker_open_schema")
    if any(not isinstance(v, str) or VERSION.fullmatch(v) is None for v in value.values()):
        raise NativeProbeError("ctypes_worker_invalid_version")
    _check_deadline(deadline_ns, time.monotonic_ns, "deadline_after_ctypes_evidence")
    return value


def _ctypes_worker() -> int:
    """Child-only ABI queries; the daemon must never call this directly."""
    try:
        cudart = ctypes.CDLL("libcudart.so")
        raw = ctypes.c_int()
        if cudart.cudaRuntimeGetVersion(ctypes.byref(raw)) != 0:
            raise RuntimeError
        major, remainder = divmod(raw.value, 1000)
        minor, patch = divmod(remainder, 10)
        nvrtc = ctypes.CDLL("libnvrtc.so")
        nv_major, nv_minor = ctypes.c_int(), ctypes.c_int()
        if nvrtc.nvrtcVersion(ctypes.byref(nv_major), ctypes.byref(nv_minor)) != 0:
            raise RuntimeError
        payload = {
            "cuda_runtime_version": f"{major}.{minor}.{patch}",
            "nvrtc_version": f"{nv_major.value}.{nv_minor.value}",
        }
        os.write(1, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        return 0
    except BaseException:
        return 2


class FileSource(Protocol):
    def read(self, path: str, maximum: int, deadline_ns: int,
             clock: Callable[[], int]) -> bytes: ...
    def pids(self, deadline_ns: int, clock: Callable[[], int]) -> Iterable[int]: ...
    def fds(self, pid: int, deadline_ns: int,
            clock: Callable[[], int]) -> Iterable[str]: ...
    def readlink(self, path: str, deadline_ns: int,
                 clock: Callable[[], int]) -> str: ...


class LinuxFileSource:
    def read(self, path: str, maximum: int, deadline_ns: int,
             clock: Callable[[], int]) -> bytes:
        if maximum <= 0:
            raise NativeProbeError("invalid_read_bound")
        _check_deadline(deadline_ns, clock, "deadline_before_read")
        required = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
        if any(not hasattr(os, name) for name in required):
            raise NativeProbeError("safe_open_flags_unavailable")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            _check_deadline(deadline_ns, clock, "deadline_after_stat")
            if not stat.S_ISREG(info.st_mode):
                raise NativeProbeError("file_not_regular")
            if info.st_size > maximum:
                raise NativeProbeError("file_too_large")
            pieces: list[bytes] = []
            total = 0
            while True:
                _check_deadline(deadline_ns, clock, "deadline_during_read")
                chunk = os.read(fd, min(8192, maximum + 1 - total))
                _check_deadline(deadline_ns, clock, "deadline_during_read")
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise NativeProbeError("file_too_large")
                pieces.append(chunk)
            value = b"".join(pieces)
            _check_deadline(deadline_ns, clock, "deadline_after_read")
            return value
        finally:
            os.close(fd)

    def pids(self, deadline_ns: int, clock: Callable[[], int]) -> Iterable[int]:
        _check_deadline(deadline_ns, clock, "deadline_before_proc_inventory")
        with os.scandir("/proc") as entries:
            count = 0
            for entry in entries:
                _check_deadline(deadline_ns, clock, "deadline_during_proc_inventory")
                if entry.name.isdigit():
                    count += 1
                    if count > MAX_PROCESSES:
                        raise NativeProbeError("process_limit")
                    yield int(entry.name)
        _check_deadline(deadline_ns, clock, "deadline_after_proc_inventory")

    def fds(self, pid: int, deadline_ns: int,
            clock: Callable[[], int]) -> Iterable[str]:
        _check_deadline(deadline_ns, clock, "deadline_before_fd_inventory")
        with os.scandir(f"/proc/{pid}/fd") as entries:
            count = 0
            for entry in entries:
                _check_deadline(deadline_ns, clock, "deadline_during_fd_inventory")
                count += 1
                if count > MAX_FDS_PER_PROCESS:
                    raise NativeProbeError("fd_process_limit")
                yield entry.path
        _check_deadline(deadline_ns, clock, "deadline_after_fd_inventory")

    def readlink(self, path: str, deadline_ns: int,
                 clock: Callable[[], int]) -> str:
        _check_deadline(deadline_ns, clock, "deadline_before_readlink")
        value = os.readlink(path)
        _check_deadline(deadline_ns, clock, "deadline_after_readlink")
        return value


def bounded_read(
    path: str | Path, maximum: int, deadline_ns: int, *,
    source: FileSource | None = None,
    clock: Callable[[], int] = time.monotonic_ns,
) -> bytes:
    return (source or LinuxFileSource()).read(str(path), maximum, deadline_ns, clock)


def bounded_readlink(
    path: str | Path, deadline_ns: int, *, source: FileSource | None = None,
    clock: Callable[[], int] = time.monotonic_ns,
) -> str:
    return (source or LinuxFileSource()).readlink(str(path), deadline_ns, clock)


def _parse_stat(pid: int, raw: bytes) -> tuple[int, int]:
    try:
        text = raw.decode("ascii")
        left = text.find(" ")
        tail = text[text.rfind(")") + 2:].split()
        if int(text[:left]) != pid:
            raise ValueError
        return int(tail[1]), int(tail[19])
    except (UnicodeError, ValueError, IndexError) as exc:
        raise NativeProbeError("invalid_proc_stat") from exc


def proc_identity(
    pid: int, deadline_ns: int, *, source: FileSource | None = None,
    clock: Callable[[], int] = time.monotonic_ns,
) -> tuple[int, int]:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise NativeProbeError("invalid_pid")
    fs = source or LinuxFileSource()
    value = _parse_stat(
        pid, fs.read(f"/proc/{pid}/stat", MAX_PROC_RECORD_BYTES, deadline_ns, clock)
    )
    _check_deadline(deadline_ns, clock, "deadline_after_proc_identity")
    return value


def process_tree(
    root_pid: int, deadline_ns: int, *, source: FileSource | None = None,
    clock: Callable[[], int] = time.monotonic_ns,
) -> set[int]:
    snapshot, owned = _process_snapshot(
        root_pid, deadline_ns, source=source, clock=clock
    )
    del snapshot
    return owned


def _process_snapshot(
    root_pid: int, deadline_ns: int, *, source: FileSource | None = None,
    clock: Callable[[], int] = time.monotonic_ns,
) -> tuple[dict[int, tuple[int, int]], set[int]]:
    if isinstance(root_pid, bool) or not isinstance(root_pid, int) or root_pid <= 0:
        raise NativeProbeError("invalid_root_pid")
    fs = source or LinuxFileSource()
    identities: dict[int, tuple[int, int]] = {}
    children: dict[int, list[int]] = {}
    found_root = False
    for pid in fs.pids(deadline_ns, clock):
        _check_deadline(deadline_ns, clock, "deadline_during_process_tree")
        try:
            parent, start = _parse_stat(
                pid, fs.read(f"/proc/{pid}/stat", MAX_PROC_RECORD_BYTES, deadline_ns, clock)
            )
        except OSError:
            continue
        found_root |= pid == root_pid
        identities[pid] = (parent, start)
        children.setdefault(parent, []).append(pid)
    if not found_root:
        raise NativeProbeError("root_process_missing")
    owned = {root_pid}
    pending = deque([root_pid])
    while pending:
        _check_deadline(deadline_ns, clock, "deadline_during_process_tree")
        parent = pending.popleft()
        for child in children.get(parent, ()):
            if child not in owned:
                owned.add(child)
                pending.append(child)
    _check_deadline(deadline_ns, clock, "deadline_after_process_tree")
    return identities, owned


def _verify_snapshot_chain(
    pid: int, root_pid: int, identities: Mapping[int, tuple[int, int]],
    source: FileSource, deadline_ns: int, clock: Callable[[], int],
) -> None:
    seen: set[int] = set()
    current = pid
    while True:
        _check_deadline(deadline_ns, clock, "deadline_during_identity_recheck")
        if current in seen or current not in identities:
            raise NativeProbeError("process_ancestry_changed")
        seen.add(current)
        observed = proc_identity(current, deadline_ns, source=source, clock=clock)
        if observed != identities[current]:
            raise NativeProbeError("process_identity_changed")
        if current == root_pid:
            return
        current = identities[current][0]


def owns_loopback_listener(
    root_pid: int, port: int, deadline_ns: int, *,
    source: FileSource | None = None,
    clock: Callable[[], int] = time.monotonic_ns,
) -> bool:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise NativeProbeError("invalid_port")
    fs = source or LinuxFileSource()
    expected_port = f"{port:04X}"
    listeners: list[tuple[str, str]] = []
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        raw = fs.read(table, MAX_PROC_TABLE_BYTES, deadline_ns, clock)
        try:
            lines = raw.decode("ascii").splitlines()[1:]
        except UnicodeError as exc:
            raise NativeProbeError("invalid_socket_table") from exc
        for line in lines:
            _check_deadline(deadline_ns, clock, "deadline_during_socket_table")
            fields = line.split()
            if len(fields) >= 10 and fields[1].endswith(":" + expected_port) and fields[3] == "0A":
                listeners.append((fields[1].split(":", 1)[0], fields[9]))
                if len(listeners) > 1:
                    return False
    if len(listeners) != 1 or listeners[0][0] != "0100007F":
        return False
    target = f"socket:[{listeners[0][1]}]"
    total_fds = 0
    identities, owned = _process_snapshot(
        root_pid, deadline_ns, source=fs, clock=clock
    )
    for pid in sorted(owned):
        try:
            for path in fs.fds(pid, deadline_ns, clock):
                total_fds += 1
                if total_fds > MAX_TOTAL_FDS:
                    raise NativeProbeError("fd_total_limit")
                try:
                    if fs.readlink(path, deadline_ns, clock) == target:
                        _verify_snapshot_chain(
                            pid, root_pid, identities, fs, deadline_ns, clock
                        )
                        _check_deadline(deadline_ns, clock, "deadline_after_listener_scan")
                        return True
                except OSError:
                    continue
        except OSError:
            continue
    _check_deadline(deadline_ns, clock, "deadline_after_listener_scan")
    return False


if __name__ == "__main__":
    if sys.argv[1:] != ["--ctypes-worker"]:
        raise SystemExit(64)
    raise SystemExit(_ctypes_worker())
