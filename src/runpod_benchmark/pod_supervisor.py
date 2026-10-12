"""Single-process-group supervisor used inside the Episode 1 image.

The owning Python process remains the child's parent, so termination can be
bounded, escalated to SIGKILL, and reaped rather than delegated to shell jobs.
"""

from __future__ import annotations

import json
import hashlib
import math
import ctypes
import os
import signal
import socket
import subprocess
import time
import threading
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


class SupervisorError(RuntimeError):
    pass


class PodProcessSupervisor:
    def __init__(
        self, state_directory: Path, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self.state_directory = state_directory
        state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(state_directory, 0o700)
        self.monotonic = monotonic
        self.process: subprocess.Popen[bytes] | None = None
        self.identity: dict[str, Any] | None = None
        self._drainers: list[threading.Thread] = []
        self._baseline_children: dict[int, int] = {}
        self._owned_identities: dict[int, int] = {}
        self._stopped_verified = True
        if sys.platform.startswith("linux"):
            try:
                if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
                    raise OSError(ctypes.get_errno(), "prctl(PR_SET_CHILD_SUBREAPER) failed")
            except OSError as exc:
                raise SupervisorError("runtime supervisor cannot become a child subreaper") from exc

    @property
    def cleanup_required(self) -> bool:
        return not self._stopped_verified

    def _drain_output(self, stream: Any, name: str, maximum_bytes: int = 1024 * 1024) -> None:
        path = self.state_directory / name
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        retained = 0
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                if retained < maximum_bytes:
                    selected = chunk[:maximum_bytes - retained]
                    os.write(descriptor, selected)
                    retained += len(selected)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _group_exists(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _wait_group_absent(self, process_group: int, timeout_seconds: float) -> bool:
        return self._wait_group_absent_until(process_group, self.monotonic() + timeout_seconds)

    def _wait_group_absent_until(self, process_group: int, deadline: float) -> bool:
        while self._group_exists(process_group) and self.monotonic() < deadline:
            self._capture_owned()
            self._reap_owned()
            time.sleep(min(.02, max(0, deadline - self.monotonic())))
        self._reap_owned()
        return not self._group_exists(process_group)

    @staticmethod
    def _process_start_ticks(pid: int) -> int:
        try:
            text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            return int(text[text.rfind(")") + 2:].split()[19])
        except (OSError, UnicodeError, ValueError, IndexError) as exc:
            if sys.platform.startswith("linux"):
                raise SupervisorError("runtime process start identity is unavailable") from exc
            # This fallback is used only by non-Linux local contract tests. The
            # pod daemon requires procfs before accepting any live operation.
            return time.monotonic_ns()

    @classmethod
    def _proc_parent_and_start(cls, pid: int) -> tuple[int, int]:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        fields = text[text.rfind(")") + 2:].split()
        return int(fields[1]), int(fields[19])

    @classmethod
    def _process_table(cls) -> dict[int, tuple[int, int]]:
        if not sys.platform.startswith("linux"):
            return {}
        result: dict[int, tuple[int, int]] = {}
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    result[int(entry.name)] = cls._proc_parent_and_start(int(entry.name))
                except (OSError, UnicodeError, ValueError, IndexError):
                    continue
        return result

    def _capture_owned(self) -> None:
        if self.process is None or not sys.platform.startswith("linux"):
            return
        table = self._process_table()
        root = self.process.pid
        discovered = {root}
        changed = True
        while changed:
            changed = False
            for pid, (parent, _start) in table.items():
                if parent in discovered and pid not in discovered:
                    discovered.add(pid)
                    changed = True
        # A descendant that daemonizes out of the original session is
        # reparented here because this process is a child subreaper. Exclude
        # children that predated the runtime launch.
        for pid, (parent, start) in table.items():
            if parent == os.getpid() and self._baseline_children.get(pid) != start:
                discovered.add(pid)
        for pid in discovered:
            if pid in table:
                self._owned_identities[pid] = table[pid][1]

    def _owned_present(self) -> list[int]:
        self._capture_owned()
        table = self._process_table()
        return [
            pid for pid, start in self._owned_identities.items()
            if pid in table and table[pid][1] == start
        ]

    def _signal_owned(self, signum: int) -> None:
        for pid in self._owned_present():
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass

    def _reap_owned(self) -> None:
        for pid in list(self._owned_identities):
            # Popen owns the leader's wait status. Reaping it here would make
            # Popen.wait() lose the authoritative return code.
            if self.process is not None and pid == self.process.pid:
                continue
            try:
                reaped, _status = os.waitpid(pid, os.WNOHANG)
                if reaped == pid:
                    self._owned_identities.pop(pid, None)
            except (ChildProcessError, ProcessLookupError):
                self._owned_identities.pop(pid, None)

    def _write_state(self, value: Mapping[str, Any]) -> None:
        target = self.state_directory / "runtime.json"
        if target.is_symlink():
            raise SupervisorError("supervisor state path cannot be a symlink")
        temporary = self.state_directory / f".runtime.{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
        directory_descriptor = os.open(self.state_directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def start(
        self, argv: Sequence[str], *, runtime: str, block_id: str, specification_sha256: str,
        environment: Mapping[str, str] | None = None, deadline_monotonic: float,
    ) -> Mapping[str, Any]:
        if not self._stopped_verified:
            raise SupervisorError("the prior runtime has not completed verified cleanup")
        if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
            raise SupervisorError("runtime argv is invalid")
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(float(deadline_monotonic))
            or self.monotonic() >= float(deadline_monotonic)
        ):
            raise SupervisorError("runtime start deadline is invalid or exhausted")
        env = None
        if environment is not None:
            env = {str(key): str(value) for key, value in environment.items()}
        table = self._process_table()
        self._baseline_children = {
            pid: start for pid, (parent, start) in table.items() if parent == os.getpid()
        }
        self._owned_identities = {}
        self.process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True, env=env,
        )
        failed_process = self.process
        self._stopped_verified = False
        try:
            assert self.process.stdout is not None and self.process.stderr is not None
            self._capture_owned()
            self._drainers = [
                threading.Thread(
                    target=self._drain_output,
                    args=(self.process.stdout, f"runtime.{self.process.pid}.stdout.log"),
                    name="episode1-runtime-stdout", daemon=True,
                ),
                threading.Thread(
                    target=self._drain_output,
                    args=(self.process.stderr, f"runtime.{self.process.pid}.stderr.log"),
                    name="episode1-runtime-stderr", daemon=True,
                ),
            ]
            for drainer in self._drainers:
                drainer.start()
            self.identity = {
                "pid": self.process.pid, "process_group": self.process.pid,
                "runtime": runtime, "block_id": block_id,
                "specification_sha256": specification_sha256,
                "argv_sha256": hashlib.sha256(
                    json.dumps(list(argv), separators=(",", ":")).encode()
                ).hexdigest(),
                "process_start_ticks": self._process_start_ticks(self.process.pid),
                "started_monotonic_ns": time.monotonic_ns(),
            }
            if self.monotonic() >= deadline_monotonic:
                raise SupervisorError("runtime start deadline reached after process creation")
            self._write_state({**self.identity, "status": "running"})
        except BaseException as setup_error:
            # A process without its durable identity cannot be managed safely.
            # Use one absolute budget to kill and reap the complete owned tree
            # before propagating the persistence error.
            cleanup_deadline = min(float(deadline_monotonic), self.monotonic() + 10)
            cleanup_error: BaseException | None = None
            try:
                self._capture_owned()
                if self._group_exists(failed_process.pid):
                    os.killpg(failed_process.pid, signal.SIGKILL)
                self._signal_owned(signal.SIGKILL)
                try:
                    failed_process.wait(
                        timeout=max(0.001, cleanup_deadline - self.monotonic())
                    )
                except subprocess.TimeoutExpired as exc:
                    raise SupervisorError(
                        "runtime leader survived failed-state cleanup"
                    ) from exc
                if not self._wait_group_absent_until(
                    failed_process.pid, cleanup_deadline
                ):
                    raise SupervisorError(
                        "runtime group survived failed-state cleanup"
                    )
                while self._owned_present() and self.monotonic() < cleanup_deadline:
                    self._signal_owned(signal.SIGKILL)
                    self._reap_owned()
                    time.sleep(min(.02, max(0, cleanup_deadline - self.monotonic())))
                self._reap_owned()
                if self._owned_present():
                    raise SupervisorError(
                        "runtime descendants survived failed-state cleanup"
                    )
            except BaseException as exc:
                cleanup_error = exc
            finally:
                for drainer in self._drainers:
                    if drainer.ident is None:
                        continue
                    drainer.join(
                        timeout=max(0, min(2, cleanup_deadline - self.monotonic()))
                    )
                    if drainer.is_alive() and cleanup_error is None:
                        cleanup_error = SupervisorError(
                            "runtime output drain survived failed-state cleanup"
                        )
                if cleanup_error is None:
                    self._drainers = []
                    if failed_process.stdout is not None:
                        failed_process.stdout.close()
                    if failed_process.stderr is not None:
                        failed_process.stderr.close()
                    self.process = None
                    self.identity = None
                    self._stopped_verified = True
            if cleanup_error is not None:
                raise SupervisorError(
                    "runtime cleanup failed after start setup failure"
                ) from cleanup_error
            raise setup_error
        return dict(self.identity)

    def wait_tcp_ready(self, host: str, port: int, timeout_seconds: float) -> None:
        if host not in {"127.0.0.1", "::1"} or not 1 <= port <= 65535:
            raise SupervisorError("readiness probe must target loopback")
        deadline = self.monotonic() + timeout_seconds
        while self.monotonic() < deadline:
            if self.process is None or self.process.poll() is not None:
                raise SupervisorError("runtime exited before readiness")
            try:
                with socket.create_connection((host, port), timeout=min(.25, timeout_seconds)):
                    return
            except OSError:
                time.sleep(.02)
        raise SupervisorError("runtime readiness deadline exceeded")

    def stop(
        self, *, deadline_monotonic: float | None = None,
        term_seconds: float = 10, kill_seconds: float = 5,
    ) -> Mapping[str, Any]:
        process = self.process
        if process is None:
            raise SupervisorError("no runtime process was started")
        process_group = process.pid
        escalated = False
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or value < 0
            for value in (term_seconds, kill_seconds)
        ) or term_seconds + kill_seconds <= 0:
            raise SupervisorError("runtime stop intervals are invalid")
        now = self.monotonic()
        overall_deadline = (
            now + term_seconds + kill_seconds
            if deadline_monotonic is None else deadline_monotonic
        )
        if (
            isinstance(overall_deadline, bool)
            or not isinstance(overall_deadline, (int, float))
            or not math.isfinite(overall_deadline)
            or overall_deadline <= now
        ):
            raise SupervisorError("runtime stop deadline is invalid")
        # A caller-supplied deadline is a ceiling for the complete operation,
        # including forced kill, reap, descendant cleanup, and output drains.
        # Preserve the configured TERM/KILL ratio when that budget is short so
        # graceful waiting cannot consume the entire cleanup interval.
        remaining = overall_deadline - now
        term_fraction = term_seconds / (term_seconds + kill_seconds)
        term_deadline = now + min(term_seconds, remaining * term_fraction)
        if self._group_exists(process_group):
            os.killpg(process_group, signal.SIGTERM)
        self._signal_owned(signal.SIGTERM)
        if process.poll() is None:
            try:
                process.wait(timeout=max(0, term_deadline - self.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        else:
            process.wait()
        if not self._wait_group_absent_until(process_group, term_deadline):
            escalated = True
            if self._group_exists(process_group):
                os.killpg(process_group, signal.SIGKILL)
            self._signal_owned(signal.SIGKILL)
            kill_deadline = overall_deadline
            try:
                if process.poll() is None:
                    process.wait(timeout=max(0, kill_deadline - self.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise SupervisorError("runtime process leader could not be reaped") from exc
            if not self._wait_group_absent_until(process_group, kill_deadline):
                raise SupervisorError("runtime process group remains present after SIGKILL")
        while self._owned_present() and self.monotonic() < overall_deadline:
            self._signal_owned(signal.SIGKILL)
            self._reap_owned()
            time.sleep(min(.02, max(0, overall_deadline - self.monotonic())))
        self._reap_owned()
        if self._owned_present():
            raise SupervisorError("runtime descendants remain present after SIGKILL")
        for drainer in self._drainers:
            drainer.join(timeout=max(0, min(2, overall_deadline - self.monotonic())))
            if drainer.is_alive():
                raise SupervisorError("runtime output drain did not finish")
        self._drainers = []
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        value = {
            **(self.identity or {}), "status": "stopped", "returncode": process.returncode,
            "sigkill_used": escalated, "reaped": True,
        }
        self._write_state(value)
        self._stopped_verified = True
        return value

    def descendants_absent(self) -> bool:
        if self.process is None:
            return self._stopped_verified and not self._owned_present()
        if self.process.poll() is None:
            return False
        self._reap_owned()
        return not self._group_exists(self.process.pid) and not self._owned_present()


def loopback_port_absent(port: int) -> bool:
    if not 1 <= port <= 65535:
        raise ValueError("port is invalid")
    for family, address in (
        (socket.AF_INET, ("127.0.0.1", port)),
        (socket.AF_INET6, ("::1", port)),
    ):
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue
        with probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            try:
                probe.bind(address)
            except OSError:
                return False
    return True
