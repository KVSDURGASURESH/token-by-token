"""Per-block telemetry assembly for the Episode 1 orchestrator.

This module has no provider or network side effects.  It retains the exact
system-sample stream delivered by RuntimeControl, accepts one injected native
source controller, recomputes every claimed summary, and emits one closed
capture envelope per completed block.
"""
from __future__ import annotations

import hashlib
import math
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .episode1 import canonical_json
from .episode1_capture import _native_source_summary
from .native_sampler import Binding as NativeBinding
from .native_sampler import NativeSampler
from .episode1_orchestrator import Allocation, CaptureControl, LifecycleError, RuntimeHandle
from .source_window import summarize_system_source_window


@dataclass(frozen=True)
class TelemetrySeriesSpec:
    series_id: str
    source_kind: str
    metric_name: str
    kind: str
    labels: Mapping[str, str]

    def checked(self) -> "TelemetrySeriesSpec":
        if not self.series_id or self.source_kind not in {"native", "system_source_window"}:
            raise ValueError("invalid telemetry series identity")
        if not self.metric_name or self.kind not in {"gauge", "counter"}:
            raise ValueError("invalid telemetry metric")
        if not isinstance(self.labels, Mapping) or not all(
            isinstance(key, str) and key and isinstance(value, str)
            for key, value in self.labels.items()
        ):
            raise ValueError("invalid telemetry labels")
        return self


class NativeSourceControl(Protocol):
    def start(self, handle: RuntimeHandle, *, deadline_monotonic: float) -> None: ...
    def finish(
        self, *, first_measured_a_ns: int, last_measured_end_ns: int,
        deadline_monotonic: float,
    ) -> tuple[bytes, Mapping[str, Any]]: ...
    def abort(self, *, deadline_monotonic: float) -> None: ...


class NativeSamplerFactory(Protocol):
    """Construct, but do not start, a sampler for one exact runtime handle."""

    def __call__(
        self, binding: NativeBinding, handle: RuntimeHandle,
    ) -> NativeSampler: ...


