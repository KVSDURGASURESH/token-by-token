"""Concrete, fail-closed SSH and Episode 1 cell adapters.

Nothing in this module creates provider resources.  Commands are expressed as
argument vectors and all remote shell text is generated with POSIX quoting.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .episode1 import (
    CHAT_TEMPLATE_SHA256,
    MODEL_REVISION,
    PROMPT_EVIDENCE_SHA256,
    TOKENIZER_ASSET_MANIFEST_SHA256,
    canonical_json,
    sha256_json,
)
from .episode1_runner import run_fixture_cell


class RemoteExecutionError(RuntimeError):
    """A bounded SSH operation failed without exposing command output."""


_SSH_CLEANUP_RESERVE_SECONDS = 2.0
_SSH_TERM_GRACE_SECONDS = 0.2
_SSH_POLL_SECONDS = 0.01


def quote_remote_argv(argv: Sequence[str]) -> str:
    if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise ValueError("remote argv must be a non-empty sequence of NUL-free strings")
    return " ".join(shlex.quote(item) for item in argv)


def _private_regular_file(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a non-symlink regular file")
    if stat.st_mode & 0o077:
        raise ValueError(f"{label} must not be accessible by group or other")
    return resolved


@dataclass(frozen=True)
class SshConfig:
    host: str
    public_port: int
    user: str
    identity_file: Path
    known_hosts_file: Path
    connect_timeout_seconds: int = 10

    def validated(self) -> "SshConfig":
        if not self.host or self.host.startswith("-") or any(char.isspace() for char in self.host):
            raise ValueError("SSH host is invalid")
        if not self.user or not self.user.replace("-", "").replace("_", "").isalnum():
            raise ValueError("SSH user is invalid")
        if not 1 <= self.public_port <= 65535:
            raise ValueError("SSH public port is invalid")
        if not 1 <= self.connect_timeout_seconds <= 60:
            raise ValueError("SSH connect timeout is invalid")
        _private_regular_file(self.identity_file, "SSH identity file")
        _private_regular_file(self.known_hosts_file, "SSH known-hosts file")
        return self

    def base_argv(self) -> list[str]:
        self.validated()
        return [
            "ssh", "-F", "/dev/null", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_file.resolve()}",
            "-o", "IdentitiesOnly=yes", "-o", "LogLevel=ERROR",
            "-o", f"ConnectTimeout={self.connect_timeout_seconds}",
            "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
            "-i", str(self.identity_file.resolve()), "-p", str(self.public_port),
            f"{self.user}@{self.host}",
        ]


class SshRemoteExecutor:
    def __init__(
        self,
        config: SshConfig,
        *,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config.validated()
        self.runner = runner
        self.monotonic = monotonic

    @classmethod
    def _terminate(
        cls, process: subprocess.Popen[bytes], *, cleanup_deadline_monotonic: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        now = monotonic()
        cleanup_deadline = (
            now + _SSH_CLEANUP_RESERVE_SECONDS
            if cleanup_deadline_monotonic is None else cleanup_deadline_monotonic
        )
        if (
            isinstance(cleanup_deadline, bool)
            or not isinstance(cleanup_deadline, (int, float))
            or not math.isfinite(cleanup_deadline)
        ):
            raise RemoteExecutionError("SSH cleanup deadline is invalid")
        del cls
        if now < cleanup_deadline:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            # Signal the whole group before reaping its leader. Descendants may
            # otherwise retain stdout/stderr after a successful leader exit.
            grace_deadline = min(
                cleanup_deadline,
                monotonic()
                + min(
                    _SSH_TERM_GRACE_SECONDS,
                    max(0.0, cleanup_deadline - monotonic()) / 2,
                ),
            )
            while monotonic() < grace_deadline and process.poll() is None:
                pause = min(_SSH_POLL_SECONDS, grace_deadline - monotonic())
                if pause > 0:
                    time.sleep(pause)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        remaining = cleanup_deadline - monotonic()
        if process.poll() is None and remaining <= 0:
            raise RemoteExecutionError("SSH cleanup deadline exhausted before reap")
        try:
            process.wait(timeout=max(0.0, remaining))
        except subprocess.TimeoutExpired as exc:
            raise RemoteExecutionError("SSH process could not be reaped within its deadline") from exc
        # Reaping the leader is insufficient: a child can close all inherited
        # pipes yet remain alive in the session's process group. Do not return
        # until killpg(0) proves that the owned group no longer exists.
        while True:
            try:
                os.killpg(process.pid, 0)
                group_present = True
            except ProcessLookupError:
                group_present = False
            except PermissionError:
                group_present = True
            if not group_present:
                break
            remaining = cleanup_deadline - monotonic()
            if remaining <= 0:
                raise RemoteExecutionError("SSH process group remained at cleanup deadline")
            time.sleep(min(_SSH_POLL_SECONDS, remaining))

    def _run_bounded(
        self, command: Sequence[str], payload: bytes | None, *, deadline_monotonic: float,
        cancel_event: threading.Event | None,
    ) -> subprocess.CompletedProcess[bytes]:
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(float(deadline_monotonic))
        ):
            raise RemoteExecutionError("SSH command deadline is invalid")
        final_deadline = float(deadline_monotonic)
        operation_deadline = final_deadline - _SSH_CLEANUP_RESERVE_SECONDS
        if self.monotonic() >= operation_deadline:
            raise RemoteExecutionError("SSH command has no bounded cleanup reserve")
        output = {"stdout": bytearray(), "stderr": bytearray()}
        overflow = threading.Event()
        threads: list[threading.Thread] = []
        started_threads: list[threading.Thread] = []
        failed = False
        operation_error: Exception | None = None
        cleanup_error: BaseException | None = None
        process = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )

        def drain(name: str, stream: Any) -> None:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    return
                remaining = 1024 * 1024 - len(output[name])
                if remaining > 0:
                    output[name].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()

        def feed() -> None:
            assert process.stdin is not None
            try:
                if payload:
                    process.stdin.write(payload)
                    process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()

        try:
            # Every fallible setup action after Popen belongs to this protected
            # scope so even local thread-construction failure reaps the child.
            threads = [
                threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
                threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
                threading.Thread(target=feed, daemon=True),
            ]
            for thread in threads:
                thread.start()
                started_threads.append(thread)
            while True:
                leader_exited = process.poll() is not None
                drains_complete = not any(thread.is_alive() for thread in threads[:2])
                if leader_exited and drains_complete:
                    break
                if overflow.is_set() or (cancel_event is not None and cancel_event.is_set()):
                    failed = True
                    break
                if self.monotonic() >= operation_deadline:
                    failed = True
                    break
                pause = min(_SSH_POLL_SECONDS, operation_deadline - self.monotonic())
                if pause > 0:
                    time.sleep(pause)
        except Exception as exc:
            failed = True
            operation_error = exc
        finally:
            # Always terminate the owned process group. A successful leader can
            # exit after leaving a same-group descendant with closed stdio, so
            # completed drain threads alone do not prove descendant absence.
            try:
                self._terminate(
                    process,
                    cleanup_deadline_monotonic=final_deadline,
                    monotonic=self.monotonic,
                )
            except BaseException as exc:
                cleanup_error = exc
            for thread in started_threads:
                thread.join(timeout=max(0.0, final_deadline - self.monotonic()))
            if cleanup_error is None and any(thread.is_alive() for thread in started_threads):
                cleanup_error = RemoteExecutionError(
                    "SSH pipe work did not finish within its deadline"
                )
            if not any(thread.is_alive() for thread in started_threads):
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
        if cleanup_error is not None:
            raise RemoteExecutionError("bounded SSH cleanup failed") from cleanup_error
        if operation_error is not None:
            raise RemoteExecutionError("bounded SSH local I/O setup failed") from operation_error
        if failed or overflow.is_set():
            raise RemoteExecutionError("bounded SSH command was cancelled or exceeded a limit")
        return subprocess.CompletedProcess(command, process.returncode, bytes(output["stdout"]), bytes(output["stderr"]))

    def run_json(
        self, remote_argv: Sequence[str], *, input_value: Mapping[str, Any] | None = None,
        timeout_seconds: float = 30,
        deadline_monotonic: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Mapping[str, Any]:
        # OpenSSH treats arguments after destination as the remote command.
        # A `--` here would become the remote executable name, not a separator.
        command = [*self.config.base_argv(), quote_remote_argv(remote_argv)]
        payload = None if input_value is None else json.dumps(input_value, separators=(",", ":")).encode()
        if payload is not None and len(payload) > 1024 * 1024:
            raise RemoteExecutionError("remote command input exceeds the closed size limit")
        deadline = min(
            self.monotonic() + timeout_seconds,
            deadline_monotonic if deadline_monotonic is not None else float("inf"),
        )
        if deadline <= self.monotonic():
            raise RemoteExecutionError("remote command deadline already elapsed")
        try:
            if self.runner is None:
                result = self._run_bounded(
                    command, payload, deadline_monotonic=deadline, cancel_event=cancel_event
                )
            else:
                result = self.runner(
                    command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=max(.001, deadline - self.monotonic()), check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RemoteExecutionError("bounded SSH command failed") from exc
        if (
            self.monotonic() >= deadline
            or (cancel_event is not None and cancel_event.is_set())
        ):
            raise RemoteExecutionError("bounded SSH command was cancelled or exceeded its deadline")
        if (
            result.returncode != 0
            or len(result.stdout) > 1024 * 1024
            or len(result.stderr) > 1024 * 1024
        ):
            raise RemoteExecutionError("remote command returned a non-success result")
        try:
            value = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteExecutionError("remote command did not return closed JSON") from exc
        if (
            self.monotonic() >= deadline
            or (cancel_event is not None and cancel_event.is_set())
        ):
            raise RemoteExecutionError("bounded SSH command was cancelled or exceeded its deadline")
        if not isinstance(value, dict):
            raise RemoteExecutionError("remote command result must be a JSON object")
        return value

    def tunnel_argv(self, *, local_port: int, remote_port: int = 8000) -> list[str]:
        if not 1 <= local_port <= 65535 or not 1 <= remote_port <= 65535:
            raise ValueError("tunnel ports are invalid")
        base = self.config.base_argv()
        destination = base.pop()
        return [
            *base, "-o", "ExitOnForwardFailure=yes", "-N",
            "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", destination,
        ]


class SshTunnel:
    """Owned SSH master with an explicitly acknowledged loopback forward."""

    def __init__(
        self, executor: SshRemoteExecutor, *, local_port: int, remote_port: int = 8000,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if (
            any(
                isinstance(port, bool)
                or not isinstance(port, int)
                or not 1 <= port <= 65535
                for port in (local_port, remote_port)
            )
            or remote_port != 8000
        ):
            raise ValueError("tunnel must bind an integer local port to runtime port 8000")
        self.executor = executor
        self.local_port = local_port
        self.remote_port = remote_port
        if monotonic is not None and monotonic is not executor.monotonic:
            raise ValueError("tunnel and executor must share the same monotonic clock")
        self.monotonic = executor.monotonic
        self.process: subprocess.Popen[bytes] | None = None
        self.cancel_event = threading.Event()
        self._watcher: threading.Thread | None = None
        self._watcher_started = False
        self._control_directory: str | None = None
        self._control_path: str | None = None
        self._used = False
        self._ready = False

    @property
    def ready(self) -> bool:
        return bool(
            self._ready
            and self.process is not None
            and self.process.poll() is None
            and not self.cancel_event.is_set()
        )

    def _command(self, *options: str) -> list[str]:
        base = self.executor.config.base_argv()
        destination = base.pop()
        return [*base, "-S", str(self._control_path), *options, destination]

    def _control(
        self, action: str, deadline: float
    ) -> subprocess.CompletedProcess[bytes]:
        options = ["-O", action]
        if action == "forward":
            options += [
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                f"127.0.0.1:{self.local_port}:127.0.0.1:{self.remote_port}",
            ]
        result = self.executor._run_bounded(
            self._command(*options),
            None,
            deadline_monotonic=deadline,
            cancel_event=self.cancel_event,
        )
        if result.returncode != 0:
            raise RemoteExecutionError("owned SSH master rejected tunnel control")
        return result

    def start(self, *, deadline_monotonic: float) -> None:
        if self._used:
            raise RemoteExecutionError("SSH tunnel objects are single use")
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(deadline_monotonic)
        ):
            raise RemoteExecutionError("SSH tunnel deadline is invalid")
        work_deadline = deadline_monotonic - _SSH_CLEANUP_RESERVE_SECONDS
        if self.monotonic() >= work_deadline - _SSH_CLEANUP_RESERVE_SECONDS:
            raise RemoteExecutionError("SSH tunnel has no startup and cleanup reserve")
        self._used = True
        self._control_directory = tempfile.mkdtemp(prefix="e1-ssh-", dir="/tmp")
        self._control_path = str(Path(self._control_directory) / "control")
        try:
            os.chmod(self._control_directory, 0o700)
            self.process = subprocess.Popen(
                self._command(
                    "-M",
                    "-N",
                    "-o",
                    "ControlPersist=no",
                    "-o",
                    "ExitOnForwardFailure=yes",
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            process = self.process

            def watch() -> None:
                process.wait()
                self.cancel_event.set()

            self._watcher = threading.Thread(
                target=watch, name="episode1-ssh-tunnel", daemon=True
            )
            self._watcher.start()
            self._watcher_started = True
            while True:
                if process.poll() is not None:
                    raise RemoteExecutionError("SSH tunnel master exited before readiness")
                if self.monotonic() >= work_deadline:
                    raise RemoteExecutionError("SSH tunnel startup deadline exceeded")
                try:
                    mode = os.lstat(self._control_path).st_mode
                except FileNotFoundError:
                    time.sleep(min(0.01, max(0.0, work_deadline - self.monotonic())))
                    continue
                if not stat.S_ISSOCK(mode):
                    raise RemoteExecutionError("SSH master control path is not a socket")
                break
            check = self._control("check", work_deadline)
            match = re.fullmatch(rb"Master running \(pid=([0-9]+)\)\s*", check.stderr)
            if check.stdout or match is None or int(match.group(1)) != process.pid:
                raise RemoteExecutionError(
                    "SSH control socket does not identify the owned master"
                )
            self._control("forward", work_deadline)
            if process.poll() is not None or self.cancel_event.is_set():
                raise RemoteExecutionError(
                    "SSH master exited during forwarding acknowledgement"
                )
            if self.monotonic() >= work_deadline:
                raise RemoteExecutionError(
                    "SSH forwarding acknowledgement missed its deadline"
                )
            self._ready = True
        except BaseException as error:
            try:
                self.close(deadline_monotonic=deadline_monotonic)
            except BaseException as cleanup_error:
                raise BaseExceptionGroup(
                    "SSH tunnel startup and cleanup failed", [error, cleanup_error]
                )
            raise

    def close(self, *, deadline_monotonic: float) -> None:
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(deadline_monotonic)
        ):
            raise RemoteExecutionError("SSH tunnel cleanup deadline is invalid")
        self._ready = False
        self.cancel_event.set()
        if self.process is not None:
            SshRemoteExecutor._terminate(
                self.process,
                cleanup_deadline_monotonic=deadline_monotonic,
                monotonic=self.monotonic,
            )
        if self._watcher_started:
            assert self._watcher is not None
            self._watcher.join(
                timeout=max(0.0, deadline_monotonic - self.monotonic())
            )
            if self._watcher.is_alive():
                raise RemoteExecutionError(
                    "SSH tunnel watcher survived its cleanup deadline"
                )
        self.process = None
        self._watcher = None
        self._watcher_started = False
        if self._control_directory is not None:
            if self._control_path is not None:
                try:
                    os.unlink(self._control_path)
                except FileNotFoundError:
                    pass
            os.rmdir(self._control_directory)
            self._control_directory = None
            self._control_path = None


class Episode1CellDriver:
    """Bridge the frozen prompt evidence to the generic concurrent cell runner."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        model: str,
        prompt_evidence: Mapping[str, Any],
        input_token_counter: Callable[[Sequence[Mapping[str, str]]], int],
        output_token_counter: Callable[[str], int],
        input_token_ids: Callable[[Sequence[Mapping[str, str]]], Sequence[int]] | None = None,
        tunnel: SshTunnel | None = None,
    ) -> None:
        try:
            parsed = urlsplit(endpoint_url)
            endpoint_port = parsed.port
        except ValueError as exc:
            raise ValueError(
                "cell endpoint must be the exact unauthenticated IPv4 loopback chat path"
            ) from exc
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username is not None or parsed.password is not None
            or parsed.path != "/v1/chat/completions" or parsed.query or parsed.fragment
            or endpoint_port is None
        ):
            raise ValueError("cell endpoint must be the exact unauthenticated IPv4 loopback chat path")
        if tunnel is not None and endpoint_port != tunnel.local_port:
            raise ValueError("cell endpoint is not bound to the owned SSH tunnel port")
        try:
            frozen_evidence = json.loads(canonical_json(prompt_evidence))
        except (TypeError, ValueError) as exc:
            raise ValueError("prompt evidence must be canonical JSON") from exc
        if sha256_json(frozen_evidence) != PROMPT_EVIDENCE_SHA256:
            raise ValueError("prompt evidence differs from the reviewed artifact")
        if (
            frozen_evidence.get("model_revision") != MODEL_REVISION
            or frozen_evidence.get("chat_template_sha256") != CHAT_TEMPLATE_SHA256
            or sha256_json(frozen_evidence.get("asset_sha256"))
            != TOKENIZER_ASSET_MANIFEST_SHA256
            or [item.get("target_input_tokens") for item in frozen_evidence.get("fixed", [])]
            != [512, 2048]
            or len(frozen_evidence.get("natural_quality", [])) != 24
        ):
            raise ValueError("prompt evidence material binding is invalid")
        self.endpoint_url = endpoint_url
        self.model = model
        self.prompt_evidence = frozen_evidence
        self.input_token_counter = input_token_counter
        self.input_token_ids = input_token_ids
        self.output_token_counter = output_token_counter
        self.tunnel = tunnel

    def _verify_prompt_tokens(self, item: Mapping[str, Any]) -> None:
        if self.input_token_ids is None:
            raise ValueError("provider prompt binding requires rendered token IDs")
        values = list(self.input_token_ids(item["messages"]))
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("rendered prompt token IDs are invalid")
        claimed = item.get("token_ids")
        claimed_sha = item.get("token_ids_sha256")
        if values != claimed or hashlib.sha256(canonical_json(values).encode()).hexdigest() != claimed_sha:
            raise ValueError("rendered prompt token IDs differ from frozen evidence")

    def start(self, *, deadline_monotonic: float) -> None:
        if self.tunnel is not None:
            self.tunnel.start(deadline_monotonic=deadline_monotonic)

    def close(self, *, deadline_monotonic: float) -> None:
        if self.tunnel is not None and self.tunnel.process is not None:
            self.tunnel.close(deadline_monotonic=deadline_monotonic)

    def _specs(self, block: Mapping[str, Any], cell: Mapping[str, Any], warmup: bool) -> list[dict[str, Any]]:
        count = int(cell["warmups"] if warmup else cell["requests"])
        prefix = "warmup" if warmup else "measured"
        if cell["mode"] == "fixed_output":
            prompt = next(
                item for item in self.prompt_evidence["fixed"]
                if item["target_input_tokens"] == cell["input_tokens"]
            )
            self._verify_prompt_tokens(prompt)
            return [{
                "request_id": f"{block['block_id']}-{prefix}-{cell['id']}-{index + 1:02d}",
                "messages": prompt["messages"], "quality_task_id": None, "gold_json": None,
            } for index in range(count)]
        tasks = list(self.prompt_evidence["natural_quality"])
        if warmup:
            tasks = tasks[:count]
        if len(tasks) != count:
            raise ValueError("natural-quality evidence does not match the frozen request count")
        for task in tasks:
            self._verify_prompt_tokens(task)
        return [{
            "request_id": f"{block['block_id']}-{prefix}-{cell['id']}-{index + 1:02d}",
            "messages": task["messages"], "quality_task_id": task["task_id"],
            "gold_json": task["gold_json"],
        } for index, task in enumerate(tasks)]

    def run_cell(
        self, *, allocation: object, block: Mapping[str, Any], cell: Mapping[str, Any],
        warmup: bool, evidence_class: str, cancel_event: threading.Event,
        record: Callable[[Mapping[str, Any]], None],
        request_lifecycle: Callable[[Mapping[str, Any]], None] | None = None,
        deadline_monotonic: float,
    ) -> Mapping[str, Any]:
        del allocation
        if self.tunnel is not None and not self.tunnel.ready:
            raise RemoteExecutionError("owned SSH tunnel is not ready for cell work")
        if evidence_class != "local_fixture" and self.tunnel is None:
            raise RemoteExecutionError("provider cell work requires an owned SSH tunnel")

        class CombinedCancellation:
            def is_set(inner_self) -> bool:
                return cancel_event.is_set() or bool(
                    self.tunnel is not None and self.tunnel.cancel_event.is_set()
                )

            def reason_code(inner_self) -> str | None:
                if self.tunnel is not None and self.tunnel.cancel_event.is_set():
                    return "tunnel_lost"
                return "cancelled_on_drain" if cancel_event.is_set() else None

        effective = dict(cell)
        if warmup:
            effective["requests"] = cell["warmups"]
        records, summary = run_fixture_cell(
            endpoint_url=self.endpoint_url, model=self.model, block=block, cell=effective,
            requests=self._specs(block, cell, warmup),
            input_token_counter=self.input_token_counter,
            output_token_counter=self.output_token_counter,
            evidence_class=evidence_class, warmup=warmup,
            external_cancel_event=CombinedCancellation(), record_callback=record,
            lifecycle_callback=request_lifecycle,
            absolute_deadline_ns=int(deadline_monotonic * 1_000_000_000),
        )
        if self.tunnel is not None and not self.tunnel.ready:
            raise RemoteExecutionError("owned SSH tunnel died during cell work")
        return {
            "scheduled": len(records),
            "failed": sum(item["status"] != "success" for item in records),
            "summary": summary,
        }
