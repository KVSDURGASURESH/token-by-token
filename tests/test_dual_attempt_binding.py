from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_capture import (
    EvidenceCaptureV2,
    IntegrityError,
    RunContract,
    _read_stream,
    _verify_system_source_startup_attempts,
    _verify_telemetry_sources,
    load_retained_system_sources,
)
from runpod_benchmark.episode1_orchestrator import Allocation, RuntimeHandle
from runpod_benchmark.episode1_telemetry import Episode1BlockTelemetry, TelemetrySeriesSpec

PLAN_SHA = "a" * 64
RUN_ID = "run-1"
RUN_ATTEMPT = "attempt-1"
BLOCK = {"block_id": "block-1", "runtime": "vllm"}
BOOT = "11111111-2222-3333-4444-555555555555"
LABELS = {"source": "proc", "unit": "bytes", "scope": "process"}


class Clock:
    def __init__(self): self.value = 10
    def mono(self): self.value += 1; return self.value
    def utc(self): return 1_000 + self.value


def make_contract() -> RunContract:
    counts = {}
    for index in range(1, 7):
        for warmup, count in ((True, 12), (False, 88)):
            counts[f"block-{index}|cell|{int(warmup)}"] = count
    blocks = tuple((f"block-{index}", "vllm" if index % 2 else "sglang")
                   for index in range(1, 7))
    return RunContract(RUN_ID, RUN_ATTEMPT, PLAN_SHA, "b" * 64, "c" * 64,
                       blocks, counts, ("sys",), 10, 20, 1_000_000, 900_000,
                       "clock", "boot")


class Native:
    def start(self, handle, *, deadline_monotonic): pass
    def abort(self, *, deadline_monotonic): pass
    def finish(self, *, first_measured_a_ns, last_measured_end_ns, deadline_monotonic):
        return b"unused-native-source", {
            "start_monotonic_ns": first_measured_a_ns,
            "end_monotonic_ns": last_measured_end_ns,
            "max_sampling_gap_ns": 200,
        }


def telemetry(capture, startup: int) -> Episode1BlockTelemetry:
    # Deliberately distinct: the provider allocation name is not the capture run id.
    allocation = Allocation("pod", "episode1-candidate-random", "host", 22022, 22,
                            "x" * 64, "H100", 1, "dc", "SECURE", 64, 0,
                            "/workspace", "image", "image", 1.0)
    return Episode1BlockTelemetry(
        plan={"plan_sha256": PLAN_SHA}, block=BLOCK,
        run_attempt_id=RUN_ATTEMPT,
        startup_attempt_id=f"block-1-attempt-{startup}", block_attempt=startup,
        allocation=allocation, capture=capture,
        specs=(TelemetrySeriesSpec("sys", "system_source_window", "rss_bytes",
                                   "gauge", LABELS),),
        native=Native(), max_system_sampling_gap_ns=200,
        native_clock_domain="clock",
    )


def record(sequence: int, slot: str, phase: str, observed: int, *, pid=77):
    target = None if pid is None else {"pid": pid, "start_ticks": 9, "role": "vllm"}
    identity = None if pid is None else [pid, 9]
    return {
        "schema_version": "episode1.system-sample.v1",
        "binding": {"run_id": RUN_ID, "attempt_id": RUN_ATTEMPT,
                    "block": "block-1", "clock_domain": "linux-clock-monotonic",
                    "source_boot_id": BOOT},
        "sequence": sequence, "phase": phase, "slot_kind": slot,
        "scheduled_monotonic_ns": observed - 20,
        "sample_start_monotonic_ns": observed - 10,
        "observed_monotonic_ns": observed, "observed_utc_ns": 100_000 + observed,
        "clock_uncertainty_ns": 2, "schedule_lag_ns": 10, "missed_slots": 0,
        "observed_gap_ns": None if sequence == 1 else 100,
        "process_expected": target, "process_identity_before": identity,
        "process_identity_after": identity,
        "process_identity_status": "prestart" if pid is None else "ok",
        "metrics": [{"source": "proc", "name": "rss_bytes", "unit": "bytes",
                     "scope": "process", "value": float(sequence), "status": "ok",
                     "reason": None}],
    }


