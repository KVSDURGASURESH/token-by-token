from __future__ import annotations

import copy
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from runpod_benchmark.episode1 import authored_quality_corpus
from runpod_benchmark.episode1_application import RunContext, execute_episode1
from runpod_benchmark.episode1_capture import EvidenceCaptureV2
from runpod_benchmark.episode1_promotion import digest, promote_private_evidence
from runpod_benchmark.episode1_telemetry import Episode1BlockTelemetry, TelemetrySeriesSpec
from test_episode1_orchestration_loopback import _RotatingProductionCells
from test_episode1_orchestrator import Guard, NOW, approved_plan
from test_episode1_promotion import make_bundle
from test_episode1_real_orchestration_capture_promotion import _NativeSource, _Provider, _Runtime


class _ReadinessFailures(_Runtime):
    def __init__(self, plan_sha256: str, failures: int) -> None:
        super().__init__(plan_sha256)
        self.failures_remaining = failures

    def wait_ready_and_probe(self, allocation, handle, plan, *, deadline_monotonic):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("injected readiness failure")
        return super().wait_ready_and_probe(
            allocation, handle, plan, deadline_monotonic=deadline_monotonic
        )


class _FailReadinessCall(_Runtime):
    def __init__(self, plan_sha256: str, fail_call: int) -> None:
        super().__init__(plan_sha256)
        self.fail_call = fail_call
        self.readiness_calls = 0

    def wait_ready_and_probe(self, allocation, handle, plan, *, deadline_monotonic):
        self.readiness_calls += 1
        if self.readiness_calls == self.fail_call:
            raise RuntimeError("injected readiness failure")
        return super().wait_ready_and_probe(
            allocation, handle, plan, deadline_monotonic=deadline_monotonic
        )


class _DeleteRetryProvider(_Provider):
    def __init__(self) -> None:
        super().__init__()
        self.cleanup_calls: list[tuple[int, str]] = []

    def delete_allocation_observed(self, allocation, *, binding, delete_attempt,
                                   deadline_monotonic):
        self.cleanup_calls.append((delete_attempt, "delete"))
        if delete_attempt == 1:
            raise RuntimeError("injected transient delete failure")
        return super().delete_allocation_observed(
            allocation, binding=binding, delete_attempt=delete_attempt,
            deadline_monotonic=deadline_monotonic,
        )

    def inventory_absent_observed(self, allocation, *, binding, delete_attempt,
                                  deadline_monotonic):
        self.cleanup_calls.append((delete_attempt, "inventory"))
        return super().inventory_absent_observed(
            allocation, binding=binding, delete_attempt=delete_attempt,
            deadline_monotonic=deadline_monotonic,
        )

    def direct_not_found_observed(self, allocation, *, binding, delete_attempt,
                                  deadline_monotonic):
        self.cleanup_calls.append((delete_attempt, "direct"))
        return super().direct_not_found_observed(
            allocation, binding=binding, delete_attempt=delete_attempt,
            deadline_monotonic=deadline_monotonic,
        )


class _FailAfterDurableWarmupCapture(EvidenceCaptureV2):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.failed = False

    def cell_complete(self, block_id, cell_id, *, warmup,
                      startup_attempt_id_sha256, process_identity_sha256):
        super().cell_complete(
            block_id, cell_id, warmup=warmup,
            startup_attempt_id_sha256=startup_attempt_id_sha256,
            process_identity_sha256=process_identity_sha256,
        )
        if warmup and not self.failed:
            self.failed = True
            raise RuntimeError("injected failure after durable warmup boundary")


def _ledger(directory: Path) -> list[dict]:
    result = []
    for line in (directory / "lifecycle.jsonl").read_text().splitlines():
        entry = json.loads(line)
        details_path = directory / (
            f"event-{entry['sequence']:06d}-{entry['details_sha256']}.json"
        )
        result.append({"event": entry["event"], "details": json.loads(details_path.read_text())})
    return result


def _records(directory: Path) -> list[dict]:
    return [json.loads(line)["payload"] for line in
            (directory / "requests.jsonl").read_text().splitlines()]


class FailurePathIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(
            dir="/private/tmp", prefix="episode1-failure-path-evidence-"
        ))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _fixture(self, *, name: str, runtime: _Runtime, provider: _Provider,
                 capture_class=EvidenceCaptureV2):
        plan, receipt, plan_bytes, material, source = approved_plan()
        reference = make_bundle(plan)
        context = RunContext.create(
            plan=plan, authorization_receipt=receipt, plan_file_bytes=plan_bytes,
            material_file_bytes=material,
            material_files={"src/example.py": b"print('bound execution material')\n"},
            observed_source_commit=plan["source_commit"], authorization_source_bytes=source,
            unique_name=f"episode1-candidate-1-{name}",
            telemetry_series=("native-queue", "system-rss"), utc_now=lambda: NOW,
            run_id="run-20260922", attempt_id="attempt-01",
            clock_domain="integration-clock", boot_id="integration-boot",
        )
        cells = _RotatingProductionCells()
        for fixture_task, authored_task in zip(
            cells.evidence["natural_quality"], authored_quality_corpus(), strict=True
        ):
            fixture_task["task_id"] = authored_task["task_id"]
        specs = (
            TelemetrySeriesSpec("native-queue", "native", "native_queue_depth", "gauge", {}),
            TelemetrySeriesSpec(
                "system-rss", "system_source_window", "rss_bytes", "gauge",
                {"source": "proc", "unit": "bytes", "scope": "process"},
            ),
        )

        def telemetry_factory(plan_arg, block, run_attempt_id, startup_attempt_id,
                              block_attempt, allocation, capture):
            return Episode1BlockTelemetry(
                plan=plan_arg, block=block, run_attempt_id=run_attempt_id,
                startup_attempt_id=startup_attempt_id, block_attempt=block_attempt,
                allocation=allocation, capture=capture, specs=specs,
                native=_NativeSource(capture.contract.run_id, run_attempt_id, dict(block)),
                max_system_sampling_gap_ns=10_000_000,
                native_clock_domain="integration-clock",
            )

        directory = self.root / name
        captures: list[EvidenceCaptureV2] = []

        def make_capture(*args, **kwargs):
            capture = capture_class(*args, **kwargs)
            captures.append(capture)
            return capture

        def execute():
            with mock.patch(
                "runpod_benchmark.episode1_application.EvidenceCaptureV2", make_capture
            ):
                return execute_episode1(
                    context=context, private_evidence_directory=directory,
                    provider=provider, guard=Guard(),
                    runtime_factory=lambda _allocation: runtime,
                    cell_factory=lambda _allocation: cells,
                    telemetry_factory=telemetry_factory, utc_now=lambda: NOW,
                    monitor_poll_seconds=0.05,
                )

        return plan, reference, context, cells, directory, captures, execute

    def _assert_not_promotable(self, capture, *, plan, reference):
        try:
            bundle = capture.assemble_promotion_bundle(
                plan=plan, sources=reference["sources"], approval=reference["approval"],
                image_digest=plan["runtime_builds"][0]["derived_image_digest"],
            )
        except BaseException:
            return
        with self.assertRaises(BaseException):
            promote_private_evidence(plan=plan, bundle=bundle)

    def test_one_startup_retry_and_delete_retry_promotes(self):
        plan, *_ = approved_plan()
        runtime = _ReadinessFailures(plan["plan_sha256"], failures=1)
        provider = _DeleteRetryProvider()
        plan, reference, _context, cells, directory, captures, execute = self._fixture(
            name="retry-success", runtime=runtime, provider=provider
        )
        result = execute()
        self.assertEqual(result.summary["startup_retries"], 1)
        self.assertEqual(result.summary["measured_requests"], 528)
        self.assertEqual(len(runtime.starts), 7)
        self.assertEqual(provider.cleanup_calls, [
            (1, "delete"), (1, "inventory"), (1, "direct"),
            (2, "delete"), (2, "inventory"), (2, "direct"),
        ])
        self.assertEqual(len(captures), 1)
        events = _ledger(directory)
        failed = [item for item in events if item["event"] == "startup-failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual((failed[0]["details"]["warmup_records"],
                          failed[0]["details"]["measured_records"]), (0, 0))
        self.assertEqual([item["event"] for item in events].count("failed-start-cleanup"), 1)
        self.assertEqual([item["event"] for item in events].count("startup-retry"), 1)
        self.assertEqual(len(_records(directory)), 600)
        bundle = result.capture.assemble_promotion_bundle(
            plan=plan, sources=reference["sources"], approval=reference["approval"],
            image_digest=plan["runtime_builds"][0]["derived_image_digest"],
        )
        promoted = promote_private_evidence(plan=plan, bundle=bundle)
        self.assertEqual(promoted["record_count"], 600)
        self.assertEqual(
            [item["evidence"]["delete_attempt"]
             for item in bundle["provider_artifacts"]["artifacts"]],
            [2, 2, 2],
        )
        self.assertEqual(cells.server_count, 6)

    def test_second_startup_failure_aborts_without_promotable_evidence(self):
        plan, *_ = approved_plan()
        runtime = _ReadinessFailures(plan["plan_sha256"], failures=2)
        provider = _DeleteRetryProvider()
        plan, reference, _context, _cells, directory, captures, execute = self._fixture(
            name="retry-exhausted", runtime=runtime, provider=provider
        )
        with self.assertRaises(BaseException):
            execute()
        self.assertEqual(len(runtime.starts), 2)
        self.assertEqual(_records(directory), [])
        events = _ledger(directory)
        self.assertEqual([item["event"] for item in events].count("startup-failed"), 2)
        self.assertEqual([item["event"] for item in events].count("failed-start-cleanup"), 2)
        self.assertIn("deletion-verified", [item["event"] for item in events])
        self.assertEqual(provider.cleanup_calls[-3:], [
            (2, "delete"), (2, "inventory"), (2, "direct")
        ])
        self.assertEqual(len(captures), 1)
        self._assert_not_promotable(captures[0], plan=plan, reference=reference)

    def test_failed_start_cannot_reuse_an_earlier_successful_process_identity(self):
        plan, *_ = approved_plan()
        runtime = _FailReadinessCall(plan["plan_sha256"], fail_call=2)
        provider = _Provider()
        plan, reference, _context, _cells, _directory, _captures, execute = self._fixture(
            name="later-retry", runtime=runtime, provider=provider
        )
        result = execute()
        bundle = result.capture.assemble_promotion_bundle(
            plan=plan, sources=reference["sources"], approval=reference["approval"],
            image_digest=plan["runtime_builds"][0]["derived_image_digest"],
        )
        promote_private_evidence(plan=plan, bundle=bundle)
        forged = copy.deepcopy(bundle)
        entries = forged["ledger"]["entries"]
        first_success = next(item for item in entries if item["event"] == "block-start")
        reused_identity = digest({
            "process_id_sha256": first_success["details"]["process_id_sha256"],
            "process_start_identity_sha256":
                first_success["details"]["process_start_identity_sha256"],
        })
        failed = next(item for item in entries if item["event"] == "startup-failed")
        cleanup = next(item for item in entries if item["event"] == "failed-start-cleanup")
        failed["details"]["process_identity_sha256"] = reused_identity
        cleanup["details"]["process_identity_sha256"] = reused_identity
        previous = "0" * 64
        for item in entries:
            item["previous_sha256"] = previous
            item.pop("record_sha256", None)
            item["record_sha256"] = digest(item)
            previous = item["record_sha256"]
        forged["ledger"].pop("artifact_sha256")
        forged["ledger"]["artifact_sha256"] = digest(forged["ledger"])
        forged["manifest"]["ledger_sha256"] = forged["ledger"]["artifact_sha256"]
        forged["manifest"].pop("artifact_sha256")
        forged["manifest"]["artifact_sha256"] = digest(forged["manifest"])
        with self.assertRaisesRegex(ValueError, "failed startup evidence"):
            promote_private_evidence(plan=plan, bundle=forged)

    def test_durable_post_warmup_capture_failure_still_cleans_up(self):
        plan, *_ = approved_plan()
        runtime = _ReadinessFailures(plan["plan_sha256"], failures=0)
        provider = _Provider()
        plan, reference, _context, _cells, directory, captures, execute = self._fixture(
            name="capture-failure", runtime=runtime, provider=provider,
            capture_class=_FailAfterDurableWarmupCapture,
        )
        with self.assertRaises(BaseException):
            execute()
        records = _records(directory)
        self.assertEqual(len(records), 4)
        self.assertTrue(all(record["warmup"] is True for record in records))
        events = _ledger(directory)
        self.assertIn("warmup-complete", [item["event"] for item in events])
        self.assertIn("deletion-verified", [item["event"] for item in events])
        self.assertTrue(provider.deleted)
        self.assertEqual(len(captures), 1)
        self._assert_not_promotable(captures[0], plan=plan, reference=reference)


if __name__ == "__main__":
    unittest.main()
