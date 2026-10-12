"""Persistent, fixed-command control plane for an Episode 1 pod.

The daemon is the runtime process-group parent.  The SSH-visible helper only
relays one bounded JSON request to its root-only Unix socket; it never accepts
an argv or shell fragment from the caller.
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import math
import os
import selectors
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .episode1 import canonical_json
from .gpu_process_ownership import (
    LinuxProcSource,
    OwnershipError,
    collect as collect_gpu_process_ownership,
    run_command as run_gpu_process_query,
)
from .native_probe_hardening import (
    MAX_FILE_BYTES,
    MAX_PROC_RECORD_BYTES,
    NativeProbeError,
    bounded_read,
    bounded_readlink,
    owns_loopback_listener,
    proc_identity,
    query_library_versions,
)
from .pod_supervisor import PodProcessSupervisor, SupervisorError, loopback_port_absent
from .system_sampler import Binding, NvidiaSmiAdapter, ProcAdapter, ProcessTarget, SystemSampler


MAX_MESSAGE_BYTES = 1024 * 1024
MAX_CONTROL_WORKERS = 4
SOCKET_PATH = Path("/run/episode1/control.sock")
STATE_DIRECTORY = Path("/run/episode1/state")
MODEL = "Qwen/Qwen2.5-32B-Instruct"
REVISION = "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd"
NATIVE_KERNEL_REASON = "humming_not_selected_by_frozen_runtime_path"
GPU_PROCESS_PID_DOMAIN = "proc_pid"


class RemoteControlError(RuntimeError):
    """The fixed remote control protocol rejected an operation."""


def runtime_argv(runtime: str) -> list[str]:
    if runtime == "vllm-0.29.0":
        return [
            "vllm", "serve", MODEL, f"--revision={REVISION}",
            f"--tokenizer-revision={REVISION}", "--dtype=bfloat16",
            "--kv-cache-dtype=bfloat16", "--gpu-memory-utilization=0.90",
            "--generation-config=vllm", "--max-model-len=4096",
            "--max-num-seqs=4", "--no-enable-prefix-caching",
            "--host=127.0.0.1", "--port=8000",
        ]
    if runtime == "sglang-0.5.20":
        return [
            "python", "-m", "sglang.launch_server", f"--model-path={MODEL}",
            f"--revision={REVISION}", "--dtype=bfloat16",
            "--kv-cache-dtype=bfloat16", "--mem-fraction-static=0.90",
            "--sampling-defaults=openai", "--context-length=4096",
            "--max-running-requests=4", "--disable-radix-cache", "--enable-metrics",
            "--host=127.0.0.1", "--port=8000",
        ]
    raise RemoteControlError("runtime is outside the frozen Episode 1 pair")


def argv_sha256(argv: Sequence[str]) -> str:
    return hashlib.sha256(canonical_json(list(argv)).encode()).hexdigest()


def _closed(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RemoteControlError(f"{label} has an open or incomplete schema")
    return value


def _load_one_json(stream: Any) -> Mapping[str, Any]:
    data = stream.read(MAX_MESSAGE_BYTES + 1)
    if len(data) > MAX_MESSAGE_BYTES:
        raise RemoteControlError("control request exceeds the byte limit")
    try:
        value = json.loads(
            data,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RemoteControlError("control request is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise RemoteControlError("control request must be an object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _request_deadline(value: Mapping[str, Any]) -> float:
    timeout = value.get("operation_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise RemoteControlError("operation timeout is invalid")
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 120:
        raise RemoteControlError("operation timeout is outside the closed bound")
    deadline = value.get("operation_deadline_monotonic")
    if (
        isinstance(deadline, bool) or not isinstance(deadline, (int, float))
        or not math.isfinite(float(deadline))
    ):
        raise RemoteControlError("operation monotonic deadline is invalid")
    now = time.monotonic()
    remaining = float(deadline) - now
    if remaining <= 0 or remaining > 120:
        raise RemoteControlError("remote operation monotonic deadline is outside the closed bound")
    return min(float(deadline), now + timeout)


def _remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if not math.isfinite(value) or value <= 0:
        raise RemoteControlError("remote operation deadline is exhausted")
    return value


def _wait_socket(connection: socket.socket, event: int, deadline: float) -> None:
    with selectors.DefaultSelector() as selector:
        selector.register(connection, event)
        if not selector.select(_remaining(deadline)):
            raise RemoteControlError("socket operation deadline is exhausted")


def _connect_until(connection: socket.socket, address: Any, deadline: float) -> None:
    connection.setblocking(False)
    status = connection.connect_ex(address)
    if status not in {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY}:
        raise OSError(status, os.strerror(status))
    if status:
        _wait_socket(connection, selectors.EVENT_WRITE, deadline)
        error = connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if error:
            raise OSError(error, os.strerror(error))


def _send_until(connection: socket.socket, data: bytes, deadline: float) -> None:
    view = memoryview(data)
    while view:
        _wait_socket(connection, selectors.EVENT_WRITE, deadline)
        try:
            written = connection.send(view)
        except BlockingIOError:
            continue
        if written <= 0:
            raise RemoteControlError("socket closed while sending a control message")
        view = view[written:]


def _receive_until_eof(
    connection: socket.socket, deadline: float, *, maximum_bytes: int = MAX_MESSAGE_BYTES
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    connection.setblocking(False)
    while True:
        _wait_socket(connection, selectors.EVENT_READ, deadline)
        try:
            chunk = connection.recv(min(65_536, maximum_bytes + 1 - total))
        except BlockingIOError:
            continue
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_bytes:
            raise RemoteControlError("socket message exceeds the byte limit")


def _http_post_loopback(body: bytes, deadline: float) -> bytes:
    request = (
        b"POST /v1/chat/completions HTTP/1.1\r\n"
        b"Host: 127.0.0.1:8000\r\n"
        b"Content-Type: application/json\r\n"
        b"Accept: application/json\r\n"
        b"Connection: close\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            _connect_until(connection, ("127.0.0.1", 8000), deadline)
            _send_until(connection, request, deadline)
            raw = _receive_until_eof(
                connection, deadline, maximum_bytes=MAX_MESSAGE_BYTES + 64 * 1024
            )
    except (OSError, RemoteControlError) as exc:
        raise RemoteControlError("fixed readiness request failed") from exc
    marker = raw.find(b"\r\n\r\n")
    if marker < 0 or marker > 64 * 1024:
        raise RemoteControlError("fixed readiness response headers are malformed")
    head, response_body = raw[:marker], raw[marker + 4:]
    lines = head.split(b"\r\n")
    if not lines or lines[0] != b"HTTP/1.1 200 OK":
        raise RemoteControlError("fixed readiness response status is not 200")
    headers: dict[bytes, list[bytes]] = {}
    for line in lines[1:]:
        if b":" not in line:
            raise RemoteControlError("fixed readiness response headers are malformed")
        name, value = line.split(b":", 1)
        key = name.strip().lower()
        headers.setdefault(key, []).append(value.strip())
    lengths = headers.get(b"content-length", [])
    if len(lengths) != 1 or b"transfer-encoding" in headers:
        raise RemoteControlError("fixed readiness response framing is unsupported")
    try:
        declared = int(lengths[0], 10)
    except ValueError as exc:
        raise RemoteControlError("fixed readiness response length is malformed") from exc
    if declared != len(response_body) or declared > MAX_MESSAGE_BYTES:
        raise RemoteControlError("fixed readiness response length is invalid")
    return response_body


def _deadline_ns(deadline: float) -> int:
    _remaining(deadline)
    return int(deadline * 1_000_000_000)


def _proc_start_ticks(pid: int, deadline: float) -> int:
    try:
        return proc_identity(pid, _deadline_ns(deadline))[1]
    except (OSError, NativeProbeError) as exc:
        raise RemoteControlError("runtime process identity is unavailable") from exc


def _runtime_owns_loopback_listener(root_pid: int, port: int, deadline: float) -> bool:
    try:
        return owns_loopback_listener(root_pid, port, _deadline_ns(deadline))
    except (OSError, NativeProbeError) as exc:
        raise RemoteControlError("kernel socket ownership evidence is unavailable") from exc


class NativeProbe:
    """Collect facts from the running container without provider writes."""

    def __init__(
        self, *, runner: Callable[..., Any] = run_gpu_process_query,
        http_post: Callable[[bytes, float], bytes] = _http_post_loopback,
    ) -> None:
        self.runner = runner
        self.http_post = http_post

    def _run(self, argv: Sequence[str], *, deadline: float, allow_empty: bool = False) -> str:
        try:
            result = self.runner(list(argv), int(deadline * 1_000_000_000))
        except (OSError, OwnershipError) as exc:
            raise RemoteControlError("native attestation command failed") from exc
        if result.status != "ok" or result.reason is not None or not isinstance(result.stdout, bytes):
            raise RemoteControlError("native attestation command was not successful")
        try:
            value = result.stdout.decode("ascii").strip()
        except UnicodeError as exc:
            raise RemoteControlError("native attestation command output is not ASCII") from exc
        if not value and not allow_empty:
            raise RemoteControlError("native attestation command returned no evidence")
        return value

    def gpu(self, *, deadline: float) -> dict[str, Any]:
        text = self._run([
            "/usr/bin/nvidia-smi",
            "--query-gpu=uuid,pci.bus_id,name,driver_version,memory.total,compute_cap,memory.used",
            "--format=csv,noheader,nounits",
        ], deadline=deadline)
        rows = [row for row in text.splitlines() if row.strip()]
        if len(rows) != 1:
            raise RemoteControlError("native attestation requires exactly one GPU")
        fields = [field.strip() for field in rows[0].split(",")]
        if len(fields) != 7:
            raise RemoteControlError("native GPU evidence is malformed")
        try:
            total, used = int(fields[4]), int(fields[6])
        except ValueError as exc:
            raise RemoteControlError("native GPU memory evidence is malformed") from exc
        processes = self._run([
            "/usr/bin/nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits",
        ], deadline=deadline, allow_empty=True)
        return {
            "gpu_uuid": fields[0], "gpu_pci": fields[1], "gpu_name": fields[2],
            "driver_version": fields[3], "gpu_count": 1,
            "gpu_total_memory_mib": total, "compute_capability": fields[5],
            "used_memory_mib": used,
            "compute_process_count": len([line for line in processes.splitlines() if line.strip()]),
        }

    @staticmethod
    def installed_runtime_builds(*, deadline: float) -> list[dict[str, str]]:
        paths = {
            "build_spec_sha256": Path("/opt/episode1/build-spec/Dockerfile"),
            "launcher_sha256": Path("/usr/local/bin/episode1-entrypoint"),
        }
        records = []
        for runtime, lock in (
            ("vllm-0.29.0", Path("/locks/vllm.lock")),
            ("sglang-0.5.20", Path("/locks/sglang.lock")),
        ):
            record = {"runtime": runtime}
            for key, path in {**paths, "dependency_lock_sha256": lock}.items():
                try:
                    data = bounded_read(path, MAX_FILE_BYTES, _deadline_ns(deadline))
                except (OSError, NativeProbeError) as exc:
                    raise RemoteControlError("installed build material is unavailable") from exc
                record[key] = hashlib.sha256(data).hexdigest()
                _remaining(deadline)
            records.append(record)
        return records

    def attest(self, *, deadline: float) -> Mapping[str, Any]:
        gpu = self.gpu(deadline=deadline)
        _remaining(deadline)
        try:
            boot_id = bounded_read(
                "/proc/sys/kernel/random/boot_id", 4096, _deadline_ns(deadline)
            ).decode("ascii").strip()
            attestation = bounded_read(
                "/opt/episode1/build-evidence/cpu-smoke.json",
                MAX_MESSAGE_BYTES, _deadline_ns(deadline),
            )
        except (OSError, UnicodeError, NativeProbeError) as exc:
            raise RemoteControlError("immutable image attestation inputs are unavailable") from exc
        installed = self.installed_runtime_builds(deadline=deadline)
        try:
            versions = query_library_versions(_deadline_ns(deadline))
        except NativeProbeError as exc:
            raise RemoteControlError("native CUDA library evidence is unavailable") from exc
        result = {
            "schema_version": "episode1.remote-attestation.v1", **gpu,
            "boot_id": boot_id,
            **versions,
            "build_attestation_sha256": hashlib.sha256(attestation).hexdigest(),
            "installed_runtime_builds": installed,
            "installed_material_sha256": hashlib.sha256(canonical_json(
                sorted(installed, key=lambda item: item["runtime"])
            ).encode()).hexdigest(),
        }
        _remaining(deadline)
        return result

    def probe(
        self, expected_argv: Sequence[str], pid: int, *, deadline: float,
        process_start_ticks: int,
    ) -> Mapping[str, Any]:
        try:
            observed = bounded_read(
                f"/proc/{pid}/cmdline", MAX_PROC_RECORD_BYTES, _deadline_ns(deadline)
            ).rstrip(b"\0").split(b"\0")
        except (OSError, NativeProbeError) as exc:
            raise RemoteControlError("runtime argv evidence is unavailable") from exc
        resolved = (
            "/opt/venvs/vllm/bin/vllm"
            if expected_argv[0] == "vllm" else "/opt/venvs/sglang/bin/python"
        )
        direct = observed == [item.encode() for item in expected_argv]
        resolved_form = (
            observed
            and os.path.realpath(os.fsdecode(observed[0])) == os.path.realpath(resolved)
            and observed[1:] == [item.encode() for item in expected_argv[1:]]
        )
        shebang_form = (
            expected_argv[0] == "vllm" and len(observed) >= 2
            and os.path.basename(os.fsdecode(observed[0])).startswith("python")
            and os.path.realpath(os.fsdecode(observed[1])) == os.path.realpath(resolved)
            and observed[2:] == [item.encode() for item in expected_argv[1:]]
        )
        if not (direct or resolved_form or shebang_form):
            raise RemoteControlError("running process argv differs from the frozen command")
        expected_executable = (
            "/opt/venvs/vllm/bin/python3.12"
            if expected_argv[0] == "vllm" else "/opt/venvs/sglang/bin/python"
        )
        try:
            executable = bounded_readlink(
                f"/proc/{pid}/exe", _deadline_ns(deadline)
            )
        except (OSError, NativeProbeError) as exc:
            raise RemoteControlError("runtime executable identity is unavailable") from exc
        if executable != os.path.realpath(expected_executable):
            raise RemoteControlError("runtime executable differs from the approved environment")
        if _proc_start_ticks(pid, deadline) != process_start_ticks:
            raise RemoteControlError("runtime process identity changed")
        if not _runtime_owns_loopback_listener(pid, 8000, deadline):
            raise RemoteControlError("runtime does not exclusively own the loopback listener")
        request_body = canonical_json({
            "model": MODEL,
            "messages": [{"role": "user", "content": "Write a deterministic 128-token readiness response."}],
            "temperature": 0, "top_p": 1, "max_completion_tokens": 128,
            "stream": False, "ignore_eos": True,
        }).encode()
        try:
            raw = self.http_post(request_body, min(deadline, time.monotonic() + 30))
        except Exception as exc:
            raise RemoteControlError("fixed readiness request failed") from exc
        if len(raw) > MAX_MESSAGE_BYTES:
            raise RemoteControlError("fixed readiness response exceeds the byte limit")
        try:
            value = _load_one_json(io.BytesIO(raw))
            usage = value["usage"]
            choice = value["choices"][0]
        except (KeyError, IndexError, TypeError, RemoteControlError) as exc:
            raise RemoteControlError("fixed readiness response is malformed") from exc
        completion_tokens = usage.get("completion_tokens")
        exact = (
            not isinstance(completion_tokens, bool)
            and isinstance(completion_tokens, int)
            and completion_tokens == 128
            and choice.get("finish_reason") == "length"
        )
        if not exact:
            raise RemoteControlError("fixed readiness response did not produce exactly 128 tokens")
        if _proc_start_ticks(pid, deadline) != process_start_ticks or not _runtime_owns_loopback_listener(pid, 8000, deadline):
            raise RemoteControlError("runtime process or socket identity changed during readiness probe")
        token_evidence = {
            "completion_tokens": usage["completion_tokens"],
            "finish_reason": choice["finish_reason"],
        }
        result = {
            "exact_tokens": True, "effective_flags": True, "loopback_only": True,
            "probe_sha256": hashlib.sha256(raw).hexdigest(),
            "token_evidence_sha256": hashlib.sha256(canonical_json(token_evidence).encode()).hexdigest(),
            "effective_config_sha256": argv_sha256(expected_argv),
        }
        _remaining(deadline)
        return result


class RemoteControlService:
    def __init__(
        self, supervisor: PodProcessSupervisor, probe: NativeProbe, *,
        expected_plan_sha256: str,
    ) -> None:
        if len(expected_plan_sha256) != 64:
            raise ValueError("expected plan digest is invalid")
        self.supervisor = supervisor
        self.probe = probe
        self.expected_plan_sha256 = expected_plan_sha256
        self.private_process_id: str | None = None
        self.gpu_uuid: str | None = None
        self.source_boot_id: str | None = None
        self.system_sampler: SystemSampler | None = None
        self.system_sampler_binding: Binding | None = None
        self.system_sampler_attempt_by_block: dict[str, int] = {}
        self.system_sampler_active_block: str | None = None
        self.system_sampler_retired_blocks: set[str] = set()
        self._state_lock = threading.RLock()
        self._mutation_lock = threading.Lock()
        self._sample_lock = threading.Lock()
        self._transitioning = False

    def _plan(self, value: Mapping[str, Any]) -> None:
        if value.get("plan_sha256") != self.expected_plan_sha256:
            raise RemoteControlError("request plan digest differs from the launched pod")

    @staticmethod
    def _acquire(lock: threading.Lock, deadline: float, label: str) -> None:
        remaining = deadline - time.monotonic()
        if not math.isfinite(remaining) or remaining <= 0 or not lock.acquire(timeout=remaining):
            raise RemoteControlError(f"{label} is busy until the operation deadline")

    def _handle_snapshot(
        self, value: object
    ) -> tuple[Mapping[str, Any], dict[str, Any], int, str]:
        handle = _closed(value, {"private_process_id", "runtime", "block_id"}, "handle")
        with self._state_lock:
            if self._transitioning:
                raise RemoteControlError("runtime state transition is in progress")
            private_process_id = self.private_process_id
            identity_value = self.supervisor.identity
            process = self.supervisor.process
            identity = dict(identity_value) if isinstance(identity_value, Mapping) else None
            process_pid = process.pid if process is not None else None
        if handle.get("private_process_id") != private_process_id:
            raise RemoteControlError("runtime handle is stale or foreign")
        if identity is None or any(
            handle.get(key) != identity.get(key) for key in ("runtime", "block_id")
        ):
            raise RemoteControlError("runtime handle identity mismatch")
        if isinstance(process_pid, bool) or not isinstance(process_pid, int) or process_pid <= 0:
            raise RemoteControlError("runtime process identity is unavailable")
        return handle, identity, process_pid, private_process_id

    def _require_snapshot_current(
        self, private_process_id: str, identity: Mapping[str, Any], process_pid: int
    ) -> None:
        with self._state_lock:
            current_identity = self.supervisor.identity
            current_process = self.supervisor.process
            if (
                self._transitioning
                or self.private_process_id != private_process_id
                or not isinstance(current_identity, Mapping)
                or dict(current_identity) != dict(identity)
                or current_process is None
                or current_process.pid != process_pid
            ):
                raise RemoteControlError("runtime identity changed during operation")

    def dispatch(self, action: str, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        if action == "clock":
            value = _closed(raw, {"schema_version"}, "clock request")
            if value["schema_version"] != "episode1.remote-clock-request.v1":
                raise RemoteControlError("clock request schema is unsupported")
            return {
                "schema_version": "episode1.remote-clock.v1",
                "remote_monotonic": time.monotonic(),
                "remote_wall_time_ns": time.time_ns(),
            }
        if action == "attest":
            value = _closed(raw, {"schema_version", "plan_sha256", "operation_timeout_seconds", "operation_deadline_monotonic"}, "attest request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-attest-request.v1":
                raise RemoteControlError("attest request schema is unsupported")
            self._plan(value)
            evidence = self.probe.attest(deadline=deadline)
            gpu_uuid = evidence.get("gpu_uuid")
            if not isinstance(gpu_uuid, str) or not gpu_uuid:
                raise RemoteControlError("attested GPU UUID is unavailable")
            boot_id = evidence.get("boot_id")
            if not isinstance(boot_id, str) or not boot_id:
                raise RemoteControlError("attested boot identity is unavailable")
            with self._state_lock:
                self.gpu_uuid = gpu_uuid
                self.source_boot_id = boot_id
            return {**evidence, "gpu_process_pid_domain": GPU_PROCESS_PID_DOMAIN}
        if action == "identity":
            value = _closed(raw, {
                "schema_version", "handle", "operation_timeout_seconds",
                "operation_deadline_monotonic",
            }, "identity request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-identity-request.v1":
                raise RemoteControlError("identity request schema is unsupported")
            _handle, identity, process_pid, private_process_id = self._handle_snapshot(
                value["handle"]
            )
            process_start_ticks = _proc_start_ticks(process_pid, deadline)
            listener_owned = _runtime_owns_loopback_listener(process_pid, 8000, deadline)
            if (
                process_start_ticks != int(identity["process_start_ticks"])
                or not listener_owned
            ):
                raise RemoteControlError("runtime process or listener identity changed")
            self._require_snapshot_current(private_process_id, identity, process_pid)
            return {
                "schema_version": "episode1.remote-identity.v1",
                "private_process_id": private_process_id,
                "process_pid": process_pid,
                "process_start_ticks": process_start_ticks,
                "loopback_listener_owned": True,
            }
        if action == "sample":
            value = _closed(raw, {
                "schema_version", "plan_sha256", "binding", "phase", "slot_kind", "handle",
                "startup_attempt_id",
                "operation_timeout_seconds", "operation_deadline_monotonic",
            }, "sample request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-sample-request.v1":
                raise RemoteControlError("sample request schema is unsupported")
            self._plan(value)
            binding_value = _closed(
                value["binding"], {"run_id", "attempt_id", "block", "clock_domain", "source_boot_id"},
                "sample binding",
            )
            try:
                binding = Binding(**dict(binding_value))
            except (TypeError, ValueError) as exc:
                raise RemoteControlError("sample binding is invalid") from exc
            startup_attempt_id = value["startup_attempt_id"]
            prefix = f"{binding.block}-attempt-"
            suffix = (startup_attempt_id[len(prefix):]
                      if isinstance(startup_attempt_id, str)
                      and startup_attempt_id.startswith(prefix) else "")
            if not suffix.isdigit() or suffix.startswith("0"):
                raise RemoteControlError("sample startup attempt identity is invalid")
            startup_attempt = int(suffix)
            if startup_attempt not in {1, 2}:
                raise RemoteControlError("sample startup attempt is outside the retry policy")
            with self._state_lock:
                gpu_uuid = self.gpu_uuid
                source_boot_id = self.source_boot_id
            if gpu_uuid is None or source_boot_id is None:
                raise RemoteControlError("sampling requires prior GPU attestation")
            try:
                current_boot_id = bounded_read(
                    "/proc/sys/kernel/random/boot_id", 4096, _deadline_ns(deadline)
                ).decode("ascii").strip()
            except (OSError, UnicodeError, NativeProbeError) as exc:
                raise RemoteControlError("current boot identity is unavailable") from exc
            if current_boot_id != source_boot_id or binding.source_boot_id != source_boot_id:
                raise RemoteControlError("system sample boot identity differs from attestation")
            snapshot = None
            self._acquire(self._sample_lock, deadline, "system sampler")
            try:
                if binding.block != self.system_sampler_active_block:
                    if binding.block in self.system_sampler_retired_blocks:
                        raise RemoteControlError("sample block was already retired")
                    if self.system_sampler_active_block is not None:
                        self.system_sampler_retired_blocks.add(
                            self.system_sampler_active_block
                        )
                    self.system_sampler_active_block = binding.block
                previous_attempt = self.system_sampler_attempt_by_block.get(binding.block)
                if previous_attempt is None:
                    if startup_attempt != 1:
                        raise RemoteControlError("sample startup attempt skipped its first attempt")
                elif startup_attempt not in {previous_attempt, previous_attempt + 1}:
                    raise RemoteControlError("sample startup attempt is duplicate or reordered")
                if (self.system_sampler_binding != binding
                        or previous_attempt != startup_attempt):
                    self.system_sampler_binding = binding
                    self.system_sampler_attempt_by_block[binding.block] = startup_attempt
                    self.system_sampler = SystemSampler(
                        binding, NvidiaSmiAdapter(Path("/usr/bin/nvidia-smi"), gpu_uuid),
                        ProcAdapter(),
                    )
                assert self.system_sampler is not None
                target = None
                if value["handle"] is not None:
                    snapshot = self._handle_snapshot(value["handle"])
                    _handle, identity, _process_pid, _private_id = snapshot
                    target = ProcessTarget(
                        int(identity["pid"]), int(identity["process_start_ticks"]),
                        str(identity["runtime"]),
                    )
                slot_kind = value["slot_kind"]
                if slot_kind in {"measurement_start_boundary", "measurement_end_boundary"}:
                    if target is None or value["phase"] != "measurement":
                        raise RemoteControlError("measurement boundary requires a live measured process")
                    marker = "measurement_start" if slot_kind == "measurement_start_boundary" else "measurement_end"
                    record = self.system_sampler.sample_boundary(
                        target, marker, hard_deadline_ns=int(deadline * 1_000_000_000)
                    )
                elif slot_kind == "periodic":
                    record = self.system_sampler.sample_periodic(
                        target, str(value["phase"]),
                        hard_deadline_ns=int(deadline * 1_000_000_000),
                    )
                else:
                    raise RemoteControlError("system sample slot kind is invalid")
                if snapshot is not None:
                    self._require_snapshot_current(snapshot[3], snapshot[1], snapshot[2])
            finally:
                self._sample_lock.release()
            source = (canonical_json(record) + "\n").encode()
            return {
                "schema_version": "episode1.remote-sample.v1",
                "record": record,
                "source_sha256": hashlib.sha256(source).hexdigest(),
            }
        if action == "start":
            value = _closed(raw, {"schema_version", "plan_sha256", "block", "runtime_build", "operation_timeout_seconds", "operation_deadline_monotonic"}, "start request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-start-request.v1":
                raise RemoteControlError("start request schema is unsupported")
            self._plan(value)
            block = _closed(value["block"], {
                "block_id", "pair_id", "position", "runtime", "fresh_process_required", "cell_order",
            }, "block")
            build = _closed(value["runtime_build"], {
                "runtime", "build_spec_sha256", "dependency_lock_sha256", "launcher_sha256",
                "build_attestation_sha256", "derived_image_digest", "post_create_gpu_check_required",
                "post_create_effective_flags_check_required",
            }, "runtime build")
            self._acquire(self._mutation_lock, deadline, "runtime mutation")
            try:
                installed = {
                    item["runtime"]: item for item in self.probe.installed_runtime_builds(deadline=deadline)
                }.get(str(block["runtime"]))
                expected_installed = {key: build[key] for key in (
                    "runtime", "build_spec_sha256", "dependency_lock_sha256", "launcher_sha256",
                )}
                if build["runtime"] != block["runtime"] or installed != expected_installed:
                    raise RemoteControlError("runtime build is not bound to installed image material")
                _remaining(deadline)
                argv = runtime_argv(str(block["runtime"]))
                env = dict(os.environ)
                venv = "/opt/venvs/vllm/bin" if block["runtime"] == "vllm-0.29.0" else "/opt/venvs/sglang/bin"
                env["PATH"] = venv + ":" + env.get("PATH", "")
                with self._state_lock:
                    self._transitioning = True
                try:
                    identity = self.supervisor.start(
                        argv, runtime=str(block["runtime"]), block_id=str(block["block_id"]),
                        specification_sha256=hashlib.sha256(canonical_json({"block": block, "runtime_build": build}).encode()).hexdigest(),
                        environment=env, deadline_monotonic=deadline,
                    )
                    private_process_id = f"runtime-{identity['pid']}-{identity['started_monotonic_ns']}"
                    with self._state_lock:
                        self.private_process_id = private_process_id
                finally:
                    with self._state_lock:
                        self._transitioning = False
            finally:
                self._mutation_lock.release()
            return {
                "schema_version": "episode1.remote-start.v1",
                "private_process_id": private_process_id,
                "runtime": block["runtime"], "block_id": block["block_id"],
                "process_pid": identity["pid"],
                "process_start_ticks": identity["process_start_ticks"],
                "argv_sha256": identity["argv_sha256"],
                "started_monotonic_ns": identity["started_monotonic_ns"],
                "kernel_path": "native_runtime", "kernel_evidence_sha256": None,
                "kernel_unavailable_reason": NATIVE_KERNEL_REASON,
            }
        if action == "probe":
            value = _closed(raw, {"schema_version", "plan_sha256", "handle", "operation_timeout_seconds", "operation_deadline_monotonic"}, "probe request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-handle-request.v1":
                raise RemoteControlError("probe request schema is unsupported")
            self._plan(value)
            handle, identity, process_pid, private_process_id = self._handle_snapshot(value["handle"])
            argv = runtime_argv(str(handle["runtime"]))
            evidence = self.probe.probe(
                argv, process_pid, deadline=deadline,
                process_start_ticks=int(identity["process_start_ticks"]),
            )
            with self._state_lock:
                gpu_uuid = self.gpu_uuid
            if gpu_uuid is None:
                raise RemoteControlError("GPU ownership proof requires prior attestation")
            try:
                ownership = collect_gpu_process_ownership(
                    root_pid=int(identity["pid"]),
                    root_start_ticks=int(identity["process_start_ticks"]),
                    expected_gpu_uuid=gpu_uuid,
                    pid_domain=GPU_PROCESS_PID_DOMAIN,
                    runner=run_gpu_process_query,
                    proc=LinuxProcSource(),
                    deadline_monotonic_ns=int(deadline * 1_000_000_000),
                )
            except OwnershipError as exc:
                raise RemoteControlError("GPU process ownership evidence is unavailable") from exc
            self._require_snapshot_current(private_process_id, identity, process_pid)
            return {
                "schema_version": "episode1.remote-probe.v1",
                "private_process_id": private_process_id, **evidence,
                "argv_sha256": argv_sha256(argv),
                "gpu_process_ownership": ownership,
            }
        if action == "stop":
            value = _closed(raw, {"schema_version", "handle", "operation_timeout_seconds", "operation_deadline_monotonic"}, "stop request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-handle-request.v1":
                raise RemoteControlError("stop request schema is unsupported")
            self._acquire(self._mutation_lock, deadline, "runtime mutation")
            try:
                _handle, identity, process_pid, private_process_id = self._handle_snapshot(value["handle"])
                with self._state_lock:
                    self._transitioning = True
                try:
                    stopped = self.supervisor.stop(deadline_monotonic=deadline)
                finally:
                    with self._state_lock:
                        self._transitioning = False
                result = {
                    "schema_version": "episode1.remote-stop.v1",
                    "private_process_id": private_process_id,
                    "reaped": stopped["reaped"],
                    "endpoint_closed": loopback_port_absent(8000),
                    "sigkill_used": stopped["sigkill_used"],
                }
            finally:
                self._mutation_lock.release()
            return result
        if action == "status":
            value = _closed(raw, {"schema_version", "handle", "operation_timeout_seconds", "operation_deadline_monotonic"}, "status request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-handle-request.v1":
                raise RemoteControlError("status request schema is unsupported")
            self._acquire(self._mutation_lock, deadline, "runtime mutation")
            try:
                _handle, _identity, _process_pid, private_process_id = self._handle_snapshot(value["handle"])
                result = {
                    "schema_version": "episode1.remote-status.v1",
                    "private_process_id": private_process_id,
                    "descendants_absent": self.supervisor.descendants_absent(),
                    "endpoint_closed": loopback_port_absent(8000),
                }
            finally:
                self._mutation_lock.release()
            return result
        if action == "memory":
            value = _closed(raw, {"schema_version", "baseline", "operation_timeout_seconds", "operation_deadline_monotonic"}, "memory request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-memory-request.v1":
                raise RemoteControlError("memory request schema is unsupported")
            gpu = self.probe.gpu(deadline=deadline)
            return {"schema_version": "episode1.remote-memory.v1", **{
                key: gpu[key] for key in ("gpu_uuid", "used_memory_mib", "compute_process_count")
            }}
        if action == "cleanup-failed-start":
            value = _closed(raw, {"schema_version", "block", "baseline", "operation_timeout_seconds", "operation_deadline_monotonic"}, "cleanup request")
            deadline = _request_deadline(value)
            if value["schema_version"] != "episode1.remote-cleanup-request.v1":
                raise RemoteControlError("cleanup request schema is unsupported")
            self._acquire(self._mutation_lock, deadline, "runtime mutation")
            try:
                with self._state_lock:
                    self._transitioning = True
                try:
                    if self.supervisor.cleanup_required:
                        self.supervisor.stop(deadline_monotonic=deadline)
                finally:
                    with self._state_lock:
                        self._transitioning = False
                gpu = self.probe.gpu(deadline=deadline)
                descendants_absent = (
                    not self.supervisor.cleanup_required and self.supervisor.descendants_absent()
                )
                result = {
                    "schema_version": "episode1.remote-cleanup.v1",
                    "descendants_absent": descendants_absent,
                    "endpoint_closed": loopback_port_absent(8000),
                    **{key: gpu[key] for key in ("gpu_uuid", "used_memory_mib", "compute_process_count")},
                }
            finally:
                self._mutation_lock.release()
            return result
        raise RemoteControlError("control action is not allowed")


def _serve_connection(service: RemoteControlService, connection: socket.socket) -> None:
    with connection:
        request: Mapping[str, Any] | None = None
        try:
            request = _load_one_json(io.BytesIO(_receive_until_eof(
                connection, time.monotonic() + 5
            )))
            envelope = _closed(request, {"action", "payload"}, "control envelope")
            if not isinstance(envelope["action"], str):
                raise RemoteControlError("control action must be a string")
            result = service.dispatch(envelope["action"], envelope["payload"])
            response = {"ok": True, "result": result}
        except (OSError, RemoteControlError, SupervisorError) as exc:
            response = {"ok": False, "error": str(exc)}
        encoded = canonical_json(response).encode() + b"\n"
        if len(encoded) > MAX_MESSAGE_BYTES:
            encoded = b'{"error":"control response exceeds the byte limit","ok":false}\n'
        action = request.get("action") if request is not None else None
        payload = request.get("payload") if request is not None else None
        supplied = payload.get("operation_deadline_monotonic") if isinstance(payload, Mapping) else None
        if action == "clock":
            response_deadline = time.monotonic() + 5
        elif (
            not isinstance(supplied, bool)
            and isinstance(supplied, (int, float))
            and math.isfinite(float(supplied))
        ):
            # Never renew an expired operation merely to deliver its error.
            response_deadline = float(supplied)
        else:
            response_deadline = time.monotonic()
        try:
            _send_until(connection, encoded, response_deadline)
        except (OSError, RemoteControlError):
            pass


class _BoundedConnectionDispatcher:
    """Run at most ``capacity`` requests; excess accepted sockets fail closed."""

    def __init__(self, service: RemoteControlService, capacity: int = MAX_CONTROL_WORKERS) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("control worker capacity must be a positive integer")
        self.service = service
        self._slots = threading.BoundedSemaphore(capacity)
        self._threads: set[threading.Thread] = set()
        self._threads_lock = threading.Lock()

    def _run(self, connection: socket.socket) -> None:
        try:
            _serve_connection(self.service, connection)
        finally:
            with self._threads_lock:
                self._threads.discard(threading.current_thread())
            self._slots.release()

    def submit(self, connection: socket.socket) -> bool:
        if not self._slots.acquire(blocking=False):
            with connection:
                try:
                    connection.setblocking(False)
                    connection.send(b'{"error":"control server is busy","ok":false}\n')
                except OSError:
                    pass
            return False
        thread = threading.Thread(target=self._run, args=(connection,), daemon=True)
        try:
            with self._threads_lock:
                self._threads.add(thread)
            thread.start()
        except BaseException:
            with self._threads_lock:
                self._threads.discard(thread)
            self._slots.release()
            connection.close()
            raise
        return True

    def wait_idle(self, deadline: float) -> bool:
        while True:
            with self._threads_lock:
                threads = tuple(self._threads)
            if not threads:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            threads[0].join(min(remaining, 0.02))


def serve(service: RemoteControlService, path: Path = SOCKET_PATH) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(8)
        dispatcher = _BoundedConnectionDispatcher(service)
        while True:
            connection, _ = server.accept()
            dispatcher.submit(connection)


def client(action: str, payload: Mapping[str, Any], path: Path = SOCKET_PATH) -> Mapping[str, Any]:
    if action not in {"clock", "attest", "sample", "start", "probe", "stop", "status", "memory", "cleanup-failed-start"}:
        raise RemoteControlError("control action is not allowed")
    encoded = canonical_json({"action": action, "payload": payload}).encode()
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise RemoteControlError("control request exceeds the byte limit")
    supplied = payload.get("operation_deadline_monotonic")
    now = time.monotonic()
    if action == "clock":
        deadline = now + 5
    elif (
        isinstance(supplied, bool)
        or not isinstance(supplied, (int, float))
        or not math.isfinite(float(supplied))
        or float(supplied) <= now
        or float(supplied) > now + 120
    ):
        raise RemoteControlError("client operation monotonic deadline is outside the closed bound")
    else:
        deadline = float(supplied)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        _connect_until(connection, str(path), deadline)
        _send_until(connection, encoded, deadline)
        connection.shutdown(socket.SHUT_WR)
        response = _load_one_json(io.BytesIO(_receive_until_eof(connection, deadline)))
    envelope = _closed(response, {"ok", "result"} if response.get("ok") is True else {"ok", "error"}, "control response")
    if envelope["ok"] is not True:
        raise RemoteControlError(str(envelope["error"]))
    if not isinstance(envelope["result"], Mapping):
        raise RemoteControlError("control result must be an object")
    return envelope["result"]


def daemon_main() -> None:
    plan_sha256 = os.environ.get("EPISODE1_PLAN_SHA256", "")
    serve(RemoteControlService(PodProcessSupervisor(STATE_DIRECTORY), NativeProbe(), expected_plan_sha256=plan_sha256))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (["--help"], ["-h"]):
        sys.stdout.write("usage: episode1-control {daemon|clock|attest|sample|start|probe|stop|status|memory|cleanup-failed-start}\n")
        return 0
    if arguments == ["daemon"]:
        daemon_main()
        return 0
    if len(arguments) != 1:
        raise RemoteControlError("usage: episode1-control ACTION")
    payload = _load_one_json(sys.stdin.buffer)
    result = client(arguments[0], payload)
    sys.stdout.write(canonical_json(result) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RemoteControlError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(2)