class NativeSamplerSource:
    """Bound a NativeSampler lifecycle and return its exact persisted stream."""

    def __init__(
        self, sampler: NativeSampler, *, hard_deadline_ns: int,
        max_sampling_gap_ns: int, monotonic_ns: Callable[[], int],
        maximum_source_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
               for value in (hard_deadline_ns, max_sampling_gap_ns, maximum_source_bytes)):
            raise ValueError("native sampler bounds must be positive integers")
        self.sampler = sampler
        self.hard_deadline_ns = hard_deadline_ns
        self.work_deadline_ns = hard_deadline_ns - sampler.reap_reserve_ns
        self.max_sampling_gap_ns = max_sampling_gap_ns
        self.monotonic_ns = monotonic_ns
        self.maximum_source_bytes = maximum_source_bytes
        self._started = False
        self._stopped = False

    def _deadline_ns(self, deadline_monotonic: float) -> int:
        if (isinstance(deadline_monotonic, bool)
                or not isinstance(deadline_monotonic, (int, float))
                or not math.isfinite(deadline_monotonic)
                or deadline_monotonic <= 0):
            raise LifecycleError("native telemetry deadline is invalid")
        return int(deadline_monotonic * 1_000_000_000)

    def _check_deadline(self, deadline_ns: int) -> None:
        if self.monotonic_ns() >= deadline_ns:
            raise TimeoutError("native telemetry deadline reached")

    def start(self, handle: RuntimeHandle, *, deadline_monotonic: float) -> None:
        if self._started:
            raise LifecycleError("native sampler already started")
        deadline_ns = self._deadline_ns(deadline_monotonic)
        self._check_deadline(deadline_ns)
        now = self.monotonic_ns()
        # Ownership transfers before invoking start: a start implementation may
        # acquire its worker and then raise.  abort() must still call stop().
        self._started = True
        self.sampler.start(start_ns=now, hard_deadline_ns=self.hard_deadline_ns)
        self._check_deadline(deadline_ns)

    def _stop(self, *, deadline_monotonic: float) -> None:
        if not self._started or self._stopped:
            return
        deadline_ns = min(self._deadline_ns(deadline_monotonic), self.work_deadline_ns)
        self._check_deadline(deadline_ns)
        drain = min(self.monotonic_ns(), self.work_deadline_ns)
        self.sampler.stop(drain_ns=drain, join_deadline_ns=deadline_ns)
        self._stopped = True

    def _source(self, *, deadline_monotonic: float) -> bytes:
        deadline_ns = self._deadline_ns(deadline_monotonic)
        output = bytearray()
        expected_sequence = 1
        root = self.sampler.store.directory
        if not isinstance(root, Path):
            root = Path(root)
        if not root.is_absolute() or any(part in {"", ".", ".."} for part in root.parts[1:]):
            raise LifecycleError("native sampler evidence root is not canonical")
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open("/", flags)
        try:
            for component in root.parts[1:]:
                next_fd = os.open(component, flags, dir_fd=root_fd)
                os.close(root_fd)
                root_fd = next_fd
            root_info = os.fstat(root_fd)
            if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.getuid():
                raise LifecycleError("native sampler evidence root is not a private directory")
            for receipt in self.sampler.records:
                self._check_deadline(deadline_ns)
                if receipt.get("sequence") != expected_sequence:
                    raise LifecycleError("native sampler receipts are not contiguous")
                expected_name = f"slot-{expected_sequence:08d}.json"
                expected_path = root / expected_name
                if receipt.get("private_path") != str(expected_path):
                    raise LifecycleError("native sampler receipt path is not canonical")
                flags = (os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
                         | getattr(os, "O_NOFOLLOW", 0))
                descriptor = os.open(expected_name, flags, dir_fd=root_fd)
                try:
                    before = os.fstat(descriptor)
                    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                            or before.st_uid != os.getuid()):
                        raise LifecycleError("native sampler artifact is not a private regular file")
                    chunks: list[bytes] = []
                    remaining = self.maximum_source_bytes + 1 - len(output)
                    while remaining > 0:
                        self._check_deadline(deadline_ns)
                        part = os.read(descriptor, min(65_536, remaining))
                        if not part:
                            break
                        chunks.append(part)
                        remaining -= len(part)
                    chunk = b"".join(chunks)
                    if len(output) + len(chunk) > self.maximum_source_bytes:
                        raise LifecycleError("native sampler source exceeds its retention bound")
                    after = os.fstat(descriptor)
                    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                         before.st_ctime_ns) !=
                        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                         after.st_ctime_ns)):
                        raise LifecycleError("native sampler artifact changed while reading")
                finally:
                    os.close(descriptor)
                if hashlib.sha256(chunk).hexdigest() != receipt.get("file_sha256"):
                    raise LifecycleError("native sampler artifact hash mismatch")
                self._check_deadline(deadline_ns)
                output.extend(chunk)
                expected_sequence += 1
        finally:
            os.close(root_fd)
        if not output:
            raise LifecycleError("native sampler produced no retained source")
        self._check_deadline(deadline_ns)
        return bytes(output)

    def finish(
        self, *, first_measured_a_ns: int, last_measured_end_ns: int,
        deadline_monotonic: float,
    ) -> tuple[bytes, Mapping[str, Any]]:
        self._stop(deadline_monotonic=deadline_monotonic)
        return self._source(deadline_monotonic=deadline_monotonic), {
            "start_monotonic_ns": first_measured_a_ns,
            "end_monotonic_ns": last_measured_end_ns,
            "max_sampling_gap_ns": self.max_sampling_gap_ns,
        }

    def abort(self, *, deadline_monotonic: float) -> None:
        self._stop(deadline_monotonic=deadline_monotonic)


