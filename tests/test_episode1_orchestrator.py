from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from runpod_benchmark.episode1_execution import (
    compile_execution_candidate,
    spend_approval_phrase,
    watchdog_risk_phrase,
)
from runpod_benchmark.episode1 import canonical_json
from runpod_benchmark.episode1_orchestrator import (
    Allocation,
    CreateOutcomeUnknown,
    DeletionAuthority,
    Episode1Orchestrator,
    LifecycleError,
    PrivateEvidenceWriter,
    RuntimeHandle,
)
from test_episode1_execution import inputs, protocol


NOW = datetime(2026, 9, 22, 12, 10, tzinfo=timezone.utc)


class Provider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.deleted = False
        self.deadlines: dict[str, list[float]] = {}

    def _deadline(self, operation, value):
        self.deadlines.setdefault(operation, []).append(value)

    def bind_cleanup_owner(self, callback):
        self.cleanup_owner = callback

    def make_cleanup_observation_binding(self, allocation, **kwargs):
        return SimpleNamespace(allocation=allocation, **kwargs)

    @staticmethod
    def _observation(kind, value, attempt):
        payload = {"kind": kind, "value": value, "delete_attempt": attempt}
        return SimpleNamespace(
            value=value,
            capture_input=payload,
            provider_artifact={"kind": kind, "sha256": "a" * 64},
            raw_bytes=(canonical_json(payload) + "\n").encode(),
        )

    def create_allocation(self, *, unique_name, ownership_token, plan, deadline_monotonic):
        self.calls.append("create")
        allocation = Allocation(
            "private", unique_name, "host", 22022, plan["access"]["ssh_port"], ownership_token,
            plan["allocation"]["gpu"], plan["allocation"]["gpu_count"],
            plan["allocation"]["data_center_id"], plan["allocation"]["cloud_type"],
            plan["allocation"]["container_disk_gb"], plan["allocation"]["volume_gb"],
            plan["allocation"]["volume_mount_path"],
            "registry.example/episode1@" + plan["runtime_builds"][0]["derived_image_digest"],
            "registry.example/episode1@" + plan["runtime_builds"][0]["derived_image_digest"],
            1.0,
        )
        self.cleanup_owner(allocation)
        return allocation

    def recover_exact_name(self, unique_name, *, deadline_monotonic):
        self._deadline("recover", deadline_monotonic)
        self.calls.append("recover")
        return []

    def read_allocation(self, allocation, *, deadline_monotonic):
        self.calls.append("read")
        return allocation

    def current_exposure_fraction(self, allocation, plan, *, deadline_monotonic):
        return 0.01

    def delete_allocation(self, allocation, *, deadline_monotonic):
        self._deadline("delete", deadline_monotonic)
        self.calls.append("delete")
        self.deleted = True
        return True

    def inventory_absent(self, allocation, *, deadline_monotonic):
        self.calls.append("inventory")
        return self.deleted

    def direct_not_found(self, allocation, *, deadline_monotonic):
        self.calls.append("direct")
        return self.deleted

    def delete_allocation_observed(
        self, allocation, *, binding, delete_attempt, deadline_monotonic
    ):
        return self._observation(
            "delete", self.delete_allocation(
                allocation, deadline_monotonic=deadline_monotonic
            ), delete_attempt,
        )

    def inventory_absent_observed(
        self, allocation, *, binding, delete_attempt, deadline_monotonic
    ):
        return self._observation(
            "inventory", self.inventory_absent(
                allocation, deadline_monotonic=deadline_monotonic
            ), delete_attempt,
        )

    def direct_not_found_observed(
        self, allocation, *, binding, delete_attempt, deadline_monotonic
    ):
        return self._observation(
            "direct", self.direct_not_found(
                allocation, deadline_monotonic=deadline_monotonic
            ), delete_attempt,
        )


class Guard:
    def arm(self, binding, *, deadline_monotonic):
        self.binding = binding
        return {"armed": True}

    def healthy(self, binding, *, deadline_monotonic):
        return binding == self.binding


