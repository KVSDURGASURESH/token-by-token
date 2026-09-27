"""Closed GPU-process ownership evidence for an already started runtime.

The caller supplies a whole-operation-deadline-bounded command runner.  This
module never treats unavailable NVIDIA evidence as an empty process set.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, Sequence

SCHEMA = "episode1.gpu-process-ownership.v1"
QUERY = (
    "/usr/bin/nvidia-smi",
    "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
    "--format=csv,noheader,nounits",
)
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_PROC_BYTES = 64 * 1024
MAX_TOTAL_PROC_BYTES = 32 * 1024 * 1024
MAX_PROCESSES = 131072
COMMAND_CLEANUP_RESERVE_NS = 250_000_000
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GPU_UUID = re.compile(r"^GPU-[A-Za-z0-9-]+$")


class OwnershipError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    status: str                 # exactly "ok" for usable evidence
    stdout: bytes | None
    reason: str | None


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _cleanup_group(process: subprocess.Popen[bytes], deadline_ns: int,
                   monotonic_ns: Callable[[], int]) -> None:
    """Terminate, kill, and reap using portions of the caller's deadline."""
    start = monotonic_ns()
    remaining = max(0, deadline_ns - start)
    term_deadline = start + remaining * 2 // 5
    kill_deadline = start + remaining * 4 // 5

    def reap_until(deadline: int) -> None:
        while process.poll() is None:
            remaining_ns = deadline - monotonic_ns()
            if remaining_ns <= 0:
                break
            try:
                process.wait(timeout=min(0.02, remaining_ns / 1e9))
            except subprocess.TimeoutExpired:
                pass

    if _group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    reap_until(term_deadline)
    while _group_exists(process.pid) and monotonic_ns() < term_deadline:
        time.sleep(min(0.005, max(0.0, (term_deadline - monotonic_ns()) / 1e9)))
    if _group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    reap_until(kill_deadline)
    while _group_exists(process.pid) and monotonic_ns() < deadline_ns:
        time.sleep(min(0.005, max(0.0, (deadline_ns - monotonic_ns()) / 1e9)))
    reap_until(deadline_ns)
    if process.poll() is None or _group_exists(process.pid):
        raise OwnershipError("command_cleanup_incomplete")


def run_command(argv: Sequence[str], deadline_monotonic_ns: int, *,
                max_bytes: int = MAX_OUTPUT_BYTES,
                cleanup_reserve_ns: int = COMMAND_CLEANUP_RESERVE_NS,
                monotonic_ns: Callable[[], int] = time.monotonic_ns) -> CommandResult:
    """Bounded local command seam; no retry and no shell or ambient environment."""
    if (not argv or any(not isinstance(item, str) or "\x00" in item for item in argv)
            or not os.path.isabs(argv[0])):
        raise ValueError("command executable must be absolute")
    for value in (deadline_monotonic_ns, max_bytes, cleanup_reserve_ns):
        _exact_int(value, positive=True)
    work_deadline = deadline_monotonic_ns - cleanup_reserve_ns
    if monotonic_ns() >= work_deadline:
        return CommandResult("unavailable", b"", "deadline_exhausted")
    try:
        process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, close_fds=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
        )
    except OSError:
        return CommandResult("unavailable", b"", "spawn_failed")
    selector: selectors.BaseSelector | None = None
    buffers: dict[int, bytearray] = {}
    stdout_fd: int | None = None
    outcome = CommandResult("unavailable", b"", "setup_failed")
    try:
        assert process.stdout is not None and process.stderr is not None
        selector = selectors.DefaultSelector()
        stdout_fd = process.stdout.fileno()
        buffers = {stdout_fd: bytearray(), process.stderr.fileno(): bytearray()}
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining_ns = work_deadline - monotonic_ns()
            if remaining_ns <= 0:
                outcome = CommandResult("unavailable", bytes(buffers[stdout_fd]), "command_timeout")
                break
            events = selector.select(remaining_ns / 1e9)
            if not events:
                outcome = CommandResult("unavailable", bytes(buffers[stdout_fd]), "command_timeout")
                break
            for key, _mask in events:
                try:
                    chunk = os.read(key.fd, 16_384)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                elif sum(map(len, buffers.values())) + len(chunk) > max_bytes:
                    outcome = CommandResult("unavailable", bytes(buffers[stdout_fd]), "output_limit")
                    break
                else:
                    buffers[key.fd].extend(chunk)
            if outcome.reason == "output_limit":
                break
        else:
            remaining_ns = work_deadline - monotonic_ns()
            if remaining_ns <= 0:
                outcome = CommandResult("unavailable", bytes(buffers[stdout_fd]), "command_timeout")
            else:
                try:
                    returncode = process.wait(timeout=remaining_ns / 1e9)
                except subprocess.TimeoutExpired:
                    outcome = CommandResult("unavailable", bytes(buffers[stdout_fd]), "command_timeout")
                else:
                    outcome = (CommandResult("ok", bytes(buffers[stdout_fd]), None)
                               if returncode == 0 else
                               CommandResult("unavailable", bytes(buffers[stdout_fd]), "command_failed"))
        return outcome
    finally:
        if selector is not None:
            selector.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        _cleanup_group(process, deadline_monotonic_ns, monotonic_ns)