class LazyNativeSamplerSource:
    """Create one PID-bound NativeSampler only after RuntimeControl starts it."""

    def __init__(
        self, factory: NativeSamplerFactory, *, run_id: str, attempt_id: str,
        runtime: str, block: str, clock_domain: str, hard_deadline_ns: int,
        max_sampling_gap_ns: int, monotonic_ns: Callable[[], int],
        maximum_source_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if not callable(factory):
            raise ValueError("native sampler factory must be callable")
        for name, value in {
            "run_id": run_id, "attempt_id": attempt_id, "runtime": runtime,
            "block": block, "clock_domain": clock_domain,
        }.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a nonempty string")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
               for value in (hard_deadline_ns, max_sampling_gap_ns,
                             maximum_source_bytes)):
            raise ValueError("lazy native sampler bounds must be positive integers")
        if not callable(monotonic_ns):
            raise ValueError("monotonic_ns must be callable")
        self.factory = factory
        self.run_id, self.attempt_id = run_id, attempt_id
        self.runtime, self.block = runtime, block
        self.clock_domain = clock_domain
        self.hard_deadline_ns = hard_deadline_ns
        self.max_sampling_gap_ns = max_sampling_gap_ns
        self.monotonic_ns = monotonic_ns
        self.maximum_source_bytes = maximum_source_bytes
        self._source: NativeSamplerSource | None = None
        self._start_attempted = False
        self._started = False
        self._finished = False

    @staticmethod
    def _deadline_ns(deadline_monotonic: float) -> int:
        if (isinstance(deadline_monotonic, bool)
                or not isinstance(deadline_monotonic, (int, float))
                or not math.isfinite(deadline_monotonic)
                or deadline_monotonic <= 0):
            raise LifecycleError("native telemetry deadline is invalid")
        return int(deadline_monotonic * 1_000_000_000)

    def _check_operation_deadline(self, deadline_monotonic: float) -> None:
        deadline_ns = self._deadline_ns(deadline_monotonic)
        if deadline_ns > self.hard_deadline_ns:
            raise LifecycleError("native telemetry deadline exceeds original hard deadline")
        if self.monotonic_ns() >= deadline_ns:
            raise TimeoutError("native telemetry deadline reached")

    def _binding(self, handle: RuntimeHandle) -> NativeBinding:
        if not isinstance(handle, RuntimeHandle):
            raise LifecycleError("native telemetry runtime handle is invalid")
        if handle.runtime != self.runtime or handle.block_id != self.block:
            raise LifecycleError("native telemetry runtime or block mismatch")
        if (not isinstance(handle.private_process_id, str)
                or not handle.private_process_id):
            raise LifecycleError("native telemetry process identity is invalid")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
               for value in (handle.process_pid, handle.process_start_ticks)):
            raise LifecycleError("native telemetry requires an exact process start identity")
        try:
            return NativeBinding(
                run_id=self.run_id,
                attempt_id=self.attempt_id,
                process_identity=f"pid:{handle.process_pid}",
                process_start_identity=f"ticks:{handle.process_start_ticks}",
                runtime=self.runtime,
                block=self.block,
                clock_domain=self.clock_domain,
            )
        except ValueError as exc:
            raise LifecycleError("native telemetry binding is invalid") from exc

    def start(self, handle: RuntimeHandle, *, deadline_monotonic: float) -> None:
        if self._start_attempted or self._finished:
            raise LifecycleError("lazy native sampler cannot be reused")
        self._check_operation_deadline(deadline_monotonic)
        binding = self._binding(handle)
        self._start_attempted = True
        try:
            sampler = self.factory(binding, handle)
        except Exception as exc:
            raise LifecycleError("native sampler factory failed") from exc
        if getattr(sampler, "binding", None) != binding:
            raise LifecycleError("native sampler factory returned a mismatched binding")
        source = NativeSamplerSource(
            sampler,
            hard_deadline_ns=self.hard_deadline_ns,
            max_sampling_gap_ns=self.max_sampling_gap_ns,
            monotonic_ns=self.monotonic_ns,
            maximum_source_bytes=self.maximum_source_bytes,
        )
        self._source = source
        self._check_operation_deadline(deadline_monotonic)
        source.start(handle, deadline_monotonic=deadline_monotonic)
        self._started = True

    def finish(
        self, *, first_measured_a_ns: int, last_measured_end_ns: int,
        deadline_monotonic: float,
    ) -> tuple[bytes, Mapping[str, Any]]:
        if not self._started or self._finished or self._source is None:
            raise LifecycleError("lazy native sampler is not active")
        result = self._source.finish(
            first_measured_a_ns=first_measured_a_ns,
            last_measured_end_ns=last_measured_end_ns,
            deadline_monotonic=deadline_monotonic,
        )
        self._finished = True
        return result

    def abort(self, *, deadline_monotonic: float) -> None:
        if self._finished:
            return
        if self._source is not None:
            self._source.abort(deadline_monotonic=deadline_monotonic)
        self._finished = True