class Runtime:
    def __init__(self) -> None:
        self.starts = 0

    def attest_allocation(self, allocation, plan, *, deadline_monotonic):
        return {
            "gpu_uuid": "gpu", "gpu_pci": "pci", "driver_version": "580",
            "boot_id": "boot", "build_attestation_sha256": "f" * 64,
            "installed_material_sha256": "e" * 64,
            "gpu_count": 1, "gpu_total_memory_mib": 81559,
            "compute_capability": "9.0", "used_memory_mib": 0,
        }

    def start(self, allocation, block, plan, *, deadline_monotonic):
        self.starts += 1
        return RuntimeHandle(str(self.starts), block["runtime"], block["block_id"])

    def wait_ready_and_probe(self, allocation, handle, plan, *, deadline_monotonic):
        return {"exact_tokens": True, "effective_flags": True}

    def stop(self, allocation, handle, *, deadline_monotonic):
        return {"reaped": True}

    def descendants_absent(self, allocation, handle, *, deadline_monotonic):
        return True

    def memory_recovered(self, allocation, baseline, *, deadline_monotonic):
        return True

    def cleanup_failed_start(self, allocation, block, baseline, *, deadline_monotonic):
        return {"descendants_absent": True, "memory_recovered": True}

    def sample_system(
        self, allocation, plan, block, handle, phase, run_id, attempt_id,
        startup_attempt_id, *, deadline_monotonic, slot_kind="periodic",
    ):
        record = {
            "schema_version": "episode1.system-sample.v1", "phase": phase,
            "block_id": block["block_id"], "attempt_id": attempt_id,
            "startup_attempt_id": startup_attempt_id,
            "runtime_bound": handle is not None, "slot_kind": slot_kind,
        }
        return {
            "record": record,
            "source_sha256": hashlib.sha256((canonical_json(record) + "\n").encode()).hexdigest(),
        }


class FailFirstStartRuntime(Runtime):
    def __init__(self) -> None:
        super().__init__()
        self.failed_start_cleanups = 0

    def start(self, allocation, block, plan, *, deadline_monotonic):
        self.starts += 1
        if self.starts == 1:
            raise RuntimeError("start failed before returning a handle")
        return RuntimeHandle(str(self.starts), block["runtime"], block["block_id"])

    def cleanup_failed_start(self, allocation, block, baseline, *, deadline_monotonic):
        self.failed_start_cleanups += 1
        return super().cleanup_failed_start(
            allocation, block, baseline, deadline_monotonic=deadline_monotonic
        )


class Cells:
    def __init__(self) -> None:
        self.calls = []
        self.started = False

    def start(self, *, deadline_monotonic):
        self.started = True

    def close(self, *, deadline_monotonic):
        self.started = False

    def run_cell(self, **kwargs):
        self.calls.append((
            kwargs["block"]["block_id"], kwargs["cell"]["id"], kwargs["warmup"],
            kwargs["evidence_class"],
        ))
        count = kwargs["cell"]["warmups" if kwargs["warmup"] else "requests"]
        return {"scheduled": count, "failed": 0}


