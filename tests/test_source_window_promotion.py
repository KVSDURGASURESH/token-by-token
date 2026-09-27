import hashlib
import unittest

try:
    from runpod_benchmark.episode1_promotion import promote_private_evidence, seal
except ImportError:
    from evidence_promotion import promote_private_evidence, seal
try:
    from runpod_benchmark.source_window import canonical, summarize_system_source_window
except ImportError:
    from source_window import canonical, summarize_system_source_window
from test_episode1_promotion import make_bundle, ready_plan, rechain
from test_source_window import _case


def _source_window_for_bundle(plan, bundle, block):
    rows, base = _case()
    start, end = base["start_receipt"], base["end_receipt"]
    runtime = block["runtime"]
    for row in rows:
        row["binding"].update(run_id="run-20260922", attempt_id="attempt-01",
                              block=block["block_id"])
        if row["process_expected"] is not None:
            row["process_expected"]["role"] = runtime
    source = b"".join(canonical(row) + b"\n" for row in rows)
    measured = [record for record in bundle["records"]["records"]
                if record["block_id"] == block["block_id"] and record["warmup"] is False]
    first_a = min(record["a_ns"] for record in measured)
    last_end = max(record["end_ns"] for record in measured)
    for receipt, row in ((start, rows[1]), (end, rows[3])):
        receipt.update(plan_sha256=plan["plan_sha256"], run_id="run-20260922",
                       attempt_id="attempt-01", block=block["block_id"], runtime=runtime,
                       source_record_sha256=hashlib.sha256(canonical(row)+b"\n").hexdigest())
    start.update(client_call_started_monotonic_ns=first_a-200,
                 client_call_completed_monotonic_ns=first_a-100)
    end.update(client_call_started_monotonic_ns=last_end+100,
               client_call_completed_monotonic_ns=last_end+200)
    return summarize_system_source_window(
        source=source, start_receipt=start, end_receipt=end,
        plan_sha256=plan["plan_sha256"], run_id="run-20260922", attempt_id="attempt-01",
        block=block["block_id"], runtime=runtime, pid=77, start_ticks=9,
        metric_name="rss_bytes", kind="gauge",
        labels={"source":"proc","unit":"bytes","scope":"process"},
        max_sampling_gap_ns=200, first_measured_a_ns=first_a,
        last_measured_end_ns=last_end)


class SourceWindowPromotionTests(unittest.TestCase):
    def test_600_record_bundle_with_actual_source_window_promotes(self):
        plan = ready_plan()
        bundle = make_bundle(plan)
        for actual, expected in zip(bundle["sources"]["runtime_builds"],
                                    plan["runtime_builds"], strict=True):
            actual["build_attestation_sha256"] = expected["build_attestation_sha256"]
        bundle["sources"] = seal({key:value for key,value in bundle["sources"].items()
                                  if key != "artifact_sha256"})
        bundle["manifest"]["sources_sha256"] = bundle["sources"]["artifact_sha256"]
        block = plan["blocks"][0]
        derived = _source_window_for_bundle(plan, bundle, block)
        bundle["telemetry"]["summaries"][0] = {
            "block_id": block["block_id"], "runtime": block["runtime"], **derived,
        }
        bundle["telemetry"] = seal({key:value for key,value in bundle["telemetry"].items()
                                    if key != "artifact_sha256"})
        bundle["manifest"]["telemetry_sha256"] = bundle["telemetry"]["artifact_sha256"]
        for entry in bundle["ledger"]["entries"]:
            if entry["event"] == "essential-export-complete":
                entry["details"]["telemetry_sha256"] = bundle["telemetry"]["artifact_sha256"]
        rechain(bundle)
        result = promote_private_evidence(plan=plan, bundle=bundle)
        self.assertEqual(result["record_count"],600)
        self.assertEqual(result["cost_status"],"provisional")
        self.assertEqual(result["telemetry_status"],"validated_with_explicit_unavailability")


if __name__ == "__main__":
    unittest.main()
