from __future__ import annotations

import time
import unittest
from unittest import mock

from runpod_benchmark.episode1_remote_control import RemoteControlError, RemoteControlService


DIGEST = "a" * 64


class _Sampler:
    instances = []

    def __init__(self, binding, nvidia, proc):
        self.binding = binding
        self.sequence = 0
        self.__class__.instances.append(self)

    def sample_periodic(self, target, phase, *, hard_deadline_ns):
        self.sequence += 1
        return {
            "schema_version": "episode1.system-sample.v1",
            "binding": self.binding.__dict__,
            "sequence": self.sequence,
            "phase": phase,
            "target": None,
        }


class StartupRetrySamplingTest(unittest.TestCase):
    def setUp(self):
        _Sampler.instances.clear()
        self.service = RemoteControlService(object(), object(), expected_plan_sha256=DIGEST)
        self.service.gpu_uuid = "GPU-fixture"
        self.service.source_boot_id = "boot-fixture"

    def _request(self, attempt: int, block: str = "block-01"):
        return {
            "schema_version": "episode1.remote-sample-request.v1",
            "plan_sha256": DIGEST,
            "binding": {
                "run_id": "run-1",
                "attempt_id": "run-attempt-1",
                "block": block,
                "clock_domain": "linux-clock-monotonic",
                "source_boot_id": "boot-fixture",
            },
            "startup_attempt_id": f"{block}-attempt-{attempt}",
            "phase": "prestart",
            "slot_kind": "periodic",
            "handle": None,
            "operation_timeout_seconds": 1.0,
            "operation_deadline_monotonic": time.monotonic() + 1.0,
        }

    @mock.patch(
        "runpod_benchmark.episode1_remote_control.bounded_read",
        return_value=b"boot-fixture\n",
    )
    @mock.patch("runpod_benchmark.episode1_remote_control.ProcAdapter", return_value=object())
    @mock.patch("runpod_benchmark.episode1_remote_control.NvidiaSmiAdapter", return_value=object())
    @mock.patch("runpod_benchmark.episode1_remote_control.SystemSampler", _Sampler)
    def test_new_startup_attempt_resets_sequence_without_changing_run_attempt(
        self, _nvidia, _proc, _read
    ):
        first = self.service.dispatch("sample", self._request(1))
        second = self.service.dispatch("sample", self._request(1))
        retried = self.service.dispatch("sample", self._request(2))
        self.assertEqual([first["record"]["sequence"], second["record"]["sequence"]], [1, 2])
        self.assertEqual(retried["record"]["sequence"], 1)
        self.assertEqual(len(_Sampler.instances), 2)
        self.assertEqual(
            retried["record"]["binding"]["attempt_id"], "run-attempt-1"
        )

    @mock.patch(
        "runpod_benchmark.episode1_remote_control.bounded_read",
        return_value=b"boot-fixture\n",
    )
    @mock.patch("runpod_benchmark.episode1_remote_control.ProcAdapter", return_value=object())
    @mock.patch("runpod_benchmark.episode1_remote_control.NvidiaSmiAdapter", return_value=object())
    @mock.patch("runpod_benchmark.episode1_remote_control.SystemSampler", _Sampler)
    def test_attempt_transition_is_strict_and_ordered(self, _nvidia, _proc, _read):
        skipped = self._request(2)
        with self.assertRaisesRegex(RemoteControlError, "skipped"):
            self.service.dispatch("sample", skipped)
        self.service.dispatch("sample", self._request(1))
        self.service.dispatch("sample", self._request(2))
        with self.assertRaisesRegex(RemoteControlError, "duplicate or reordered"):
            self.service.dispatch("sample", self._request(1))
        malformed = self._request(2)
        malformed["startup_attempt_id"] = "block-01-attempt-02"
        with self.assertRaisesRegex(RemoteControlError, "identity is invalid"):
            self.service.dispatch("sample", malformed)

    @mock.patch(
        "runpod_benchmark.episode1_remote_control.bounded_read",
        return_value=b"boot-fixture\n",
    )
    @mock.patch("runpod_benchmark.episode1_remote_control.ProcAdapter", return_value=object())
    @mock.patch("runpod_benchmark.episode1_remote_control.NvidiaSmiAdapter", return_value=object())
    @mock.patch("runpod_benchmark.episode1_remote_control.SystemSampler", _Sampler)
    def test_retired_block_cannot_reenter_and_restart_sequence(self, _nvidia, _proc, _read):
        self.service.dispatch("sample", self._request(1, "block-01"))
        self.service.dispatch("sample", self._request(1, "block-02"))
        with self.assertRaisesRegex(RemoteControlError, "already retired"):
            self.service.dispatch("sample", self._request(1, "block-01"))


if __name__ == "__main__":
    unittest.main()