class Capture:
    def __init__(self, *, fail_export=False) -> None:
        self.events = []
        self.fail_export = fail_export
        self.export_deadlines = []
        self.telemetry_records = []
        self.contract = SimpleNamespace(
            run_id="run", attempt_id="attempt", plan_sha256="b" * 64,
            hard_deadline_monotonic_ns=10**18,
        )

    def prepare(self, plan, unique_name, ownership_token):
        self.events.append("prepare")

    def owned(self, authority, plan, *, cleanup_deadline_monotonic):
        self.events.append("owned")

    def start(self, allocation, plan, *, cleanup_deadline_monotonic):
        self.events.append("start")

    def boundary(self, event, details):
        self.events.append(event)

    def request(self, value):
        pass

    def request_lifecycle(self, value):
        pass

    def telemetry(self, value):
        self.telemetry_records.append(value)

    def block_start(self, block_id, runtime, **details):
        self.events.append(f"block-start:{block_id}:{runtime}")

    def startup_failed(self, block_id, runtime, **details):
        self.events.append(f"startup-failed:{block_id}:{runtime}")

    def failed_start_cleanup(self, block_id, runtime, **details):
        assert details["descendants_absent"] is True
        assert details["memory_recovered"] is True
        self.events.append(f"failed-start-cleanup:{block_id}:{runtime}")

    def cell_complete(self, block_id, cell_id, *, warmup, **details):
        kind = "warmup" if warmup else "measured"
        self.events.append(f"cell-complete:{block_id}:{cell_id}:{kind}")

    def block_complete(
        self, block_id, runtime, *, descendants_absent, memory_recovered,
        startup_attempt_id_sha256, process_identity_sha256,
    ):
        assert descendants_absent is True
        assert memory_recovered is True
        self.events.append(f"block-complete:{block_id}:{runtime}")

    def export_essential(self, *, deadline_monotonic):
        self.export_deadlines.append(deadline_monotonic)
        if self.fail_export:
            raise OSError("fixture export failure")
        self.events.append("export")

    def deletion_verified(self, **details):
        assert details["acknowledged"] is True
        assert details["inventory_absent"] is True
        assert details["direct_not_found"] is True
        self.events.append("deletion-verified")

    def cleanup_attempt_observed(self, **details):
        status = "error" if details["error_type"] is not None else "response"
        self.events.append(
            f"cleanup-attempt:{details['delete_attempt']}:{details['operation']}:{status}"
        )

    def failed_telemetry_source(self, **details):
        self.events.append(f"failed-telemetry:{details['block_id']}")

    def settlement_observed(self, **details):
        self.events.append(f"settlement:{details['status']}")

    def close(self):
        self.events.append("close")


class Telemetry:
    def __init__(self, run_attempt_id, startup_attempt_id, block_attempt, capture):
        self.run_attempt_id = run_attempt_id
        self.startup_attempt_id = startup_attempt_id
        self.block_attempt = block_attempt
        self.capture = capture

    def start(self, handle, *, deadline_monotonic):
        self.capture.telemetry({"record": {"phase": "startup"}})

    def system_sample(self, value):
        self.capture.telemetry(value)

    def observe_request(self, value, *, warmup):
        pass

    def finish(self, *, deadline_monotonic):
        self.capture.telemetry({"record": {"phase": "drain"}})

    def abort(self, *, deadline_monotonic):
        self.capture.telemetry({"record": {"phase": "drain"}})


def telemetry_factory(plan, block, run_attempt_id, startup_attempt_id, block_attempt,
                      allocation, capture):
    return Telemetry(run_attempt_id, startup_attempt_id, block_attempt, capture)


def approved_plan():
    material_bytes = b"print('bound execution material')\n"
    files = [{"path": "src/example.py", "sha256": hashlib.sha256(material_bytes).hexdigest()}]
    aggregate = hashlib.sha256(canonical_json(files).encode()).hexdigest()
    material = (canonical_json({
        "aggregate_sha256": aggregate,
        "classification": "execution_material_hashes", "files": files,
    }) + "\n").encode()
    values = inputs()
    values["material_sha256"] = aggregate
    plan = compile_execution_candidate(protocol(), values)
    plan_bytes = (canonical_json(plan) + "\n").encode()
    source = (canonical_json({
        "schema_version": "episode1.owner-approval-record.v1",
        "source_channel": "codex_user_message",
        "plan_sha256": plan["plan_sha256"],
        "approved_at": "2026-09-22T12:09:00Z",
        "spend_approval": spend_approval_phrase(plan),
        "watchdog_risk_approval": watchdog_risk_phrase(plan),
    }) + "\n").encode()
    receipt = {
        "schema_version": "episode1.authorization-receipt.v1",
        "plan_sha256": plan["plan_sha256"],
        "plan_file_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "material_file_sha256": hashlib.sha256(material).hexdigest(),
        "material_sha256": aggregate,
        "source_commit": plan["source_commit"],
        "approved_at": "2026-09-22T12:09:00Z",
        "source_kind": "retained_owner_record",
        "source_reference_sha256": hashlib.sha256(source).hexdigest(),
        "spend_approval": spend_approval_phrase(plan),
        "watchdog_risk_approval": watchdog_risk_phrase(plan),
    }
    return plan, receipt, plan_bytes, material, source