class Episode1BlockTelemetry:
    """Collect and seal both native and remote-system sources for one block."""

    def __init__(
        self, *, plan: Mapping[str, Any], block: Mapping[str, Any],
        run_attempt_id: str, startup_attempt_id: str, block_attempt: int,
        allocation: Allocation, capture: CaptureControl,
        specs: Sequence[TelemetrySeriesSpec], native: NativeSourceControl,
        max_system_sampling_gap_ns: int, native_clock_domain: str,
    ) -> None:
        block_id = block.get("block_id")
        if (not isinstance(run_attempt_id, str) or not run_attempt_id
                or not isinstance(startup_attempt_id, str) or not startup_attempt_id):
            raise ValueError("run and startup attempt ids are required")
        if (isinstance(block_attempt, bool) or not isinstance(block_attempt, int)
                or block_attempt <= 0
                or startup_attempt_id != f"{block_id}-attempt-{block_attempt}"):
            raise ValueError("startup attempt id is not canonical for its block attempt")
        if (isinstance(max_system_sampling_gap_ns, bool)
                or not isinstance(max_system_sampling_gap_ns, int)
                or max_system_sampling_gap_ns <= 0):
            raise ValueError("system sampling gap must be a positive integer")
        checked = tuple(spec.checked() for spec in specs)
        if not checked or len({spec.series_id for spec in checked}) != len(checked):
            raise ValueError("telemetry series must be nonempty and unique")
        if not any(spec.source_kind == "system_source_window" for spec in checked):
            raise ValueError("at least one system source-window series is required")
        self.plan, self.block = plan, block
        self.run_attempt_id = run_attempt_id
        self.startup_attempt_id = startup_attempt_id
        self.block_attempt = block_attempt
        self.allocation = allocation
        self.capture, self.specs, self.native = capture, checked, native
        self.max_system_sampling_gap_ns = max_system_sampling_gap_ns
        if not isinstance(native_clock_domain, str) or not native_clock_domain:
            raise ValueError("native clock domain is required")
        self.native_clock_domain = native_clock_domain
        self._system = bytearray()
        self._start_receipt: Mapping[str, Any] | None = None
        self._end_receipt: Mapping[str, Any] | None = None
        self._handle: RuntimeHandle | None = None
        self._first_a_ns: int | None = None
        self._last_end_ns: int | None = None
        self._finished = False

    def start(self, handle: RuntimeHandle, *, deadline_monotonic: float) -> None:
        if self._handle is not None or handle.process_pid is None or handle.process_start_ticks is None:
            raise LifecycleError("telemetry requires one stable runtime process identity")
        self._handle = handle
        self.native.start(handle, deadline_monotonic=deadline_monotonic)

    def system_sample(self, value: Mapping[str, Any]) -> None:
        if self._finished or not isinstance(value, Mapping):
            raise LifecycleError("system sample arrived outside the block telemetry lifecycle")
        if set(value) not in ({"record", "source_sha256"},
                             {"record", "source_sha256", "boundary_receipt"}):
            raise LifecycleError("system sample response is open or incomplete")
        record = value["record"]
        if not isinstance(record, Mapping):
            raise LifecycleError("system sample record is invalid")
        encoded = (canonical_json(dict(record)) + "\n").encode()
        if hashlib.sha256(encoded).hexdigest() != value["source_sha256"]:
            raise LifecycleError("system sample source hash mismatch")
        if len(self._system) + len(encoded) > 16 * 1024 * 1024:
            raise LifecycleError("system telemetry source exceeds its retention bound")
        self.capture.system_source({
            "schema_version": "episode1.system-source-evidence.v1",
            "plan_sha256": self.plan["plan_sha256"],
            "block_id": self.block["block_id"],
            "runtime": self.block["runtime"],
            "run_attempt_id": self.run_attempt_id,
            "startup_attempt_id": self.startup_attempt_id,
            "block_attempt": self.block_attempt,
            "source_sha256": value["source_sha256"],
            "record": dict(record),
        })
        self._system.extend(encoded)
        receipt = value.get("boundary_receipt")
        if receipt is not None:
            if not isinstance(receipt, Mapping):
                raise LifecycleError("system boundary receipt is invalid")
            marker = receipt.get("marker")
            if marker == "measurement_start" and self._start_receipt is None and self._end_receipt is None:
                self._start_receipt = dict(receipt)
            elif marker == "measurement_end" and self._start_receipt is not None and self._end_receipt is None:
                self._end_receipt = dict(receipt)
            else:
                raise LifecycleError("system measurement boundaries are duplicate or reordered")

    def observe_request(self, value: Mapping[str, Any], *, warmup: bool) -> None:
        if warmup:
            return
        a_ns, end_ns = value.get("a_ns"), value.get("end_ns")
        if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0
               for item in (a_ns, end_ns)) or end_ns < a_ns:
            raise LifecycleError("measured request has invalid telemetry timestamps")
        self._first_a_ns = a_ns if self._first_a_ns is None else min(self._first_a_ns, a_ns)
        self._last_end_ns = end_ns if self._last_end_ns is None else max(self._last_end_ns, end_ns)

    @staticmethod
    def _series(spec: TelemetrySeriesSpec, derived: Mapping[str, Any], *,
                source: bytes, window: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "series_id": spec.series_id, "source_kind": spec.source_kind,
            "metric_name": spec.metric_name, "kind": spec.kind,
            "status": derived["status"], "value": derived["value"],
            "unavailable_reason": derived["unavailable_reason"],
            "expected_samples": derived["expected_samples"],
            "observed_samples": derived["observed_samples"],
            "missing_samples": derived["missing_samples"],
            "labels": dict(spec.labels), "window": dict(window), "source_bytes": source,
        }

    def finish(self, *, deadline_monotonic: float) -> None:
        if self._finished:
            raise LifecycleError("block telemetry already finished")
        if (self._handle is None or self._start_receipt is None or self._end_receipt is None
                or self._first_a_ns is None or self._last_end_ns is None):
            raise LifecycleError("block telemetry lacks its closed measurement window")
        native_source, native_window = self.native.finish(
            first_measured_a_ns=self._first_a_ns,
            last_measured_end_ns=self._last_end_ns,
            deadline_monotonic=deadline_monotonic,
        )
        system_source = bytes(self._system)
        system_window = {
            "start_receipt": dict(self._start_receipt),
            "end_receipt": dict(self._end_receipt),
            "pid": self._handle.process_pid,
            "start_ticks": self._handle.process_start_ticks,
            "max_sampling_gap_ns": self.max_system_sampling_gap_ns,
            "first_measured_a_ns": self._first_a_ns,
            "last_measured_end_ns": self._last_end_ns,
        }
        output = []
        for spec in self.specs:
            if spec.source_kind == "system_source_window":
                derived = summarize_system_source_window(
                    source=system_source, start_receipt=self._start_receipt,
                    end_receipt=self._end_receipt, plan_sha256=self.plan["plan_sha256"],
                    run_id=self.capture.contract.run_id, attempt_id=self.run_attempt_id,
                    block=str(self.block["block_id"]), runtime=str(self.block["runtime"]),
                    pid=self._handle.process_pid, start_ticks=self._handle.process_start_ticks,
                    metric_name=spec.metric_name, kind=spec.kind, labels=spec.labels,
                    max_sampling_gap_ns=self.max_system_sampling_gap_ns,
                    first_measured_a_ns=self._first_a_ns,
                    last_measured_end_ns=self._last_end_ns,
                )
                output.append(self._series(spec, derived, source=system_source, window=system_window))
            else:
                derived, _digest = _native_source_summary(
                    native_source, run_id=self.capture.contract.run_id,
                    attempt_id=self.run_attempt_id, block=str(self.block["block_id"]),
                    runtime=str(self.block["runtime"]), clock_domain=self.native_clock_domain,
                    metric_name=spec.metric_name, kind=spec.kind, labels=spec.labels,
                    window=native_window,
                )
                output.append(self._series(spec, derived, source=native_source, window=native_window))
        self.capture.telemetry({
            "plan_sha256": self.plan["plan_sha256"],
            "block_id": self.block["block_id"], "runtime": self.block["runtime"],
            "series": output,
        })
        self._finished = True

    def abort(self, *, deadline_monotonic: float) -> None:
        if self._finished:
            return
        # Persist the in-memory stream before native teardown: native abort may
        # itself time out, and process exit must not erase observed samples.
        self.capture.failed_telemetry_source(
            block_id=str(self.block["block_id"]),runtime=str(self.block["runtime"]),
            source_kind="system_source_window",source_bytes=bytes(self._system),
            reason="block_abort",
        )
        self.native.abort(deadline_monotonic=deadline_monotonic)
        self._finished = True
