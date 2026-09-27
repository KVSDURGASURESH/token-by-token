from __future__ import annotations

import base64
import copy
import hashlib
import unittest

from runpod_benchmark.episode1_promotion import PromotionError, digest, promote_private_evidence, seal
from runpod_benchmark.episode1 import CELLS, canonical_json
from runpod_benchmark.episode1_execution import compile_execution_candidate, spend_approval_phrase, watchdog_risk_phrase
from test_episode1_contract import observation
from test_episode1_execution import inputs, protocol


RUN = "run-20260922"
ATTEMPT = "attempt-01"
RESOURCE = "d" * 64
START = 1_000_000_000


def ready_plan():
    return compile_execution_candidate(protocol(), inputs())


def reseal(value):
    body = dict(value)
    body.pop("artifact_sha256", None)
    return seal(body)


def ledger_entry(plan, sequence, event, when, previous, details):
    body = {
        "schema_version": "episode1.private-ledger.v2",
        "sequence": sequence,
        "run_id": RUN,
        "attempt_id": ATTEMPT,
        "plan_sha256": plan["plan_sha256"],
        "event": event,
        "monotonic_ns": when,
        "previous_sha256": previous,
        "details": details,
    }
    body["record_sha256"] = digest(body)
    return body


def rechain(bundle):
    entries = bundle["ledger"]["entries"]
    previous = "0" * 64
    for sequence, entry in enumerate(entries, 1):
        entry["sequence"] = sequence
        entry["previous_sha256"] = previous
        body = dict(entry); body.pop("record_sha256", None)
        entry["record_sha256"] = digest(body)
        previous = entry["record_sha256"]
    bundle["ledger"] = reseal(bundle["ledger"])
    bundle["manifest"]["ledger_sha256"] = bundle["ledger"]["artifact_sha256"]
    bundle["manifest"] = reseal(bundle["manifest"])