def run_args(plan, receipt, plan_bytes, material, source):
    return {
        "plan": plan, "authorization_receipt": receipt,
        "plan_file_bytes": plan_bytes, "material_file_bytes": material,
        "material_files": {"src/example.py": b"print('bound execution material')\n"},
        "observed_source_commit": plan["source_commit"],
        "authorization_source_bytes": source,
        "unique_name": "episode1-candidate-1-run",
    }


def orchestrator(provider, capture, cells=None):
    return Episode1Orchestrator(
        provider=provider, guard=Guard(), runtime=Runtime(), cells=cells or Cells(),
        capture=capture, utc_now=lambda: NOW, monitor_poll_seconds=.01,
        telemetry_factory=telemetry_factory,
    )


class AllocationBoundFactoryTests(unittest.TestCase):
    def test_factories_receive_verified_owned_allocation(self):
        plan, receipt, plan_bytes, material, source = approved_plan()
        provider, capture = Provider(), Capture()
        started = 100.0
        hard = started + float(plan["budget"]["maximum_lifetime_seconds"])
        teardown = started + float(plan["budget"]["maximum_lifetime_seconds"]) * float(
            plan["budget"]["teardown_fraction"]
        )
        capture.contract = SimpleNamespace(
            run_id="run", attempt_id="attempt", plan_sha256=plan["plan_sha256"],
            original_t0_monotonic_ns=int(started * 1_000_000_000),
            hard_deadline_monotonic_ns=int(hard * 1_000_000_000),
            teardown_deadline_monotonic_ns=int(teardown * 1_000_000_000),
        )
        context = SimpleNamespace(
            plan_sha256=plan["plan_sha256"], original_t0_monotonic=started,
            hard_deadline_monotonic=hard, teardown_deadline_monotonic=teardown,
            clock_domain="process-monotonic-domain",
        )
        allocations = []
        runtime = Runtime()
        cells = Cells()

        runner = Episode1Orchestrator(
            provider=provider, guard=Guard(), capture=capture,
            runtime_factory=lambda allocation: allocations.append(("runtime", allocation)) or runtime,
            cell_factory=lambda allocation: allocations.append(("cells", allocation)) or cells,
            monotonic=lambda: 101.0, utc_now=lambda: NOW, monitor_poll_seconds=.01,
            telemetry_factory=telemetry_factory, run_context=context,
        )
        result = runner.run(**run_args(plan, receipt, plan_bytes, material, source))
        self.assertEqual(result["completed_blocks"], 6)
        self.assertEqual([kind for kind, _ in allocations], ["runtime", "cells"])
        self.assertEqual(allocations[0][1], allocations[1][1])
        self.assertIsNotNone(allocations[0][1].resource_identity_sha256)
        self.assertLess(provider.calls.index("read"), provider.calls.index("delete"))


def _case_bad_approval_makes_zero_provider_calls() -> None:
    plan, receipt, plan_bytes, material, source = approved_plan()
    provider = Provider()
    receipt["spend_approval"] = "wrong"
    with unittest.TestCase().assertRaises(ValueError):
        orchestrator(provider, Capture()).run(**run_args(plan, receipt, plan_bytes, material, source))
    assert provider.calls == []


