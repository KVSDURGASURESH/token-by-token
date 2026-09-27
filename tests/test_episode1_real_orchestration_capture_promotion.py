from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from runpod_benchmark.episode1 import authored_quality_corpus, canonical_json
from runpod_benchmark.episode1_application import RunContext, execute_episode1
from runpod_benchmark.episode1_orchestrator import (
    Allocation, DeletionAuthority, RuntimeHandle, _attempt_hashes,
)
from runpod_benchmark.episode1_promotion import promote_private_evidence
from runpod_benchmark.episode1_telemetry import Episode1BlockTelemetry, TelemetrySeriesSpec
from test_episode1_orchestration_loopback import _RotatingProductionCells
from test_episode1_orchestrator import Guard, NOW, approved_plan
from test_episode1_promotion import make_bundle


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _sealed(value: dict) -> dict:
    result = dict(value)
    result["artifact_sha256"] = _digest(result)
    return result


class _NativeSource:
    def __init__(self, run_id: str, attempt_id: str, block: dict) -> None:
        self.run_id, self.attempt_id, self.block = run_id, attempt_id, block
        self.handle: RuntimeHandle | None = None

    def start(self, handle: RuntimeHandle, *, deadline_monotonic: float) -> None:
        assert time.monotonic() < deadline_monotonic
        self.handle = handle

    def finish(self, *, first_measured_a_ns: int, last_measured_end_ns: int,
               deadline_monotonic: float):
        assert time.monotonic() < deadline_monotonic
        assert self.handle is not None
        handle = self.handle
        process_id = f"pid:{handle.process_pid}"
        process_start = f"ticks:{handle.process_start_ticks}"
        chunks = []
        for sequence, (when, value) in enumerate(
            ((first_measured_a_ns, 10.0), (last_measured_end_ns, 20.0)), 1
        ):
            raw = (b"# HELP native_queue_depth Runtime queue depth\n"
                   b"# TYPE native_queue_depth gauge\n"
                   b"# UNIT native_queue_depth items\n" +
                   f"native_queue_depth {value}\n".encode())
            binding = {
                "run_id": self.run_id, "attempt_id": self.attempt_id,
                "process_identity": process_id,
                "process_start_identity": process_start,
                "runtime": handle.runtime, "block": handle.block_id,
                "clock_domain": "integration-clock",
            }
            sample = {
                "clock_domain": "integration-clock", "monotonic_ns": when,
                "process_identity": process_id, "process_start_identity": process_start,
                "runtime": handle.runtime, "block": handle.block_id,
                "metric_name": "native_queue_depth", "labels": {}, "value": value,
                "status": "ok", "reason": None, "kind": "gauge", "unit": "items",
                "help": "Runtime queue depth", "declared_type": "gauge",
                "declared_unit": "items",
            }
            envelope = {
                "schema_version": "episode1.native-scrape.v1", "binding": binding,
                "sequence": sequence, "scheduled_monotonic_ns": when - 2,
                "observed_monotonic_ns": when, "observed_utc_ns": time.time_ns(),
                "clock_uncertainty_ns": 2, "scrape_start_monotonic_ns": when - 1,
                "scrape_end_monotonic_ns": when + 1,
                "scrape_deadline_monotonic_ns": int(deadline_monotonic * 1e9),
                "scrape_status": "ok", "scrape_reason": None, "schedule_lag_ns": 1,
                "observed_process_identity_before": [process_id, process_start],
                "observed_process_identity_after": [process_id, process_start],
                "raw_kind": "body", "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_base64": base64.b64encode(raw).decode("ascii"),
                "native_samples": [sample], "counter_resets": [],
            }
            chunks.append((canonical_json(envelope) + "\n").encode())
        return b"".join(chunks), {
            "start_monotonic_ns": first_measured_a_ns,
            "end_monotonic_ns": last_measured_end_ns,
            "max_sampling_gap_ns": last_measured_end_ns - first_measured_a_ns,
        }

    def abort(self, *, deadline_monotonic: float) -> None:
        assert time.monotonic() < deadline_monotonic