def sample(row, *, marker=None, client=(0, 0)):
    encoded = (canonical_json(row) + "\n").encode()
    value = {"record": row, "source_sha256": hashlib.sha256(encoded).hexdigest()}
    if marker is not None:
        value["boundary_receipt"] = {
            "schema_version": "episode1.system-window-boundary.v1",
            "plan_sha256": PLAN_SHA, "run_id": RUN_ID, "attempt_id": RUN_ATTEMPT,
            "block": "block-1", "runtime": "vllm", "marker": marker,
            "source_clock_domain": "linux-clock-monotonic", "source_boot_id": BOOT,
            "source_sequence": row["sequence"], "source_record_sha256": value["source_sha256"],
            "source_observed_monotonic_ns": row["observed_monotonic_ns"],
            "source_observed_utc_ns": row["observed_utc_ns"],
            "source_utc_uncertainty_ns": row["clock_uncertainty_ns"],
            "client_clock_domain": "client_monotonic_ns",
            "client_call_started_monotonic_ns": client[0],
            "client_call_completed_monotonic_ns": client[1],
        }
    return value


class DualAttemptBindingTests(unittest.TestCase):
    def test_failed_prestart_then_success_keeps_startups_distinct_and_raw_run_bound(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            contract = make_contract(); clock = Clock()
            capture = EvidenceCaptureV2(Path(temporary) / "evidence", contract,
                monotonic_ns=clock.mono, utc_ns=clock.utc,
                observation_validator=lambda value: value)

            first = telemetry(capture, 1)
            first.system_sample(sample(record(1, "periodic", "prestart", 100, pid=None)))
            first.abort(deadline_monotonic=1.0)

            second = telemetry(capture, 2)
            second.start(RuntimeHandle("process", "vllm", "block-1", 77, 9),
                         deadline_monotonic=1.0)
            second.system_sample(sample(record(1, "measurement_start_boundary", "measurement", 200),
                                        marker="measurement_start", client=(1_000, 1_100)))
            second.system_sample(sample(record(2, "periodic", "measurement", 300)))
            second.system_sample(sample(record(3, "measurement_end_boundary", "measurement", 400),
                                        marker="measurement_end", client=(4_900, 5_000)))
            second.observe_request({"a_ns": 1_200, "end_ns": 4_800}, warmup=False)
            second.finish(deadline_monotonic=1.0)

            retained = load_retained_system_sources(capture.directory, contract)
            self.assertEqual({item["startup_attempt_id"] for item in retained},
                             {"block-1-attempt-1", "block-1-attempt-2"})
            self.assertEqual({item["run_attempt_id"] for item in retained}, {RUN_ATTEMPT})
            self.assertEqual({item["record"]["binding"]["run_id"] for item in retained}, {RUN_ID})
            self.assertNotEqual(RUN_ID, second.allocation.unique_name)

            promoted, _ = _read_stream(capture.directory / "telemetry.jsonl",
                                       "episode1.telemetry-stream.v2")
            _verify_telemetry_sources(capture.directory, promoted)
            self.assertEqual(len(promoted), 1)

    def test_startup_hash_crosscheck_accepts_both_terminal_outcomes_and_rejects_tamper(self):
        values = [
            {"block_id": "block-1", "runtime": "vllm", "block_attempt": number,
             "startup_attempt_id": f"block-1-attempt-{number}"}
            for number in (1, 2)
        ]
        ledger = []
        for number, event in ((1, "startup-failed"), (2, "block-start")):
            startup = f"block-1-attempt-{number}"
            ledger.append(({"event": event}, {"block_id": "block-1", "runtime": "vllm",
                "block_attempt": number,
                "startup_attempt_id_sha256": hashlib.sha256(startup.encode()).hexdigest()}))
        _verify_system_source_startup_attempts(values, ledger)
        ledger[0][1]["startup_attempt_id_sha256"] = "0" * 64
        with self.assertRaisesRegex(IntegrityError, "hash mismatch"):
            _verify_system_source_startup_attempts(values, ledger)

    def test_constructor_rejects_noncanonical_or_boolean_block_attempt(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            contract = make_contract(); clock = Clock()
            capture = EvidenceCaptureV2(Path(temporary) / "evidence", contract,
                monotonic_ns=clock.mono, utc_ns=clock.utc,
                observation_validator=lambda value: value)
            for startup, number in (("block-1-attempt-2", 1), ("block-1-attempt-1", True)):
                with self.subTest(startup=startup, number=number), self.assertRaises(ValueError):
                    Episode1BlockTelemetry(
                        plan={"plan_sha256": PLAN_SHA}, block=BLOCK,
                        run_attempt_id=RUN_ATTEMPT, startup_attempt_id=startup,
                        block_attempt=number, allocation=SimpleNamespace(unique_name="unrelated"),
                        capture=capture,
                        specs=(TelemetrySeriesSpec("sys", "system_source_window", "rss_bytes",
                                                   "gauge", LABELS),),
                        native=Native(), max_system_sampling_gap_ns=200,
                        native_clock_domain="clock")


if __name__ == "__main__": unittest.main()