class ProcSource(Protocol):
    def pids(self, deadline_ns: int, monotonic_ns: Callable[[], int]) -> Iterable[int]: ...
    def read(self, path: str, max_bytes: int, deadline_ns: int,
             monotonic_ns: Callable[[], int]) -> bytes: ...


class LinuxProcSource:
    """Bounded, non-executing production adapter for the current PID namespace."""
    def pids(self, deadline_ns: int,
             monotonic_ns: Callable[[], int]) -> Iterable[int]:
        count = 0
        try:
            entries = os.scandir("/proc")
        except OSError as exc:
            raise OwnershipError("proc_inventory_unavailable") from exc
        with entries:
            for item in entries:
                _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_inventory")
                if not item.name.isdigit():
                    continue
                count += 1
                if count > MAX_PROCESSES:
                    raise OwnershipError("proc_process_limit")
                yield int(item.name)
        _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_inventory")

    def read(self, path: str, max_bytes: int, deadline_ns: int,
             monotonic_ns: Callable[[], int]) -> bytes:
        if not path.startswith("/proc/") or max_bytes <= 0:
            raise OwnershipError("invalid_proc_read")
        _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_proc_read")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        except OSError:
            raise
        try:
            chunks, size = [], 0
            while True:
                _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_proc_read")
                chunk = os.read(fd, min(8192, max_bytes + 1 - size))
                _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_proc_read")
                if not chunk:
                    break
                chunks.append(chunk); size += len(chunk)
                if size > max_bytes:
                    raise OwnershipError("proc_record_too_large")
            return b"".join(chunks)
        finally:
            os.close(fd)


def _before_deadline(deadline_ns: int, monotonic_ns: Callable[[], int], reason: str) -> None:
    if monotonic_ns() >= deadline_ns:
        raise OwnershipError(reason)


def _valid_gpu_uuid(value: object) -> bool:
    return isinstance(value, str) and GPU_UUID.fullmatch(value) is not None