class _Runtime:
    def __init__(self, plan_sha256: str) -> None:
        self.plan_sha256 = plan_sha256
        self.starts: list[RuntimeHandle] = []
        self._block_state: dict[str, dict[str, int]] = {}

    def attest_allocation(self, allocation, plan, *, deadline_monotonic):
        return {
            "gpu_uuid": "gpu-fixture", "gpu_pci": "0000:01:00.0",
            "driver_version": "580", "boot_id": "remote-boot",
            "build_attestation_sha256": "f" * 64,
            "installed_material_sha256": "e" * 64,
            "gpu_count": 1, "gpu_total_memory_mib": 81559,
            "compute_capability": "9.0", "used_memory_mib": 0,
        }

    def start(self, allocation, block, plan, *, deadline_monotonic):
        ordinal = len(self.starts) + 1
        handle = RuntimeHandle(
            f"runtime-process-{ordinal}", block["runtime"], block["block_id"],
            process_pid=10_000 + ordinal, process_start_ticks=20_000 + ordinal,
        )
        self.starts.append(handle)
        return handle

    def wait_ready_and_probe(self, allocation, handle, plan, *, deadline_monotonic):
        return {"exact_tokens": True, "effective_flags": True}

    def stop(self, allocation, handle, *, deadline_monotonic): return {"reaped": True}
    def descendants_absent(self, allocation, handle, *, deadline_monotonic): return True
    def memory_recovered(self, allocation, baseline, *, deadline_monotonic): return True
    def cleanup_failed_start(self, allocation, block, baseline, *, deadline_monotonic):
        return {"descendants_absent": True, "memory_recovered": True}

    def sample_system(self, allocation, plan, block, handle, phase, run_id, attempt_id,
                      startup_attempt_id, *, deadline_monotonic, slot_kind="periodic"):
        block_id = str(block["block_id"])
        stream_id = (block_id, startup_attempt_id)
        state = self._block_state.setdefault(stream_id, {"sequence": 0, "source": 1_000_000})
        state["sequence"] += 1
        state["source"] += 1_000_000
        sequence, scheduled = state["sequence"], state["source"]
        begun, observed = scheduled + 1, scheduled + 2
        target = None if handle is None else {
            "pid": handle.process_pid, "start_ticks": handle.process_start_ticks,
            "role": handle.runtime,
        }
        metric = {
            "source": "proc", "name": "rss_bytes", "unit": "bytes",
            "scope": "process", "value": None if handle is None else float(sequence),
            "status": "unavailable" if handle is None else "ok",
            "reason": "prestart" if handle is None else None,
        }
        record = {
            "schema_version": "episode1.system-sample.v1",
            "binding": {"run_id": run_id, "attempt_id": attempt_id, "block": block_id,
                        "clock_domain": "linux-clock-monotonic",
                        "source_boot_id": "remote-boot"},
            "sequence": sequence, "phase": phase, "slot_kind": slot_kind,
            "scheduled_monotonic_ns": scheduled, "sample_start_monotonic_ns": begun,
            "observed_monotonic_ns": observed, "observed_utc_ns": time.time_ns(),
            "clock_uncertainty_ns": 1, "schedule_lag_ns": 1, "missed_slots": 0,
            "observed_gap_ns": None if sequence == 1 else 1_000_000,
            "process_expected": target,
            "process_identity_before": None if handle is None else [handle.process_pid, handle.process_start_ticks],
            "process_identity_after": None if handle is None else [handle.process_pid, handle.process_start_ticks],
            "process_identity_status": "prestart" if handle is None else "ok",
            "metrics": [metric],
        }
        encoded = (canonical_json(record) + "\n").encode()
        result = {"record": record, "source_sha256": hashlib.sha256(encoded).hexdigest()}
        marker = {"measurement_start_boundary": "measurement_start",
                  "measurement_end_boundary": "measurement_end"}.get(slot_kind)
        if marker:
            call_completed = time.monotonic_ns()
            result["boundary_receipt"] = {
                "schema_version": "episode1.system-window-boundary.v1",
                "plan_sha256": self.plan_sha256, "run_id": run_id,
                "attempt_id": attempt_id, "block": block_id,
                "runtime": handle.runtime, "marker": marker,
                "source_clock_domain": "linux-clock-monotonic",
                "source_boot_id": "remote-boot", "source_sequence": sequence,
                "source_record_sha256": hashlib.sha256(encoded).hexdigest(),
                "source_observed_monotonic_ns": observed,
                "source_observed_utc_ns": record["observed_utc_ns"],
                "source_utc_uncertainty_ns": 1,
                "client_clock_domain": "client_monotonic_ns",
                "client_call_started_monotonic_ns": call_completed - 1,
                "client_call_completed_monotonic_ns": call_completed,
            }
        return result