def _case_exact_schedule_runs_and_deletes_once() -> None:
    plan, receipt, plan_bytes, material, source = approved_plan()
    provider, capture, cells = Provider(), Capture(), Cells()
    result = orchestrator(provider, capture, cells).run(
        **run_args(plan, receipt, plan_bytes, material, source)
    )
    assert result == {
        "completed_blocks": 6, "startup_retries": 0, "warmups": 72,
        "measured_requests": 528, "deletion_verified": True,
    }
    assert len(cells.calls) == 36
    assert cells.started is False
    assert {call[3] for call in cells.calls} == {"provider_candidate"}
    assert provider.calls.count("create") == 1
    assert provider.calls.count("delete") == 1
    assert len([event for event in capture.events if event.startswith("block-complete:")]) == 6
    assert len(capture.telemetry_records) >= 12
    assert {item["record"]["phase"] for item in capture.telemetry_records} >= {"prestart", "drain"}


def _case_capture_export_failure_does_not_prevent_verified_deletion() -> None:
    plan, receipt, plan_bytes, material, source = approved_plan()
    provider = Provider()
    with unittest.TestCase().assertRaisesRegex(OSError, "export failure"):
        orchestrator(provider, Capture(fail_export=True)).run(
            **run_args(plan, receipt, plan_bytes, material, source)
        )
    assert provider.deleted is True


def _case_stale_quote_makes_zero_provider_calls() -> None:
    plan, receipt, plan_bytes, material, source = approved_plan()
    provider = Provider()
    runner = Episode1Orchestrator(
        provider=provider, guard=Guard(), runtime=Runtime(), cells=Cells(), capture=Capture(),
        utc_now=lambda: datetime(2026, 9, 22, 14, tzinfo=timezone.utc),
        telemetry_factory=telemetry_factory,
    )
    with unittest.TestCase().assertRaisesRegex(ValueError, "not fresh"):
        runner.run(**run_args(plan, receipt, plan_bytes, material, source))
    assert provider.calls == []


def _case_failed_start_without_handle_is_cleaned_before_retry() -> None:
    plan, receipt, plan_bytes, material, source = approved_plan()
    runtime = FailFirstStartRuntime()
    provider = Provider()
    runner = Episode1Orchestrator(
        provider=provider, guard=Guard(), runtime=runtime, cells=Cells(), capture=Capture(),
        utc_now=lambda: NOW, monitor_poll_seconds=.01,
        telemetry_factory=telemetry_factory,
    )
    result = runner.run(**run_args(plan, receipt, plan_bytes, material, source))
    assert result["startup_retries"] == 1
    assert runtime.failed_start_cleanups == 1
    assert provider.deleted is True


def _case_deletion_proof_cannot_mix_observations_from_different_attempts() -> None:
    class SplitProofProvider(Provider):
        def __init__(self) -> None:
            super().__init__()
            self.proof_attempt = 0

        def inventory_absent(self, allocation, *, deadline_monotonic):
            self.proof_attempt += 1
            if self.proof_attempt == 1:
                return True
            if self.proof_attempt == 2:
                raise TimeoutError("inventory unavailable")
            return False

        def direct_not_found(self, allocation, *, deadline_monotonic):
            return self.proof_attempt >= 2

    plan, receipt, plan_bytes, material, source = approved_plan()
    provider = SplitProofProvider()
    with unittest.TestCase().assertRaisesRegex(LifecycleError, "deletion proof is incomplete"):
        orchestrator(provider, Capture()).run(
            **run_args(plan, receipt, plan_bytes, material, source)
        )
    assert provider.proof_attempt == 3