@dataclass(frozen=True)
class ProcIdentity:
    pid: int
    parent_pid: int
    start_ticks: int
    nspid: tuple[int, ...]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _exact_int(value: object, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise OwnershipError("invalid_integer")
    return value


def _parse_proc(pid: int, stat: bytes, status: bytes) -> ProcIdentity:
    try:
        stat_text = stat.decode("ascii")
        tail = stat_text[stat_text.rfind(")") + 2:].split()
        if int(stat_text[:stat_text.find(" ")]) != pid:
            raise ValueError
        parent, start = int(tail[1]), int(tail[19])
        status_lines = status.decode("ascii").splitlines()
        values = [line.split()[1:] for line in status_lines if line.startswith("NSpid:")]
        if len(values) > 1:
            raise ValueError
        nspid = tuple(int(item) for item in values[0]) if values else ()
        if parent < 0 or start <= 0 or any(item <= 0 for item in nspid):
            raise ValueError
    except (UnicodeError, ValueError, IndexError) as exc:
        raise OwnershipError("invalid_proc_identity") from exc
    return ProcIdentity(pid, parent, start, nspid)


def _snapshot(source: ProcSource, root_pid: int, root_start_ticks: int, *,
              deadline_ns: int, monotonic_ns: Callable[[], int]) -> tuple[dict[int, ProcIdentity], set[int]]:
    identities: dict[int, ProcIdentity] = {}
    seen_pids: set[int] = set()
    total_bytes = 0
    _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_inventory")
    for pid in source.pids(deadline_ns, monotonic_ns):
        _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_inventory")
        if type(pid) is not int or pid <= 0 or pid in seen_pids:
            raise OwnershipError("invalid_proc_inventory")
        seen_pids.add(pid)
        if len(seen_pids) > MAX_PROCESSES:
            raise OwnershipError("proc_process_limit")
        try:
            _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_proc_scan")
            stat = source.read(f"/proc/{pid}/stat", MAX_PROC_BYTES,
                               deadline_ns, monotonic_ns)
            _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_proc_scan")
            status = source.read(f"/proc/{pid}/status", MAX_PROC_BYTES,
                                 deadline_ns, monotonic_ns)
            _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_proc_scan")
        except OSError:
            _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_proc_scan")
            if pid == root_pid:
                raise OwnershipError("runtime_root_unavailable")
            continue
        if not isinstance(stat, bytes) or not isinstance(status, bytes):
            raise OwnershipError("proc_record_not_bytes")
        if len(stat) > MAX_PROC_BYTES or len(status) > MAX_PROC_BYTES:
            raise OwnershipError("proc_record_too_large")
        total_bytes += len(stat) + len(status)
        if total_bytes > MAX_TOTAL_PROC_BYTES:
            raise OwnershipError("proc_snapshot_byte_limit")
        try:
            identity = _parse_proc(pid, stat, status)
        except OwnershipError:
            if pid == root_pid:
                raise OwnershipError("runtime_root_unavailable")
            continue
        identities[pid] = identity
    _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_inventory")
    root = identities.get(root_pid)
    if root is None or root.start_ticks != root_start_ticks:
        raise OwnershipError("runtime_root_identity_changed")
    children: dict[int, list[int]] = {}
    for pid, identity in identities.items():
        _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_tree_build")
        children.setdefault(identity.parent_pid, []).append(pid)
    owned, pending = {root_pid}, [root_pid]
    while pending:
        _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_tree_build")
        parent = pending.pop()
        for child in children.get(parent, ()):
            if child not in owned:
                owned.add(child); pending.append(child)
    return identities, owned


def _parse_rows(raw: bytes, expected_gpu_uuid: str) -> list[tuple[int, str, int]]:
    if not raw or len(raw) > MAX_OUTPUT_BYTES:
        raise OwnershipError("gpu_process_output_missing_or_oversize")
    try:
        text = raw.decode("ascii")
    except UnicodeError as exc:
        raise OwnershipError("gpu_process_output_not_ascii") from exc
    rows: list[tuple[int, str, int]] = []
    seen: set[tuple[int, str]] = set()
    for line in text.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 3:
            raise OwnershipError("gpu_process_row_malformed")
        try:
            pid, used = int(fields[0]), int(fields[2])
        except ValueError as exc:
            raise OwnershipError("gpu_process_row_malformed") from exc
        gpu = fields[1]
        if pid <= 0 or used < 0 or not GPU_UUID.fullmatch(gpu):
            raise OwnershipError("gpu_process_row_malformed")
        if gpu != expected_gpu_uuid:
            raise OwnershipError("gpu_process_on_unexpected_device")
        if (pid, gpu) in seen:
            raise OwnershipError("duplicate_gpu_process_row")
        seen.add((pid, gpu)); rows.append((pid, gpu, used))
    if not rows:
        raise OwnershipError("no_gpu_compute_process")
    return sorted(rows)


def _map(reported_pid: int, identities: dict[int, ProcIdentity], owned: set[int], domain: str) -> ProcIdentity:
    if domain == "proc_pid":
        candidates = [identities[reported_pid]] if reported_pid in identities else []
    elif domain == "outermost_nspid":
        candidates = [item for item in identities.values() if item.nspid and item.nspid[0] == reported_pid]
    else:
        raise OwnershipError("unsupported_pid_domain")
    if len(candidates) != 1:
        raise OwnershipError("gpu_pid_mapping_missing_or_ambiguous")
    identity = candidates[0]
    if identity.pid not in owned:
        raise OwnershipError("gpu_process_not_owned_by_runtime")
    return identity


def _ownership_path(identity: ProcIdentity, identities: dict[int, ProcIdentity],
                    root_pid: int, *, deadline_ns: int,
                    monotonic_ns: Callable[[], int]) -> list[ProcIdentity]:
    """Return the complete root-to-process identity chain from one snapshot."""
    path, seen = [identity], {identity.pid}
    while path[-1].pid != root_pid:
        _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_binding")
        parent = identities.get(path[-1].parent_pid)
        if parent is None or parent.pid in seen or len(path) >= MAX_PROCESSES:
            raise OwnershipError("gpu_process_ancestry_invalid")
        path.append(parent); seen.add(parent.pid)
    return list(reversed(path))


def _identity_record(identity: ProcIdentity) -> dict[str, object]:
    return {"pid": identity.pid, "parent_pid": identity.parent_pid,
            "start_ticks": identity.start_ticks, "nspid": list(identity.nspid)}


def _tree_records(identities: dict[int, ProcIdentity], owned: set[int], *,
                  deadline_ns: int, monotonic_ns: Callable[[], int]) -> list[dict[str, object]]:
    records = []
    for pid in sorted(owned):
        _before_deadline(deadline_ns, monotonic_ns, "deadline_exhausted_during_tree_receipt")
        records.append(_identity_record(identities[pid]))
    return records


def collect(
    *, root_pid: int, root_start_ticks: int, expected_gpu_uuid: str,
    pid_domain: str, runner: Callable[[Sequence[str], int], CommandResult],
    proc: ProcSource, deadline_monotonic_ns: int,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> dict[str, object]:
    _exact_int(root_pid, positive=True); _exact_int(root_start_ticks, positive=True)
    _exact_int(deadline_monotonic_ns, positive=True)
    if not _valid_gpu_uuid(expected_gpu_uuid):
        raise OwnershipError("invalid_expected_gpu_uuid")
    _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted")
    before, owned_before = _snapshot(
        proc, root_pid, root_start_ticks,
        deadline_ns=deadline_monotonic_ns, monotonic_ns=monotonic_ns,
    )
    _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted_before_query")
    result = runner(QUERY, deadline_monotonic_ns)
    if result.status != "ok" or result.reason is not None or not isinstance(result.stdout, bytes):
        raise OwnershipError("gpu_process_query_unavailable")
    _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted_after_query")
    rows = _parse_rows(result.stdout, expected_gpu_uuid)
    before_rows_hash = hashlib.sha256(result.stdout).hexdigest()
    _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted_after_parse")
    after, owned_after = _snapshot(
        proc, root_pid, root_start_ticks,
        deadline_ns=deadline_monotonic_ns, monotonic_ns=monotonic_ns,
    )
    _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted_after_snapshot")
    processes = []
    proof_nodes = 0
    for reported_pid, gpu, used in rows:
        _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted_during_binding")
        first = _map(reported_pid, before, owned_before, pid_domain)
        second = _map(reported_pid, after, owned_after, pid_domain)
        first_path = _ownership_path(
            first, before, root_pid,
            deadline_ns=deadline_monotonic_ns, monotonic_ns=monotonic_ns,
        )
        second_path = _ownership_path(
            second, after, root_pid,
            deadline_ns=deadline_monotonic_ns, monotonic_ns=monotonic_ns,
        )
        if first != second or first_path != second_path:
            raise OwnershipError("gpu_process_identity_changed")
        proof_nodes += len(first_path)
        if proof_nodes > MAX_PROCESSES:
            raise OwnershipError("ownership_proof_node_limit")
        processes.append({
            "nvidia_pid": reported_pid, "proc_pid": first.pid,
            "proc_start_ticks": first.start_ticks, "nspid": list(first.nspid),
            "gpu_uuid": gpu, "used_memory_mib": used,
            "ownership_path": [_identity_record(item) for item in first_path],
        })
    tree_before = _tree_records(
        before, owned_before,
        deadline_ns=deadline_monotonic_ns, monotonic_ns=monotonic_ns,
    )
    tree_after = _tree_records(
        after, owned_after,
        deadline_ns=deadline_monotonic_ns, monotonic_ns=monotonic_ns,
    )
    body: dict[str, object] = {
        "schema_version": SCHEMA,
        "source": "nvidia-smi-query-compute-apps-plus-procfs",
        "query_argv_sha256": hashlib.sha256(_canonical(list(QUERY))).hexdigest(),
        "raw_stdout_sha256": before_rows_hash,
        "observed_monotonic_ns": monotonic_ns(), "pid_domain": pid_domain,
        "root": {"pid": root_pid, "start_ticks": root_start_ticks},
        "gpu_uuid": expected_gpu_uuid, "process_count": len(processes),
        "total_used_memory_mib": sum(int(item["used_memory_mib"]) for item in processes),
        "processes": processes,
        "tree_before_sha256": hashlib.sha256(_canonical(tree_before)).hexdigest(),
        "tree_after_sha256": hashlib.sha256(_canonical(tree_after)).hexdigest(),
    }
    body["receipt_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted_during_receipt")
    verify(body, root_pid=root_pid, root_start_ticks=root_start_ticks,
           expected_gpu_uuid=expected_gpu_uuid, pid_domain=pid_domain)
    _before_deadline(deadline_monotonic_ns, monotonic_ns, "deadline_exhausted_after_verification")
    return body


def verify(receipt: object, *, root_pid: int, root_start_ticks: int,
           expected_gpu_uuid: str, pid_domain: str) -> None:
    _exact_int(root_pid, positive=True)
    _exact_int(root_start_ticks, positive=True)
    if not _valid_gpu_uuid(expected_gpu_uuid) or pid_domain not in {"proc_pid", "outermost_nspid"}:
        raise OwnershipError("invalid_verification_binding")
    if not isinstance(receipt, dict):
        raise OwnershipError("receipt_not_object")
    keys = {"schema_version", "source", "query_argv_sha256", "raw_stdout_sha256",
            "observed_monotonic_ns", "pid_domain", "root", "gpu_uuid", "process_count",
            "total_used_memory_mib", "processes", "tree_before_sha256",
            "tree_after_sha256", "receipt_sha256"}
    if set(receipt) != keys or receipt["schema_version"] != SCHEMA or receipt["source"] != "nvidia-smi-query-compute-apps-plus-procfs":
        raise OwnershipError("receipt_open_or_wrong_schema")
    if receipt["pid_domain"] != pid_domain or receipt["gpu_uuid"] != expected_gpu_uuid:
        raise OwnershipError("receipt_binding_mismatch")
    root = receipt["root"]
    if not isinstance(root, dict) or set(root) != {"pid", "start_ticks"}:
        raise OwnershipError("receipt_root_invalid")
    _exact_int(root["pid"], positive=True)
    _exact_int(root["start_ticks"], positive=True)
    if root != {"pid": root_pid, "start_ticks": root_start_ticks}:
        raise OwnershipError("receipt_root_mismatch")
    for key in ("query_argv_sha256", "raw_stdout_sha256", "tree_before_sha256", "tree_after_sha256", "receipt_sha256"):
        if not isinstance(receipt[key], str) or not SHA256.fullmatch(receipt[key]):
            raise OwnershipError("receipt_digest_invalid")
    if receipt["query_argv_sha256"] != hashlib.sha256(_canonical(list(QUERY))).hexdigest():
        raise OwnershipError("receipt_query_mismatch")
    _exact_int(receipt["observed_monotonic_ns"], positive=True)
    processes = receipt["processes"]
    if not isinstance(processes, list) or not processes or len(processes) > MAX_PROCESSES:
        raise OwnershipError("receipt_processes_invalid")
    expected_keys = {"nvidia_pid", "proc_pid", "proc_start_ticks", "nspid", "gpu_uuid",
                     "used_memory_mib", "ownership_path"}
    seen: set[tuple[int, str]] = set()
    seen_proc: set[int] = set()
    proof_nodes = 0
    for item in processes:
        if not isinstance(item, dict) or set(item) != expected_keys or item["gpu_uuid"] != expected_gpu_uuid:
            raise OwnershipError("receipt_process_invalid")
        for key in ("nvidia_pid", "proc_pid", "proc_start_ticks"):
            _exact_int(item[key], positive=True)
        _exact_int(item["used_memory_mib"])
        if not isinstance(item["nspid"], list) or any(type(x) is not int or x <= 0 for x in item["nspid"]):
            raise OwnershipError("receipt_nspid_invalid")
        path = item["ownership_path"]
        path_keys = {"pid", "parent_pid", "start_ticks", "nspid"}
        if not isinstance(path, list) or not path or len(path) > MAX_PROCESSES:
            raise OwnershipError("receipt_ancestry_invalid")
        proof_nodes += len(path)
        if proof_nodes > MAX_PROCESSES:
            raise OwnershipError("receipt_ancestry_limit")
        path_pids: set[int] = set()
        for index, node in enumerate(path):
            if not isinstance(node, dict) or set(node) != path_keys:
                raise OwnershipError("receipt_ancestry_invalid")
            for key in ("pid", "start_ticks"):
                _exact_int(node[key], positive=True)
            _exact_int(node["parent_pid"])
            if not isinstance(node["nspid"], list) or any(type(x) is not int or x <= 0 for x in node["nspid"]):
                raise OwnershipError("receipt_ancestry_invalid")
            if node["pid"] in path_pids:
                raise OwnershipError("receipt_ancestry_invalid")
            path_pids.add(node["pid"])
            if index and node["parent_pid"] != path[index - 1]["pid"]:
                raise OwnershipError("receipt_ancestry_invalid")
        if (path[0]["pid"] != root_pid or path[0]["start_ticks"] != root_start_ticks
                or path[-1]["pid"] != item["proc_pid"]
                or path[-1]["start_ticks"] != item["proc_start_ticks"]
                or path[-1]["nspid"] != item["nspid"]):
            raise OwnershipError("receipt_ancestry_invalid")
        if pid_domain == "proc_pid" and item["nvidia_pid"] != item["proc_pid"]:
            raise OwnershipError("receipt_pid_mapping_invalid")
        if pid_domain == "outermost_nspid" and (not item["nspid"] or item["nvidia_pid"] != item["nspid"][0]):
            raise OwnershipError("receipt_pid_mapping_invalid")
        pair = (item["nvidia_pid"], item["gpu_uuid"])
        if pair in seen or item["proc_pid"] in seen_proc:
            raise OwnershipError("receipt_duplicate_process")
        seen.add(pair); seen_proc.add(item["proc_pid"])
    _exact_int(receipt["process_count"], positive=True)
    _exact_int(receipt["total_used_memory_mib"])
    if receipt["process_count"] != len(processes) or receipt["total_used_memory_mib"] != sum(item["used_memory_mib"] for item in processes):
        raise OwnershipError("receipt_aggregate_invalid")
    unsigned = dict(receipt); supplied = unsigned.pop("receipt_sha256")
    if hashlib.sha256(_canonical(unsigned)).hexdigest() != supplied:
        raise OwnershipError("receipt_hash_invalid")