class _Provider:
    def __init__(self) -> None:
        self.owner_callback = None
        self.allocation: Allocation | None = None
        self.binding = None
        self.deleted = False

    def bind_cleanup_owner(self, callback): self.owner_callback = callback

    def create_allocation(self, *, unique_name, ownership_token, plan, deadline_monotonic):
        billing = time.monotonic()
        ref = "registry.example/episode1@" + plan["runtime_builds"][0]["derived_image_digest"]
        allocation = Allocation(
            "pod-integration", unique_name, "127.0.0.1", 2222, plan["access"]["ssh_port"],
            ownership_token, plan["allocation"]["gpu"], plan["allocation"]["gpu_count"],
            plan["allocation"]["data_center_id"], plan["allocation"]["cloud_type"],
            plan["allocation"]["container_disk_gb"], plan["allocation"]["volume_gb"],
            plan["allocation"]["volume_mount_path"], ref, ref, billing,
        )
        self.allocation = allocation
        assert self.owner_callback is not None
        self.owner_callback(DeletionAuthority(
            allocation.private_id, allocation.unique_name, allocation.ownership_token, billing
        ))
        return allocation

    def recover_exact_name(self, unique_name, *, deadline_monotonic): return []
    def read_allocation(self, allocation, *, deadline_monotonic): return allocation
    def current_exposure_fraction(self, allocation, plan, *, deadline_monotonic): return 0.01

    def make_cleanup_observation_binding(self, allocation, **kwargs):
        ownership = _digest({
            "provider": "runpod-rest-v2", "private_id": allocation.private_id,
            "unique_name": allocation.unique_name,
            "ownership_token_sha256": hashlib.sha256(allocation.ownership_token.encode()).hexdigest(),
            "billing_started_monotonic_ns": int(allocation.billing_started_monotonic * 1e9),
        })
        self.binding = SimpleNamespace(allocation=allocation, ownership_identity_sha256=ownership, **kwargs)
        return self.binding

    def _call(self, role, method, path, status, raw, *, binding, delete_attempt,
              deadline_monotonic, query=None, **extra):
        started = time.monotonic_ns()
        completed = max(started + 1, time.monotonic_ns())
        hard = binding.original_deadline_monotonic_ns
        operation = int(deadline_monotonic * 1e9)
        evidence = _sealed({
            "schema_version": "episode1.provider-call-evidence.v1", "role": role,
            "delete_attempt": delete_attempt, "run_id": binding.run_id,
            "attempt_id": binding.attempt_id, "plan_sha256": binding.plan_sha256,
            "resource_identity_sha256": binding.resource_identity_sha256,
            "ownership_identity_sha256": binding.ownership_identity_sha256,
            "http_method": method, "request_path": path, "request_query": query or {},
            "http_status": status, "request_started_monotonic_ns": started,
            "body_complete_monotonic_ns": completed,
            "absolute_deadline_monotonic_ns": hard,
            "operation_deadline_monotonic_ns": operation,
            "raw_body_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_body_base64": base64.b64encode(raw).decode("ascii"), **extra,
        })
        return evidence, completed

    def _observation(self, value, kind, status, complete, absent, raw, evidence, completed,
                     binding, delete_attempt):
        capture = {
            "schema_version": "episode1.provider-call-observation.v1",
            "delete_attempt": delete_attempt, "kind": kind, "run_id": binding.run_id,
            "attempt_id": binding.attempt_id, "plan_sha256": binding.plan_sha256,
            "resource_identity_sha256": binding.resource_identity_sha256,
            "observed_monotonic_ns": completed,
            "provider_response_sha256": hashlib.sha256(raw).hexdigest(),
            "status": status, "complete": complete, "resource_absent": absent,
        }
        return SimpleNamespace(value=value, raw_bytes=raw, capture_input=capture,
                               provider_artifact=evidence)

    def delete_allocation_observed(self, allocation, *, binding, delete_attempt, deadline_monotonic):
        raw = b""
        evidence, completed = self._call(
            "delete-response", "DELETE", f"/pods/{allocation.private_id}", 204, raw,
            binding=binding, delete_attempt=delete_attempt, deadline_monotonic=deadline_monotonic,
        )
        self.deleted = True
        return self._observation(True, "delete_ack", "acknowledged", None, None,
                                 raw, evidence, completed, binding, delete_attempt)

    def inventory_absent_observed(self, allocation, *, binding, delete_attempt, deadline_monotonic):
        cursor = "cursor-2"
        raws = [
            canonical_json({"pagination": {"hasNextPage": True, "nextCursor": cursor},
                            "pods": [{"id": "pod-other-1"}]}).encode(),
            canonical_json({"pagination": {"hasNextPage": False, "nextCursor": None},
                            "pods": []}).encode(),
        ]
        pages, previous = [], None
        for sequence, raw in enumerate(raws, 1):
            request_cursor = None if sequence == 1 else cursor
            query = {"includeClusterPods": "true", "limit": "1000"}
            if request_cursor is not None: query["cursor"] = request_cursor
            page, previous = self._call(
                "inventory-page", "GET", "/pods", 200, raw,
                binding=binding, delete_attempt=delete_attempt,
                deadline_monotonic=deadline_monotonic, query=query, sequence=sequence,
                request_cursor=request_cursor, has_next_page=sequence == 1,
                next_cursor=cursor if sequence == 1 else None,
            )
            pages.append(page)
        manifest = _sealed({
            "schema_version": "episode1.provider-inventory-evidence.v1",
            "role": "inventory-after-delete", "delete_attempt": delete_attempt,
            "run_id": binding.run_id, "attempt_id": binding.attempt_id,
            "plan_sha256": binding.plan_sha256,
            "resource_identity_sha256": binding.resource_identity_sha256,
            "ownership_identity_sha256": binding.ownership_identity_sha256,
            "absolute_deadline_monotonic_ns": binding.original_deadline_monotonic_ns,
            "pages": pages, "terminal_page_sequence": 2,
            "terminal_next_cursor": None, "complete": True, "resource_absent": True,
        })
        raw = canonical_json(manifest).encode()
        return self._observation(True, "inventory_read", "complete", True, True,
                                 raw, manifest, previous, binding, delete_attempt)

    def direct_not_found_observed(self, allocation, *, binding, delete_attempt, deadline_monotonic):
        raw = b""
        evidence, completed = self._call(
            "direct-after-delete", "GET", f"/pods/{allocation.private_id}", 404, raw,
            binding=binding, delete_attempt=delete_attempt, deadline_monotonic=deadline_monotonic,
        )
        return self._observation(True, "direct_read", "not_found", None, None,
                                 raw, evidence, completed, binding, delete_attempt)


