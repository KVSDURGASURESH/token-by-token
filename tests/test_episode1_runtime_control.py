from __future__ import annotations

import copy
import hashlib
import time
import unittest

from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_execution import compile_execution_candidate
from runpod_benchmark.episode1_orchestrator import Allocation, LifecycleError, RuntimeHandle
from runpod_benchmark.episode1_runtime_control import SshRuntimeControl, _argv_sha256
from runpod_benchmark import gpu_process_ownership as gpu_ownership
from test_episode1_execution import inputs, protocol


DIGEST = "a" * 64


class FakeExecutor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run_json(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[-1] == "clock":
            return {
                "schema_version": "episode1.remote-clock.v1",
                "remote_monotonic": time.monotonic(),
                "remote_wall_time_ns": time.time_ns(),
            }
        return self.responses.pop(0)


def allocation():
    return Allocation(
        "pod-1", "episode1-candidate-1-run", "192.0.2.1", 31022, 22,
        "owner", "NVIDIA H100 80GB HBM3", 1, "US-TEST-1", "SECURE",
        120, 0, "", "registry.example/episode1@sha256:" + "b" * 64,
        "registry.example/episode1@sha256:" + "b" * 64, 1.0,
    )


def attestation():
    installed = [
        {key: item[key] for key in (
            "runtime", "build_spec_sha256", "dependency_lock_sha256", "launcher_sha256",
        )}
        for item in compile_execution_candidate(protocol(), inputs())["runtime_builds"]
    ]
    return {
        "schema_version": "episode1.remote-attestation.v1",
        "gpu_uuid": "GPU-fixture", "gpu_pci": "0000:01:00.0",
        "gpu_name": "NVIDIA H100 80GB HBM3", "driver_version": "580.65.06",
        "boot_id": "boot-fixture", "cuda_runtime_version": "13.0",
        "nvrtc_version": "13.0.88",
        "gpu_count": 1, "gpu_total_memory_mib": 81559,
        "compute_capability": "9.0", "used_memory_mib": 0,
        "compute_process_count": 0,
        "build_attestation_sha256": DIGEST,
        "installed_runtime_builds": installed,
        "installed_material_sha256": hashlib.sha256(canonical_json(
            sorted(installed, key=lambda item: item["runtime"])
        ).encode()).hexdigest(),
        "gpu_process_pid_domain": "proc_pid",
    }


def ownership_receipt():
    def stat(pid, parent, start):
        return (f"{pid} (worker) " + " ".join(
            ["S", str(parent)] + ["0"] * 17 + [str(start)]
        )).encode()

    class Proc:
        def pids(self, deadline_ns, monotonic_ns):
            return [10, 11]

        def read(self, path, max_bytes, deadline_ns, monotonic_ns):
            _proc, pid, kind = path.split("/")[1:]
            values = {
                10: {"stat": stat(10, 1, 100), "status": b"NSpid:\t10\n"},
                11: {"stat": stat(11, 10, 110), "status": b"NSpid:\t11\n"},
            }
            return values[int(pid)][kind]

    return gpu_ownership.collect(
        root_pid=10, root_start_ticks=100, expected_gpu_uuid="GPU-fixture",
        pid_domain="proc_pid",
        runner=lambda argv, deadline: gpu_ownership.CommandResult(
            "ok", b"11, GPU-fixture, 123\n", None
        ),
        proc=Proc(), deadline_monotonic_ns=1000,
        monotonic_ns=lambda: 100,
    )


class RuntimeControlTests(unittest.TestCase):
    def setUp(self):
        self.plan = compile_execution_candidate(protocol(), inputs())
        self.block = self.plan["blocks"][0]

    def test_attestation_accepts_only_frozen_nvrtc_h100_path(self):
        executor = FakeExecutor([attestation()])
        result = SshRuntimeControl(executor).attest_allocation(
            allocation(), self.plan, deadline_monotonic=time.monotonic() + 1
        )
        self.assertEqual(result["installed_runtime_builds"][0]["build_spec_sha256"], DIGEST)
        self.assertEqual(executor.calls[1][0], ["/usr/local/bin/episode1-control", "attest"])

    def test_attestation_rejects_cutile_cuda_drift_and_provider_gpu_mismatch(self):
        for key, value, message in (
            ("cuda_runtime_version", "13.1", "CUDA runtime"),
            ("gpu_name", "NVIDIA A100-SXM4-80GB", "provider readback"),
        ):
            evidence = copy.deepcopy(attestation())
            evidence[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(LifecycleError, message):
                SshRuntimeControl(FakeExecutor([evidence])).attest_allocation(
                    allocation(), self.plan, deadline_monotonic=time.monotonic() + 1
                )

        evidence = copy.deepcopy(attestation())
        evidence["installed_runtime_builds"][0]["launcher_sha256"] = "c" * 64
        with self.assertRaisesRegex(LifecycleError, "installed build material"):
            SshRuntimeControl(FakeExecutor([evidence])).attest_allocation(
                allocation(), self.plan, deadline_monotonic=time.monotonic() + 1
            )

    def test_attestation_rejects_arbitrary_valid_build_attestation_digest(self):
        evidence = copy.deepcopy(attestation())
        evidence["build_attestation_sha256"] = "c" * 64
        with self.assertRaisesRegex(LifecycleError, "approved image evidence"):
            SshRuntimeControl(FakeExecutor([evidence])).attest_allocation(
                allocation(), self.plan, deadline_monotonic=time.monotonic() + 1
            )

    def test_probe_rejects_arbitrary_valid_effective_configuration_digest(self):
        response = {
            "schema_version": "episode1.remote-probe.v1",
            "private_process_id": "pid-1",
            "exact_tokens": True,
            "effective_flags": True,
            "loopback_only": True,
            "probe_sha256": DIGEST,
            "token_evidence_sha256": DIGEST,
            "effective_config_sha256": "c" * 64,
            "argv_sha256": _argv_sha256(self.block["runtime"]),
            "gpu_process_ownership": {},
        }
        handle = RuntimeHandle("pid-1", self.block["runtime"], self.block["block_id"])
        with self.assertRaisesRegex(LifecycleError, "effective runtime configuration"):
            SshRuntimeControl(FakeExecutor([response])).wait_ready_and_probe(
                allocation(), handle, self.plan,
                deadline_monotonic=time.monotonic() + 1,
            )

    def test_start_probe_stop_and_cleanup_are_closed_and_bound(self):
        responses = [
            attestation(),
            {"schema_version": "episode1.remote-start.v1", "private_process_id": "pid-1",
             "runtime": self.block["runtime"], "block_id": self.block["block_id"],
             "process_pid": 10, "process_start_ticks": 100,
             "argv_sha256": _argv_sha256(self.block["runtime"]), "started_monotonic_ns": 1,
             "kernel_path": "native_runtime", "kernel_evidence_sha256": None,
             "kernel_unavailable_reason": "humming_not_selected_by_frozen_runtime_path"},
            {"schema_version": "episode1.remote-probe.v1", "private_process_id": "pid-1",
             "exact_tokens": True, "effective_flags": True, "loopback_only": True,
             "probe_sha256": DIGEST, "token_evidence_sha256": DIGEST,
             "effective_config_sha256": _argv_sha256(self.block["runtime"]),
             "argv_sha256": _argv_sha256(self.block["runtime"]),
             "gpu_process_ownership": ownership_receipt()},
            {"schema_version": "episode1.remote-stop.v1", "private_process_id": "pid-1",
             "reaped": True, "endpoint_closed": True, "sigkill_used": False},
            {"schema_version": "episode1.remote-status.v1", "private_process_id": "pid-1",
             "descendants_absent": True, "endpoint_closed": True},
            {"schema_version": "episode1.remote-memory.v1",
             "gpu_uuid": "GPU-fixture", "used_memory_mib": 0,
             "compute_process_count": 0},
            {"schema_version": "episode1.remote-cleanup.v1", "descendants_absent": True,
             "endpoint_closed": True, "gpu_uuid": "GPU-fixture",
             "used_memory_mib": 0, "compute_process_count": 0},
        ]
        control = SshRuntimeControl(FakeExecutor(responses))
        deadline = time.monotonic() + 1
        control.attest_allocation(allocation(), self.plan, deadline_monotonic=deadline)
        handle = control.start(allocation(), self.block, self.plan, deadline_monotonic=deadline)
        self.assertEqual(handle, RuntimeHandle(
            "pid-1", self.block["runtime"], self.block["block_id"], 10, 100
        ))
        self.assertTrue(control.wait_ready_and_probe(allocation(), handle, self.plan, deadline_monotonic=deadline)["exact_tokens"])
        self.assertTrue(control.stop(allocation(), handle, deadline_monotonic=deadline)["reaped"])
        self.assertTrue(control.descendants_absent(allocation(), handle, deadline_monotonic=deadline))
        baseline = {"gpu_uuid": "GPU-fixture", "used_memory_mib": 0}
        self.assertTrue(control.memory_recovered(allocation(), baseline, deadline_monotonic=deadline))
        self.assertTrue(control.cleanup_failed_start(allocation(), self.block, baseline, deadline_monotonic=deadline)["memory_recovered"])

    def test_identity_probe_reobserves_and_binds_pid_start_and_listener(self):
        handle = RuntimeHandle(
            "pid-1", self.block["runtime"], self.block["block_id"], 10, 100
        )
        response = {
            "schema_version": "episode1.remote-identity.v1",
            "private_process_id": "pid-1",
            "process_pid": 10,
            "process_start_ticks": 100,
            "loopback_listener_owned": True,
        }
        executor = FakeExecutor([response])
        control = SshRuntimeControl(executor)
        self.assertEqual(
            control.observe_process_identity(
                handle, deadline_monotonic=time.monotonic() + 1
            ),
            ("pid:10", "ticks:100"),
        )
        payload = executor.calls[-1][1]["input_value"]
        self.assertEqual(payload["schema_version"], "episode1.remote-identity-request.v1")
        self.assertEqual(payload["handle"], handle.__dict__)

        for key, value in (
            ("process_start_ticks", 101),
            ("loopback_listener_owned", False),
        ):
            bad = dict(response)
            bad[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                LifecycleError, "identity changed"
            ):
                SshRuntimeControl(FakeExecutor([bad])).observe_process_identity(
                    handle, deadline_monotonic=time.monotonic() + 1
                )

    def test_system_sample_is_hash_bound_to_exact_canonical_source(self):
        record = {
            "schema_version": "episode1.system-sample.v1",
            "binding": {"run_id": "capture-run", "attempt_id": "attempt-1",
                        "block": self.block["block_id"], "clock_domain": "linux-clock-monotonic",
                        "source_boot_id": "boot-fixture"},
            "sequence": 1, "slot_kind": "periodic",
        }
        source_sha256 = hashlib.sha256((canonical_json(record) + "\n").encode()).hexdigest()
        executor = FakeExecutor([{
            "schema_version": "episode1.remote-sample.v1",
            "record": record,
            "source_sha256": source_sha256,
        }])
        control = SshRuntimeControl(executor)
        control._attested_boot_id = "boot-fixture"
        value = control.sample_system(
            allocation(), self.plan, self.block, None, "prestart", "capture-run", "attempt-1",
            f"{self.block['block_id']}-attempt-1",
            deadline_monotonic=time.monotonic() + 1,
        )
        self.assertEqual(value["source_sha256"], source_sha256)
        payload = executor.calls[-1][1]["input_value"]
        self.assertIsNone(payload["handle"])
        self.assertEqual(payload["phase"], "prestart")
        self.assertEqual(payload["startup_attempt_id"], f"{self.block['block_id']}-attempt-1")

        bad = FakeExecutor([{
            "schema_version": "episode1.remote-sample.v1",
            "record": record,
            "source_sha256": "f" * 64,
        }])
        bad_control = SshRuntimeControl(bad)
        bad_control._attested_boot_id = "boot-fixture"
        with self.assertRaisesRegex(LifecycleError, "source hash"):
            bad_control.sample_system(
                allocation(), self.plan, self.block, None, "prestart", "capture-run", "attempt-1",
                f"{self.block['block_id']}-attempt-1",
                deadline_monotonic=time.monotonic() + 1,
            )

    def test_open_or_mismatched_responses_fail_closed(self):
        evidence = attestation()
        evidence["extra"] = True
        with self.assertRaisesRegex(LifecycleError, "open or incomplete"):
            SshRuntimeControl(FakeExecutor([evidence])).attest_allocation(
                allocation(), self.plan, deadline_monotonic=time.monotonic() + 1
            )
        bad = {"schema_version": "episode1.remote-start.v1", "private_process_id": "pid-1",
               "runtime": self.block["runtime"], "block_id": "wrong", "argv_sha256": DIGEST,
               "process_pid": 10, "process_start_ticks": 100,
               "started_monotonic_ns": 1, "kernel_path": "native_runtime",
               "kernel_evidence_sha256": None,
               "kernel_unavailable_reason": "humming_not_selected_by_frozen_runtime_path"}
        with self.assertRaisesRegex(LifecycleError, "bind the requested block"):
            SshRuntimeControl(FakeExecutor([bad])).start(
                allocation(), self.block, self.plan, deadline_monotonic=time.monotonic() + 1
            )

    def test_long_caller_deadline_is_mapped_to_same_bounded_remote_interval(self):
        executor = FakeExecutor([attestation()])
        started = time.monotonic()
        SshRuntimeControl(executor).attest_allocation(
            allocation(), self.plan, deadline_monotonic=started + 240
        )
        remote_call = executor.calls[-1][1]
        payload = remote_call["input_value"]
        self.assertLessEqual(payload["operation_timeout_seconds"], 30)
        self.assertLessEqual(payload["operation_deadline_monotonic"] - time.monotonic(), 30.1)
        self.assertGreater(payload["operation_deadline_monotonic"], time.monotonic())


if __name__ == "__main__":
    unittest.main()