def make_bundle(plan, *, provisional=True, retry_blocks=()):
    approval = seal({
        "schema_version": "episode1.digest-approval-receipt.v1",
        "run_id": RUN, "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"],
        "approved_plan_sha256": plan["plan_sha256"],
        "spend_approval": spend_approval_phrase(plan),
        "watchdog_risk_approval": watchdog_risk_phrase(plan),
        "retained_receipt_sha256": "e" * 64,
    })
    private_id="pod-fixture"; unique_name="episode1-fixture"; token="f"*64
    billing=(START+1)/1_000_000_000
    token_sha=hashlib.sha256(token.encode()).hexdigest()
    RESOURCE=digest({"provider":"runpod-rest-v2","private_id":private_id,
        "unique_name":unique_name,"ownership_token_sha256":token_sha,
        "billing_started_monotonic":billing})
    ownership=digest({"provider":"runpod-rest-v2","private_id":private_id,
        "unique_name":unique_name,"ownership_token_sha256":token_sha,
        "billing_started_monotonic_ns":int(billing*1_000_000_000)})
    immutable_facts={"private_id":private_id,"unique_name":unique_name,
        "ssh_host":"127.0.0.1","ssh_public_port":2222,
        "requested_image_reference":"example.invalid/episode1@"+plan["runtime_builds"][0]["derived_image_digest"],
        "provider_image_reference":"example.invalid/episode1@"+plan["runtime_builds"][0]["derived_image_digest"],
        "gpu":plan["allocation"]["gpu"],"gpu_count":plan["allocation"]["gpu_count"],
        "data_center_id":plan["allocation"]["data_center_id"],"cloud_type":plan["allocation"]["cloud_type"],
        "container_disk_gb":plan["allocation"]["container_disk_gb"],"volume_gb":plan["allocation"]["volume_gb"],
        "volume_mount_path":plan["allocation"]["volume_mount_path"],
        "container_ssh_port":plan["access"]["ssh_port"]}
    immutable=digest(immutable_facts)
    hard_deadline=START+int(plan["budget"]["maximum_lifetime_seconds"])*1_000_000_000
    allocation_authority=seal({"schema_version":"episode1.sanitized-allocation-authority.v1",
        "run_id":RUN,"attempt_id":ATTEMPT,"plan_sha256":plan["plan_sha256"],
        "provider":"runpod-rest-v2","private_id":private_id,"unique_name":unique_name,
        "ownership_token_sha256":token_sha,"billing_started_monotonic":billing,
        "billing_started_monotonic_ns":int(billing*1_000_000_000),
        "original_t0_monotonic_ns":START,"hard_deadline_monotonic_ns":hard_deadline,
        "resource_identity_sha256":RESOURCE,"ownership_identity_sha256":ownership,
        "immutable_allocation":immutable_facts,"immutable_allocation_sha256":immutable})
    records = []
    group_hashes = {}
    events = []
    sequence = 0
    previous = "0" * 64
    now = START

    def add(event, details, *, advance=1_000_000_000):
        nonlocal sequence, previous, now
        now += advance
        sequence += 1
        entry = ledger_entry(plan, sequence, event, now, previous, details)
        previous = entry["record_sha256"]
        events.append(entry)

    add("allocation-owned", {
        "resource_identity_sha256": RESOURCE,
        "cleanup_deadline_monotonic_ns": START + 7_200_000_000_000,
        "immutable_allocation_sha256": immutable,
        "allocation_authority_sha256":allocation_authority["artifact_sha256"],
    })
    cells = {cell["id"]: cell for cell in CELLS}
    ordinal = 0
    process_ordinal = 0
    for block_index, block in enumerate(plan["blocks"]):
        def process_facts(block_attempt, *, emit_start):
            nonlocal process_ordinal
            process_ordinal += 1
            process_id = f"{process_ordinal:064x}"
            process_start = f"{process_ordinal + 100:064x}"
            startup_attempt = hashlib.sha256(
                f"{block['block_id']}-attempt-{block_attempt}".encode()
            ).hexdigest()
            process_identity = digest({"process_id_sha256": process_id, "process_start_identity_sha256": process_start})
            if emit_start:
                add("block-start", {
                "resource_identity_sha256": RESOURCE, "block_id": block["block_id"],
                "runtime": block["runtime"], "block_attempt": block_attempt,
                "startup_attempt_id_sha256": startup_attempt,
                "process_id_sha256": process_id,
                "process_start_identity_sha256": process_start,
                "image_digest": plan["runtime_builds"][0]["derived_image_digest"],
                })
            return startup_attempt, process_identity

        if block_index in retry_blocks:
            startup_attempt, process_identity = process_facts(1, emit_start=False)
            add("startup-failed", {
                "resource_identity_sha256": RESOURCE, "block_id": block["block_id"],
                "runtime": block["runtime"], "block_attempt": 1,
                "startup_attempt_id_sha256": startup_attempt,
                "process_identity_sha256": process_identity,
                "failure_stage": "readiness_probe", "warmup_records": 0,
                "measured_records": 0,
            })
            add("failed-start-cleanup", {
                "resource_identity_sha256": RESOURCE, "block_id": block["block_id"],
                "runtime": block["runtime"], "block_attempt": 1,
                "startup_attempt_id_sha256": startup_attempt,
                "process_identity_sha256": process_identity,
                "descendants_absent": True, "gpu_memory_recovered": True,
            })
            startup_attempt, process_identity = process_facts(2, emit_start=True)
        else:
            startup_attempt, process_identity = process_facts(1, emit_start=True)
        for warmup in (True, False):
            for cell_id in block["cell_order"]:
                cell = cells[cell_id]
                count = cell["warmups" if warmup else "requests"]
                group = []
                a = now + 10_000_000
                for order in range(1, count + 1):
                    ordinal += 1
                    item = observation(
                        request_id=f"request-{ordinal}", block_id=block["block_id"],
                        pair_id=block["pair_id"], runtime=block["runtime"], cell_id=cell_id,
                        mode=cell["mode"], warmup=warmup, scheduled_order=order,
                        a_ns=a, b_ns=a + 1_000_000, s_ns=a + 2_000_000,
                        f_ns=a + 5_000_000, l_ns=a + 132_000_000,
                        d_ns=a + 135_000_000, end_ns=a + 135_000_000,
                        evidence_class="provider_candidate",
                    )
                    if cell["mode"] == "fixed_output":
                        item["input_tokens"] = cell["input_tokens"]
                    else:
                        item.update({
                            "input_tokens": 64, "stop_reason": "stop", "fixed_length_valid": None,
                            "schema_valid": True, "semantic_correct": True, "nontruncated": True,
                            "quality_task_id": f"quality-{order:02d}",
                        })
                    records.append(item); group.append(item)
                key = (block["block_id"], cell_id, warmup)
                group_hashes[key] = digest(group)
                add("warmup-complete" if warmup else "cell-complete", {
                    "resource_identity_sha256": RESOURCE, "block_id": block["block_id"],
                    "cell_id": cell_id, "scheduled": count, "failed": 0,
                    "records_sha256": group_hashes[key],
                    "startup_attempt_id_sha256": startup_attempt,
                    "process_identity_sha256": process_identity,
                })
        add("block-stop", {
            "resource_identity_sha256": RESOURCE, "block_id": block["block_id"],
            "startup_attempt_id_sha256": startup_attempt,
            "process_identity_sha256": process_identity,
            "descendants_absent": True, "gpu_memory_recovered": True,
        })
    records_artifact = seal({
        "schema_version": "episode1.private-records.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"], "records": records,
    })
    telemetry = seal({
        "schema_version": "episode1.private-telemetry.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"],
        "summaries": [{
            "block_id": block["block_id"], "runtime": block["runtime"],
            "series_id": "native-queue", "source_kind": "native", "labels": {},
            "metric_name": "native.queue_depth", "kind": "gauge", "status": "unavailable",
            "value": None, "unavailable_reason": "unsupported", "expected_samples": 10,
            "observed_samples": 0, "missing_samples": 10, "samples_sha256": "a" * 64,
        } for block in plan["blocks"]],
    })
    add("essential-export-complete", {
        "resource_identity_sha256": RESOURCE, "records_sha256": records_artifact["artifact_sha256"],
        "telemetry_sha256": telemetry["artifact_sha256"],
    })
    cleanup_receipts = []
    def provider_call(role, method, path, status, started, completed, raw, **extra):
        value = {
            "schema_version": "episode1.provider-call-evidence.v1",
            "role": role, "delete_attempt":2, "run_id": RUN, "attempt_id": ATTEMPT,
            "plan_sha256": plan["plan_sha256"],
            "resource_identity_sha256": RESOURCE,
            "ownership_identity_sha256": ownership,
            "http_method": method, "request_path": path, "request_query": {},
            "http_status": status, "request_started_monotonic_ns": started,
            "body_complete_monotonic_ns": completed,
            "absolute_deadline_monotonic_ns": hard_deadline,
            "operation_deadline_monotonic_ns": completed + 500_000_000,
            "raw_body_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_body_base64": base64.b64encode(raw).decode("ascii"),
            **extra,
        }
        return seal(value)

    cleanup_base = now
    delete_raw = b""
    delete_evidence = provider_call(
        "delete-response", "DELETE", f"/pods/{private_id}", 204,
        cleanup_base + 100_000_000, cleanup_base + 1_000_000_000, delete_raw,
    )
    inventory_page_raw = canonical_json({
        "pagination": {"hasNextPage": False, "nextCursor": None}, "pods": [],
    }).encode()
    inventory_page = provider_call(
        "inventory-page", "GET", "/pods", 200,
        cleanup_base + 1_100_000_000, cleanup_base + 2_000_000_000,
        inventory_page_raw, sequence=1, request_cursor=None,
        has_next_page=False, next_cursor=None,
    )
    inventory_page["request_query"] = {"includeClusterPods": "true", "limit": "1000"}
    inventory_page = reseal(inventory_page)
    inventory_evidence = seal({
        "schema_version": "episode1.provider-inventory-evidence.v1",
        "role": "inventory-after-delete", "delete_attempt":2, "run_id": RUN, "attempt_id": ATTEMPT,
        "plan_sha256": plan["plan_sha256"],
        "resource_identity_sha256": RESOURCE,
        "ownership_identity_sha256": ownership,
        "absolute_deadline_monotonic_ns": hard_deadline,
        "pages": [inventory_page], "terminal_page_sequence": 1,
        "terminal_next_cursor": None, "complete": True, "resource_absent": True,
    })
    inventory_raw = canonical_json(inventory_evidence).encode()
    direct_raw = b""
    direct_evidence = provider_call(
        "direct-after-delete", "GET", f"/pods/{private_id}", 404,
        cleanup_base + 2_100_000_000, cleanup_base + 3_000_000_000, direct_raw,
    )
    def cleanup_receipt(kind, status, complete, absent, response_hash):
        body = {
            "schema_version": "episode1.provider-receipt.v1", "kind": kind,
            "delete_attempt":2,
            "run_id": RUN, "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"],
            "resource_identity_sha256": RESOURCE, "observed_monotonic_ns": now + 1_000_000_000,
            "provider_response_sha256": response_hash, "status": status,
            "complete": complete, "resource_absent": absent,
        }
        body["receipt_sha256"] = digest(body)
        cleanup_receipts.append(body)
        return body
    delete = cleanup_receipt("delete_ack", "acknowledged", None, None, hashlib.sha256(delete_raw).hexdigest())
    add("delete-ack", {"resource_identity_sha256": RESOURCE, "provider_receipt_sha256": delete["receipt_sha256"],"delete_attempt":2})
    inventory = cleanup_receipt("inventory_read", "complete", True, True, hashlib.sha256(inventory_raw).hexdigest())
    add("inventory-read", {"resource_identity_sha256": RESOURCE, "provider_receipt_sha256": inventory["receipt_sha256"], "complete": True, "resource_absent": True,"delete_attempt":2})
    direct = cleanup_receipt("direct_read", "not_found", None, None, hashlib.sha256(direct_raw).hexdigest())
    add("direct-read", {"resource_identity_sha256": RESOURCE, "provider_receipt_sha256": direct["receipt_sha256"], "status": "not_found","delete_attempt":2})
    add("capture-closed", {"resource_identity_sha256": RESOURCE})
    cleanup = seal({
        "schema_version": "episode1.provider-cleanup.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"], "receipts": cleanup_receipts,
    })
    provider_artifacts = seal({
        "schema_version": "episode1.provider-artifacts.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"],
        "artifacts": [
            {"role": "delete-response", "encoding": "base64",
             "raw_base64": base64.b64encode(delete_raw).decode("ascii"),
             "raw_sha256": hashlib.sha256(delete_raw).hexdigest(),
             "bytes": len(delete_raw), "evidence": delete_evidence},
            {"role": "inventory-after-delete", "encoding": "base64",
             "raw_base64": base64.b64encode(inventory_raw).decode("ascii"),
             "raw_sha256": hashlib.sha256(inventory_raw).hexdigest(),
             "bytes": len(inventory_raw), "evidence": inventory_evidence},
            {"role": "direct-after-delete", "encoding": "base64",
             "raw_base64": base64.b64encode(direct_raw).decode("ascii"),
             "raw_sha256": hashlib.sha256(direct_raw).hexdigest(),
             "bytes": len(direct_raw), "evidence": direct_evidence},
        ],
    })
    ledger = seal({
        "schema_version": "episode1.private-ledger-artifact.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"], "entries": events,
    })
    settlement = seal({
        "schema_version": "episode1.cost-settlement.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"],
        "status": "provisional" if provisional else "settled",
        "observed_total_usd": None if provisional else "4.125000",
        "reason": "pending_provider_settlement" if provisional else None,
        "billing_source_sha256": None if provisional else "4" * 64,
    })
    sources = seal({
        "schema_version": "episode1.immutable-sources.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"],
        "source_commit": plan["source_commit"], "protocol_sha256": plan["protocol_sha256"],
        "material_sha256": plan["material_sha256"],
        "collector_sha256": plan["capture"]["collector_sha256"],
        "private_schema_sha256": plan["capture"]["private_schema_sha256"],
        "runtime_builds": [{
            "runtime": item["runtime"], "build_spec_sha256": item["build_spec_sha256"],
            "dependency_lock_sha256": item["dependency_lock_sha256"],
            "launcher_sha256": item["launcher_sha256"],
            "build_attestation_sha256": item["build_attestation_sha256"],
            "image_digest": item["derived_image_digest"],
        } for item in plan["runtime_builds"]],
    })
    manifest = seal({
        "schema_version": "episode1.evidence-manifest.v1", "run_id": RUN,
        "attempt_id": ATTEMPT, "plan_sha256": plan["plan_sha256"],
        "protocol_sha256": plan["protocol_sha256"], "material_sha256": plan["material_sha256"],
        "source_commit": plan["source_commit"], "image_digest": plan["runtime_builds"][0]["derived_image_digest"],
        "collector_sha256": plan["capture"]["collector_sha256"],
        "private_schema_sha256": plan["capture"]["private_schema_sha256"],
        "records_sha256": records_artifact["artifact_sha256"],
        "telemetry_sha256": telemetry["artifact_sha256"],
        "sources_sha256": sources["artifact_sha256"],
        "cleanup_sha256": cleanup["artifact_sha256"],
        "approval_sha256": approval["artifact_sha256"], "ledger_sha256": ledger["artifact_sha256"],
        "settlement_sha256": settlement["artifact_sha256"],
        "allocation_authority_sha256":allocation_authority["artifact_sha256"],
        "resource_identity_sha256": RESOURCE, "start_monotonic_ns": START,
        "provider_private_id": private_id,
        "provider_ownership_identity_sha256": ownership,
        "hard_deadline_monotonic_ns": hard_deadline,
    })
    return {"manifest": manifest, "allocation_authority":allocation_authority,
            "sources": sources, "approval": approval,
            "records": records_artifact, "telemetry": telemetry, "cleanup": cleanup,
            "provider_artifacts": provider_artifacts, "ledger": ledger,
            "settlement": settlement}


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.plan = ready_plan()
        self.bundle = make_bundle(self.plan)

    def promote(self, bundle=None, plan=None):
        return promote_private_evidence(plan=plan or self.plan, bundle=bundle or self.bundle)

    def test_complete_private_evidence_promotes_and_provisional_cost_is_honest(self):
        result = self.promote()
        self.assertEqual(600, result["record_count"])
        self.assertEqual("private_provider_measurement", result["classification"])
        self.assertEqual("provisional", result["cost_status"])
        self.assertEqual({"provider_measurement"}, {r["evidence_class"] for r in result["records"]})
        self.assertEqual({"provider_candidate"}, {r["evidence_class"] for r in self.bundle["records"]["records"]})

    def test_sanitized_allocation_authority_cannot_be_rebound(self):
        bad = copy.deepcopy(self.bundle)
        authority = bad["allocation_authority"]
        authority["private_id"] = "pod-rebound"
        authority["immutable_allocation"]["private_id"] = "pod-rebound"
        authority["immutable_allocation_sha256"] = digest(authority["immutable_allocation"])
        authority["resource_identity_sha256"] = digest({
            "provider": authority["provider"], "private_id": authority["private_id"],
            "unique_name": authority["unique_name"],
            "ownership_token_sha256": authority["ownership_token_sha256"],
            "billing_started_monotonic": authority["billing_started_monotonic"],
        })
        authority["ownership_identity_sha256"] = digest({
            "provider": authority["provider"], "private_id": authority["private_id"],
            "unique_name": authority["unique_name"],
            "ownership_token_sha256": authority["ownership_token_sha256"],
            "billing_started_monotonic_ns": authority["billing_started_monotonic_ns"],
        })
        bad["allocation_authority"] = reseal(authority)
        with self.assertRaisesRegex(PromotionError, "allocation authority identity link mismatch"):
            self.promote(bad)

    def _replace_allocation_images(self, requested, provider):
        bad = copy.deepcopy(self.bundle)
        authority = bad["allocation_authority"]
        authority["immutable_allocation"]["requested_image_reference"] = requested
        authority["immutable_allocation"]["provider_image_reference"] = provider
        authority["immutable_allocation_sha256"] = digest(authority["immutable_allocation"])
        bad["allocation_authority"] = reseal(authority)
        bad["manifest"]["allocation_authority_sha256"] = bad["allocation_authority"]["artifact_sha256"]
        owned = next(item for item in bad["ledger"]["entries"] if item["event"] == "allocation-owned")
        owned["details"]["immutable_allocation_sha256"] = authority["immutable_allocation_sha256"]
        owned["details"]["allocation_authority_sha256"] = bad["allocation_authority"]["artifact_sha256"]
        rechain(bad)
        return bad

    def test_allocation_image_reference_must_use_approved_digest(self):
        wrong = "registry.invalid/episode1@sha256:" + "f" * 64
        bad = self._replace_allocation_images(wrong, wrong)
        with self.assertRaisesRegex(PromotionError, "image reference mismatch"):
            self.promote(bad)

    def test_provider_image_reference_must_equal_requested_reference(self):
        requested = self.bundle["allocation_authority"]["immutable_allocation"]["requested_image_reference"]
        provider = "registry.invalid/episode1@sha256:" + "f" * 64
        bad = self._replace_allocation_images(requested, provider)
        with self.assertRaisesRegex(PromotionError, "image reference mismatch"):
            self.promote(bad)

    def test_provider_proofs_cannot_mix_delete_attempts(self):
        bad = copy.deepcopy(self.bundle)
        direct = next(item for item in bad["provider_artifacts"]["artifacts"]
            if item["role"] == "direct-after-delete")
        direct["evidence"]["delete_attempt"] = 3
        direct["evidence"] = reseal(direct["evidence"])
        bad["provider_artifacts"] = reseal(bad["provider_artifacts"])
        with self.assertRaisesRegex(PromotionError, "mixes delete attempts"):
            self.promote(bad)

    def test_settled_cost_is_separate_and_accepted(self):
        result = self.promote(make_bundle(self.plan, provisional=False))
        self.assertEqual("settled", result["cost_status"])

    def test_settlement_must_be_in_manifest_inventory(self):
        bad = copy.deepcopy(self.bundle)
        bad["settlement"] = make_bundle(self.plan, provisional=False)["settlement"]
        with self.assertRaisesRegex(PromotionError, "inventory mismatch"):
            self.promote(bad)

    def test_allocation_cannot_predate_original_start(self):
        bad = copy.deepcopy(self.bundle)
        bad["ledger"]["entries"][0]["monotonic_ns"] = START - 1
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "outside the original lifetime"):
            self.promote(bad)

    def test_fixed_tokens_must_be_known_and_exact(self):
        bad = copy.deepcopy(self.bundle)
        bad["records"]["records"][0]["input_tokens"] = None
        bad["records"] = reseal(bad["records"])
        with self.assertRaisesRegex(PromotionError, "exact token contract"):
            self.promote(bad)

    def test_failure_cannot_be_hidden_by_zero_failed_ledger_count(self):
        bad = copy.deepcopy(self.bundle)
        bad["records"]["records"][0].update(status="timeout", reason_code="request_deadline")
        bad["records"] = reseal(bad["records"])
        with self.assertRaisesRegex(PromotionError, "failed captures"):
            self.promote(bad)

    def test_telemetry_summary_bounds_must_agree(self):
        bad = copy.deepcopy(self.bundle)
        summary = bad["telemetry"]["summaries"][0]
        summary.update(status="available", value={"minimum": 5, "mean": 1, "maximum": 3},
                       unavailable_reason=None, expected_samples=3, observed_samples=3, missing_samples=0)
        bad["telemetry"] = reseal(bad["telemetry"])
        with self.assertRaisesRegex(PromotionError, "bounds are inconsistent"):
            self.promote(bad)

    def test_distinct_series_ids_cannot_duplicate_actual_source_selector(self):
        bad = copy.deepcopy(self.bundle)
        duplicate = copy.deepcopy(bad["telemetry"]["summaries"][0])
        duplicate["series_id"] = "caller-renamed-series"
        bad["telemetry"]["summaries"].append(duplicate)
        bad["telemetry"] = reseal(bad["telemetry"])
        bad["manifest"]["telemetry_sha256"] = bad["telemetry"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "duplicate telemetry source identity"):
            self.promote(bad)

    def test_counter_actual_interval_tamper_is_rejected(self):
        bad = copy.deepcopy(self.bundle)
        summary = bad["telemetry"]["summaries"][0]
        summary.update(kind="counter", unit="tokens",
            counter_semantics="delta_over_actual_bracketing_interval",
            first_sample_monotonic_ns=100, last_sample_monotonic_ns=1_000_000_100,
            coverage="sampled_interval_covering_window", status="available",
            value={"first":10.0,"last":20.0,"delta":10.0,
                   "rate_per_second":5.0,"elapsed_seconds":2.0},
            unavailable_reason=None,expected_samples=2,observed_samples=2,missing_samples=0)
        bad["telemetry"] = reseal(bad["telemetry"])
        bad["manifest"]["telemetry_sha256"] = bad["telemetry"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "counter interval is inconsistent"):
            self.promote(bad)

    def test_one_pre_warmup_startup_retry_is_accepted_and_preserved(self):
        bundle = make_bundle(self.plan, retry_blocks={0})
        result = self.promote(bundle)
        self.assertEqual(600, result["record_count"])
        self.assertEqual(
            ["startup-failed", "failed-start-cleanup", "block-start"],
            [entry["event"] for entry in bundle["ledger"]["entries"][1:4]],
        )
        self.assertEqual(0, bundle["ledger"]["entries"][1]["details"]["warmup_records"])
        self.assertEqual(0, bundle["ledger"]["entries"][1]["details"]["measured_records"])

    def test_more_than_one_startup_retry_is_rejected(self):
        with self.assertRaisesRegex(PromotionError, "global limit"):
            self.promote(make_bundle(self.plan, retry_blocks={0, 1}))

    def test_failed_start_cannot_contain_traffic_or_skip_cleanup(self):
        bad = make_bundle(self.plan, retry_blocks={0})
        failed = next(e for e in bad["ledger"]["entries"] if e["event"] == "startup-failed")
        failed["details"]["warmup_records"] = 1
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "contains traffic"):
            self.promote(bad)

        bad = make_bundle(self.plan, retry_blocks={0})
        cleanup = next(e for e in bad["ledger"]["entries"] if e["event"] == "failed-start-cleanup")
        cleanup["details"]["descendants_absent"] = False
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "did not restore"):
            self.promote(bad)

    def test_retry_after_any_warmup_or_measurement_is_rejected(self):
        bad = make_bundle(self.plan, retry_blocks={0})
        entries = bad["ledger"]["entries"]
        retry_events = [entries.pop(1), entries.pop(1), entries.pop(1)]
        insert_after = next(i for i, entry in enumerate(entries) if entry["event"] == "cell-complete") + 1
        entries[insert_after:insert_after] = retry_events
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "lifecycle order|event count"):
            self.promote(bad)

    def test_provider_create_retry_event_is_rejected(self):
        bad = copy.deepcopy(self.bundle)
        injected = copy.deepcopy(bad["ledger"]["entries"][0])
        injected["event"] = "allocation-create-retry"
        bad["ledger"]["entries"].insert(1, injected)
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "event count"):
            self.promote(bad)

    def test_retry_attempt_and_process_bindings_are_enforced(self):
        bad = make_bundle(self.plan, retry_blocks={0})
        failed = next(e for e in bad["ledger"]["entries"] if e["event"] == "startup-failed")
        failed["details"]["startup_attempt_id_sha256"] = "9" * 64
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "failed startup evidence"):
            self.promote(bad)

    def test_blocked_plan_cannot_promote(self):
        blocked = compile_execution_candidate(protocol(), inputs(ready=False))
        with self.assertRaisesRegex(PromotionError, "execution-ready"):
            promote_private_evidence(plan=blocked, bundle=self.bundle)

    def test_artifact_byte_tamper_is_detected(self):
        bad = copy.deepcopy(self.bundle)
        bad["records"]["records"][0]["request_id"] = "tampered"
        with self.assertRaisesRegex(PromotionError, "hash mismatch"):
            self.promote(bad)

    def test_missing_record_fails_even_after_attacker_rehashes_artifacts(self):
        bad = copy.deepcopy(self.bundle)
        bad["records"]["records"].pop()
        bad["records"] = reseal(bad["records"])
        bad["manifest"]["records_sha256"] = bad["records"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "incomplete scheduled attempts"):
            self.promote(bad)

    def test_authored_quality_task_order_is_recomputed(self):
        bad = copy.deepcopy(self.bundle)
        natural = [r for r in bad["records"]["records"] if r["cell_id"] == "natural-quality" and not r["warmup"]]
        natural[1]["quality_task_id"] = natural[0]["quality_task_id"]
        bad["records"] = reseal(bad["records"])
        bad["manifest"]["records_sha256"] = bad["records"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "authored schedule"):
            self.promote(bad)

    def test_ledger_chain_and_exact_event_order_are_enforced(self):
        bad = copy.deepcopy(self.bundle)
        bad["ledger"]["entries"][3], bad["ledger"]["entries"][4] = bad["ledger"]["entries"][4], bad["ledger"]["entries"][3]
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "lifecycle order|identity mismatch"):
            self.promote(bad)

    def test_records_must_occur_in_each_ledger_cell_window(self):
        bad = copy.deepcopy(self.bundle)
        target = next(r for r in bad["records"]["records"] if r["block_id"] == "block-02")
        shift = target["a_ns"] - (START + 1)
        for field in ("a_ns", "b_ns", "s_ns", "f_ns", "l_ns", "d_ns", "end_ns"):
            target[field] -= shift
        bad["records"] = reseal(bad["records"])
        bad["manifest"]["records_sha256"] = bad["records"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "cell receipt"):
            self.promote(bad)

    def test_same_attempt_fresh_cleanup_is_enforced(self):
        bad = copy.deepcopy(self.bundle)
        direct = next(e for e in bad["ledger"]["entries"] if e["event"] == "direct-read")
        direct["monotonic_ns"] = bad["manifest"]["hard_deadline_monotonic_ns"] + 1
        receipt = next(r for r in bad["cleanup"]["receipts"] if r["kind"] == "direct_read")
        receipt["observed_monotonic_ns"] = direct["monotonic_ns"]
        body = dict(receipt); body.pop("receipt_sha256")
        receipt["receipt_sha256"] = digest(body)
        direct["details"]["provider_receipt_sha256"] = receipt["receipt_sha256"]
        bad["cleanup"] = reseal(bad["cleanup"])
        bad["manifest"]["cleanup_sha256"] = bad["cleanup"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        closed = next(e for e in bad["ledger"]["entries"] if e["event"] == "capture-closed")
        closed["monotonic_ns"] = direct["monotonic_ns"] + 1
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "after the original deadline"):
            self.promote(bad)

    def test_cleanup_scalar_claims_and_incomplete_inventory_do_not_pass(self):
        bad = copy.deepcopy(self.bundle)
        inventory = next(e for e in bad["ledger"]["entries"] if e["event"] == "inventory-read")
        inventory["details"]["complete"] = False
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "inventory"):
            self.promote(bad)
        bad = copy.deepcopy(self.bundle)
        bad["fake_cleanup_passed"] = True
        with self.assertRaisesRegex(PromotionError, "fields invalid"):
            self.promote(bad)

    def test_cleanup_receipt_facts_are_recomputed_before_ledger_claims(self):
        bad = copy.deepcopy(self.bundle)
        inventory = next(r for r in bad["cleanup"]["receipts"] if r["kind"] == "inventory_read")
        inventory["resource_absent"] = False
        body = dict(inventory); body.pop("receipt_sha256")
        inventory["receipt_sha256"] = digest(body)
        bad["cleanup"] = reseal(bad["cleanup"])
        bad["manifest"]["cleanup_sha256"] = bad["cleanup"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "does not prove deletion"):
            self.promote(bad)

    def test_unavailable_telemetry_requires_null_reason_and_accounted_slots(self):
        bad = copy.deepcopy(self.bundle)
        bad["telemetry"]["summaries"][0]["value"] = {"minimum": 0, "maximum": 0, "mean": 0}
        bad["telemetry"] = reseal(bad["telemetry"])
        bad["manifest"]["telemetry_sha256"] = bad["telemetry"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "null"):
            self.promote(bad)
        bad = copy.deepcopy(self.bundle)
        bad["telemetry"]["summaries"][0]["missing_samples"] = 9
        bad["telemetry"] = reseal(bad["telemetry"])
        with self.assertRaisesRegex(PromotionError, "sampling slots"):
            self.promote(bad)

    def test_approval_and_source_bindings_are_recomputed(self):
        bad = copy.deepcopy(self.bundle)
        bad["approval"]["spend_approval"] += " "
        bad["approval"] = reseal(bad["approval"])
        bad["manifest"]["approval_sha256"] = bad["approval"]["artifact_sha256"]
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "does not authorize"):
            self.promote(bad)
        bad = copy.deepcopy(self.bundle)
        bad["manifest"]["source_commit"] = "0" * 40
        bad["manifest"] = reseal(bad["manifest"])
        with self.assertRaisesRegex(PromotionError, "material/source"):
            self.promote(bad)

    def test_six_distinct_process_identities_are_required(self):
        bad = copy.deepcopy(self.bundle)
        starts = [e for e in bad["ledger"]["entries"] if e["event"] == "block-start"]
        starts[1]["details"]["process_id_sha256"] = starts[0]["details"]["process_id_sha256"]
        starts[1]["details"]["process_start_identity_sha256"] = starts[0]["details"]["process_start_identity_sha256"]
        rechain(bad)
        with self.assertRaisesRegex(PromotionError, "process is reused"):
            self.promote(bad)


if __name__ == "__main__":
    unittest.main()