class RealOrchestrationCapturePromotionTest(unittest.TestCase):
    def test_attempt_identity_hash_binds_emitted_component_hashes(self):
        handle = RuntimeHandle(
            "runtime-process", "vllm", "block-01",
            process_pid=10001, process_start_ticks=20001,
        )
        _, process_id_sha256, process_start_sha256, identity_sha256 = (
            _attempt_hashes("block-01", 1, handle)
        )
        self.assertEqual(
            identity_sha256,
            _digest({
                "process_id_sha256": process_id_sha256,
                "process_start_identity_sha256": process_start_sha256,
            }),
        )
        self.assertEqual(process_start_sha256, _digest({"pid": 10001, "start_ticks": 20001}))

    def test_real_600_request_path_promotes(self):
        plan, receipt, plan_bytes, material, source = approved_plan()
        reference = make_bundle(plan)
        context = RunContext.create(
            plan=plan, authorization_receipt=receipt, plan_file_bytes=plan_bytes,
            material_file_bytes=material,
            material_files={"src/example.py": b"print('bound execution material')\n"},
            observed_source_commit=plan["source_commit"], authorization_source_bytes=source,
            unique_name="episode1-candidate-1-run", telemetry_series=("native-queue", "system-rss"),
            utc_now=lambda: NOW, run_id="run-20260922", attempt_id="attempt-01",
            clock_domain="integration-clock", boot_id="integration-boot",
        )
        provider, runtime, cells = _Provider(), _Runtime(plan["plan_sha256"]), _RotatingProductionCells()
        for fixture_task, authored_task in zip(
            cells.evidence["natural_quality"], authored_quality_corpus(), strict=True
        ):
            fixture_task["task_id"] = authored_task["task_id"]
        specs = (
            TelemetrySeriesSpec("native-queue", "native", "native_queue_depth", "gauge", {}),
            TelemetrySeriesSpec("system-rss", "system_source_window", "rss_bytes", "gauge",
                                {"source": "proc", "unit": "bytes", "scope": "process"}),
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

        evidence_root = Path(tempfile.mkdtemp(
            dir="/private/tmp", prefix="episode1-real-orchestration-evidence-"
        ))
        self.addCleanup(shutil.rmtree, evidence_root, ignore_errors=True)
        directory = evidence_root / "capture"
        result = execute_episode1(
            context=context, private_evidence_directory=directory, provider=provider,
            guard=Guard(), runtime_factory=lambda _allocation: runtime,
            cell_factory=lambda _allocation: cells, telemetry_factory=telemetry_factory,
            utc_now=lambda: NOW, monitor_poll_seconds=0.05,
        )
        self.assertEqual(result.summary, {
            "completed_blocks": 6, "startup_retries": 0, "warmups": 72,
            "measured_requests": 528, "deletion_verified": True,
        })
        self.assertEqual(len(runtime.starts), 6)
        self.assertEqual(len({(h.process_pid, h.process_start_ticks) for h in runtime.starts}), 6)
        self.assertEqual(cells.server_count, 6)
        bundle = result.capture.assemble_promotion_bundle(
            plan=plan, sources=reference["sources"], approval=reference["approval"],
            image_digest=plan["runtime_builds"][0]["derived_image_digest"],
        )
        promoted = promote_private_evidence(plan=plan, bundle=bundle)
        self.assertEqual(promoted["record_count"], 600)
        self.assertEqual(len(bundle["records"]["records"]), 600)
        records = bundle["records"]["records"]
        self.assertEqual(sum(record["warmup"] is True for record in records), 72)
        self.assertEqual(sum(record["warmup"] is False for record in records), 528)
        self.assertEqual(
            len({(record["block_id"], record["cell_id"]) for record in records}), 18
        )
        lifecycle = [json.loads(line)["payload"] for line in
                     (directory / "request-lifecycle.jsonl").read_text().splitlines()]
        self.assertEqual(len(lifecycle), 1800)
        self.assertEqual({item["stage"] for item in lifecycle},
                         {"scheduled", "dispatched", "finalized"})
        ledger = bundle["ledger"]["entries"]
        self.assertEqual(sum(item["event"] in {"warmup-complete", "cell-complete"}
                             for item in ledger), 36)
        self.assertEqual(sum(item["event"] == "block-start" for item in ledger), 6)
        provider_artifacts = bundle["provider_artifacts"]["artifacts"]
        delete_evidence = provider_artifacts[0]["evidence"]
        inventory_evidence = provider_artifacts[1]["evidence"]
        direct_evidence = provider_artifacts[2]["evidence"]
        self.assertEqual(
            (delete_evidence["http_method"], delete_evidence["http_status"],
             provider_artifacts[0]["raw_base64"]),
            ("DELETE", 204, ""),
        )
        self.assertEqual(len(inventory_evidence["pages"]), 2)
        self.assertEqual(
            [page["request_cursor"] for page in inventory_evidence["pages"]],
            [None, "cursor-2"],
        )
        self.assertEqual(
            (direct_evidence["http_method"], direct_evidence["http_status"],
             provider_artifacts[2]["raw_base64"]),
            ("GET", 404, ""),
        )
        hard_deadline = bundle["manifest"]["hard_deadline_monotonic_ns"]
        self.assertTrue(all(
            evidence["absolute_deadline_monotonic_ns"] == hard_deadline
            for evidence in (
                delete_evidence, *inventory_evidence["pages"], direct_evidence,
            )
        ))
        self.assertEqual([item["evidence"]["delete_attempt"] for item in provider_artifacts],
                         [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