def _case_deletion_proof_cannot_reuse_an_old_delete_ack() -> None:
    class SplitAckProvider(Provider):
        def __init__(self) -> None:
            super().__init__()
            self.delete_attempt = 0

        def delete_allocation(self, allocation, *, deadline_monotonic):
            self.delete_attempt += 1
            return self.delete_attempt == 1

        def inventory_absent(self, allocation, *, deadline_monotonic):
            return self.delete_attempt >= 2

        def direct_not_found(self, allocation, *, deadline_monotonic):
            return self.delete_attempt >= 2

    plan, receipt, plan_bytes, material, source = approved_plan()
    provider = SplitAckProvider()
    with unittest.TestCase().assertRaisesRegex(LifecycleError, "deletion proof is incomplete"):
        orchestrator(provider, Capture()).run(
            **run_args(plan, receipt, plan_bytes, material, source)
        )
    assert provider.delete_attempt == 3


def _case_readiness_failure_after_create_still_deletes_by_authority() -> None:
    class ReadinessFailureProvider(Provider):
        def create_allocation(self, *, unique_name, ownership_token, plan, deadline_monotonic):
            self.calls.append("create")
            self.cleanup_owner(DeletionAuthority(
                "private", unique_name, ownership_token, 1.0
            ))
            raise LifecycleError("pod failed before readiness")

    plan, receipt, plan_bytes, material, source = approved_plan()
    provider = ReadinessFailureProvider()
    capture = Capture()
    with unittest.TestCase().assertRaisesRegex(LifecycleError, "before readiness"):
        orchestrator(provider, capture).run(
            **run_args(plan, receipt, plan_bytes, material, source)
        )
    assert provider.deleted is True
    assert "owned" in capture.events
    assert provider.calls.count("delete") == 1


def _case_create_recovery_uses_configured_subbudget() -> None:
    class AmbiguousProvider(Provider):
        def create_allocation(self, **kwargs):
            raise CreateOutcomeUnknown("unknown")

    plan, *_ = approved_plan()
    provider = AmbiguousProvider()
    runner = Episode1Orchestrator(
        provider=provider, guard=Guard(), runtime=Runtime(), cells=Cells(),
        capture=Capture(), monotonic=lambda: 100.0,
        telemetry_factory=telemetry_factory,
    )
    with unittest.TestCase().assertRaisesRegex(LifecycleError, "ambiguous create"):
        runner._create_or_recover(plan, "episode1-candidate-1-run", "owner", 999.0)
    assert provider.deadlines["recover"] == [
        100.0 + float(plan["budget"]["create_recovery_seconds"])
    ]


def _case_cleanup_operations_use_configured_subbudgets() -> None:
    class EarlyFailureProvider(Provider):
        def create_allocation(self, *, unique_name, ownership_token, plan, deadline_monotonic):
            allocation = super().create_allocation(
                unique_name=unique_name, ownership_token=ownership_token, plan=plan,
                deadline_monotonic=deadline_monotonic,
            )
            raise LifecycleError("early failure")

    plan, receipt, plan_bytes, material, source = approved_plan()
    provider, capture = EarlyFailureProvider(), Capture()
    runner = Episode1Orchestrator(
        provider=provider, guard=Guard(), runtime=Runtime(), cells=Cells(),
        capture=capture, utc_now=lambda: NOW, monotonic=lambda: 100.0,
        monitor_poll_seconds=.01, telemetry_factory=telemetry_factory,
    )
    with unittest.TestCase().assertRaisesRegex(LifecycleError, "early failure"):
        runner.run(**run_args(plan, receipt, plan_bytes, material, source))
    assert capture.export_deadlines == [
        100.0 + float(plan["budget"]["export_seconds"])
    ]
    assert provider.deadlines["delete"] == [
        100.0 + float(plan["budget"]["delete_verification_seconds"])
    ]


def _case_deletion_proof_requires_literal_booleans_and_live_deadline() -> None:
    class StringProvider(Provider):
        def delete_allocation(self, allocation, *, deadline_monotonic):
            return "true"

        def inventory_absent(self, allocation, *, deadline_monotonic):
            return "true"

        def direct_not_found(self, allocation, *, deadline_monotonic):
            return "true"

    allocation = Allocation(
        "private", "episode1-candidate-1-run", "host", 22022, 22, "owner",
        "NVIDIA H100 80GB HBM3", 1, "US-CA-2", "SECURE", 64, 0, "/workspace",
        "image@sha256:" + "a" * 64, "image@sha256:" + "a" * 64, 1.0,
    )
    runner = orchestrator(StringProvider(), Capture())
    with unittest.TestCase().assertRaisesRegex(LifecycleError, "deletion proof is incomplete"):
        runner._delete_and_verify(allocation, deadline_monotonic=10**12)

    class ExpiringProvider(Provider):
        def __init__(self, clock):
            super().__init__(); self.clock = clock

        def delete_allocation(self, allocation, *, deadline_monotonic):
            self.calls.append("delete"); self.clock[0] = deadline_monotonic
            return True

    clock = [1.0]
    expiring = ExpiringProvider(clock)
    runner = Episode1Orchestrator(
        provider=expiring, guard=Guard(), runtime=Runtime(), cells=Cells(),
        capture=Capture(), monotonic=lambda: clock[0],
        telemetry_factory=telemetry_factory,
    )
    with unittest.TestCase().assertRaisesRegex(LifecycleError, "deletion proof is incomplete"):
        runner._delete_and_verify(allocation, deadline_monotonic=10.0)
    assert expiring.calls == ["delete"]


def _case_request_lifecycle_is_durable_and_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        writer = PrivateEvidenceWriter(Path(directory) / "private")
        base = {
            "schema_version": "episode1.request-lifecycle.v1",
            "request_id": "block-cell-01", "block_id": "block", "cell_id": "cell",
            "scheduled_order": 1, "clock_domain": "client_monotonic_ns",
        }
        writer.request_lifecycle({**base, "stage": "scheduled", "at_ns": 10})
        writer.request_lifecycle({**base, "stage": "dispatched", "at_ns": 11})
        writer.request_lifecycle({**base, "stage": "finalized", "at_ns": 12})
        records = [
            json.loads(line) for line in
            (Path(directory) / "private" / "request-lifecycle.jsonl").read_text().splitlines()
        ]
        assert [item["stage"] for item in records] == [
            "scheduled", "dispatched", "finalized"
        ]
        with unittest.TestCase().assertRaisesRegex(ValueError, "transition"):
            writer.request_lifecycle({**base, "stage": "finalized", "at_ns": 13})

        bad = {**base, "request_id": "bad", "scheduled_order": True,
               "stage": "scheduled", "at_ns": 20}
        with unittest.TestCase().assertRaisesRegex(ValueError, "scheduled order"):
            writer.request_lifecycle(bad)


class OrchestratorUnittestBridge(unittest.TestCase):
    def test_bad_approval(self):
        _case_bad_approval_makes_zero_provider_calls()

    def test_schedule(self):
        _case_exact_schedule_runs_and_deletes_once()

    def test_export_cleanup(self):
        _case_capture_export_failure_does_not_prevent_verified_deletion()

    def test_stale(self):
        _case_stale_quote_makes_zero_provider_calls()

    def test_failed_start_cleanup(self):
        _case_failed_start_without_handle_is_cleaned_before_retry()

    def test_deletion_proof_same_attempt(self):
        _case_deletion_proof_cannot_mix_observations_from_different_attempts()

    def test_deletion_proof_requires_fresh_ack(self):
        _case_deletion_proof_cannot_reuse_an_old_delete_ack()

    def test_readiness_failure_after_create_deletes(self):
        _case_readiness_failure_after_create_still_deletes_by_authority()

    def test_create_recovery_subbudget(self):
        _case_create_recovery_uses_configured_subbudget()

    def test_cleanup_operation_subbudgets(self):
        _case_cleanup_operations_use_configured_subbudgets()

    def test_deletion_proof_types_and_deadline(self):
        _case_deletion_proof_requires_literal_booleans_and_live_deadline()

    def test_request_lifecycle_is_durable_and_closed(self):
        _case_request_lifecycle_is_durable_and_closed()
