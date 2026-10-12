import copy
import json
import tempfile
import unittest
from pathlib import Path

from runpod_benchmark.episode1 import (
    CELLS,
    SCHEMA_VERSION,
    append_phase,
    authored_quality_corpus,
    exact_token_filler,
    evaluate_quality,
    export_public_fixture,
    paired_block_schedule,
    protocol,
    sha256_json,
    summarize_cell,
    validate_observation,
    verify_protocol,
    verify_phase_ledger,
)


def observation(**changes):
    value = {
        "schema_version": SCHEMA_VERSION, "evidence_class": "local_fixture",
        "request_id": "request-1", "block_id": "block-01", "pair_id": "pair-1",
        "runtime": "vllm-0.29.0", "cell_id": "fixed-short", "mode": "fixed_output",
        "warmup": False, "scheduled_order": 1, "clock_domain": "client_monotonic_ns",
        "a_ns": 0, "b_ns": 1_000_000, "s_ns": 2_000_000, "f_ns": 5_000_000,
        "l_ns": 132_000_000, "d_ns": 135_000_000, "end_ns": 135_000_000,
        "content_event_count": 32, "interchunk_gaps_ns": [4_000_000] * 31,
        "input_tokens": 512, "output_tokens": 128, "streamed_usage_output_tokens": 128,
        "tokenizer_output_tokens": 128, "stop_reason": "length", "status": "success",
        "reason_code": "none", "fixed_length_valid": True, "schema_valid": None,
        "semantic_correct": None, "nontruncated": None, "quality_task_id": None,
    }
    value.update(changes)
    return value


class Episode1ContractTests(unittest.TestCase):
    def test_protocol_is_bounded_and_never_authorizes_execution(self):
        value = protocol("a" * 64, "b" * 64)
        self.assertFalse(value["execution_ready"])
        self.assertIsNone(value["approval_phrase"])
        self.assertEqual(value["totals"], {"measured_requests": 528, "fixed_requests": 384, "natural_requests": 144, "warmups": 72})
        self.assertEqual([block["runtime"] for block in paired_block_schedule()], [
            "vllm-0.29.0", "sglang-0.5.20", "sglang-0.5.20",
            "vllm-0.29.0", "vllm-0.29.0", "sglang-0.5.20",
        ])
        claimed = value.pop("protocol_sha256")
        self.assertEqual(claimed, sha256_json(value))

    def test_protocol_digest_changes_with_material_contract_change(self):
        first = protocol("a" * 64, "b" * 64)
        second = protocol("a" * 64, "b" * 64)
        second["cells"][0]["requests"] = 33
        self.assertNotEqual(first["protocol_sha256"], sha256_json({k: v for k, v in second.items() if k != "protocol_sha256"}))
        with self.assertRaises(ValueError):
            verify_protocol(second)

    def test_corpus_is_24_unique_authored_tasks(self):
        corpus = authored_quality_corpus()
        self.assertEqual(len(corpus), 24)
        self.assertEqual(len({task["task_id"] for task in corpus}), 24)
        self.assertTrue(all(json.loads(task["gold_json"])["ticket"].startswith("LAB-") for task in corpus))

    def test_exact_token_filler_succeeds_or_fails_closed(self):
        encode = lambda text: text.split()
        text = exact_token_filler("one two", 5, encode)
        self.assertEqual(len(encode(text)), 5)
        with self.assertRaises(ValueError):
            exact_token_filler("one two three", 2, encode)
        with self.assertRaises(ValueError):
            exact_token_filler("one", 3, lambda _: [1])

    def test_quality_evaluator_is_strict_and_does_not_trust_labels(self):
        gold = json.dumps({"ticket": "LAB-001", "service": "billing", "priority": "high"})
        self.assertEqual(evaluate_quality(gold, gold, "eos"), {
            "schema_valid": True, "semantic_correct": True, "nontruncated": True,
        })
        self.assertFalse(evaluate_quality("not json", gold, "eos")["schema_valid"])
        self.assertFalse(evaluate_quality(json.dumps({**json.loads(gold), "extra": "x"}), gold, "eos")["schema_valid"])
        wrong = json.dumps({"ticket": "LAB-999", "service": "billing", "priority": "high"})
        self.assertTrue(evaluate_quality(wrong, gold, "eos")["schema_valid"])
        self.assertFalse(evaluate_quality(wrong, gold, "eos")["semantic_correct"])
        self.assertFalse(evaluate_quality(gold, gold, "length")["nontruncated"])
        self.assertIsNone(evaluate_quality(gold, gold, None)["nontruncated"])

    def test_timestamp_metrics_include_terminal_overhead_and_tpot(self):
        result = validate_observation(observation())
        self.assertEqual(result["derived"]["scheduling_lag_ms"], 1)
        self.assertEqual(result["derived"]["send_preparation_ms"], 1)
        self.assertEqual(result["derived"]["ttft_ms"], 3)
        self.assertEqual(result["derived"]["terminal_overhead_ms"], 3)
        self.assertEqual(result["derived"]["tpot_ms"], 1)

    def test_multi_token_single_chunk_is_flagged_not_token_timing_proof(self):
        result = validate_observation(observation(content_event_count=1, interchunk_gaps_ns=[]))
        self.assertTrue(result["derived"]["coalesced_content"])

    def test_zero_and_one_token_tpot_are_unavailable(self):
        for tokens in (0, 1):
            item = observation(output_tokens=tokens, streamed_usage_output_tokens=tokens,
                               tokenizer_output_tokens=tokens, fixed_length_valid=False,
                               stop_reason="stop")
            self.assertIsNone(validate_observation(item)["derived"]["tpot_ms"])

    def test_closed_schema_token_mismatch_nonfinite_and_time_order_fail(self):
        with self.assertRaises(ValueError):
            validate_observation({**observation(), "raw_text": "must not pass"})
        with self.assertRaises(ValueError):
            validate_observation(observation(tokenizer_output_tokens=127))
        with self.assertRaises(ValueError):
            validate_observation(observation(f_ns=float("nan")))
        with self.assertRaises(ValueError):
            validate_observation(observation(l_ns=1))

    def test_status_mode_and_input_invariants_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_observation(observation(status="success", reason_code="transport"))
        with self.assertRaises(ValueError):
            validate_observation(observation(input_tokens=999))
        with self.assertRaises(ValueError):
            validate_observation(observation(schema_valid=True))

    def test_goodput_uses_full_wall_with_failure_and_drain(self):
        cell = {**CELLS[0], "requests": 2}
        failed = observation(
            request_id="request-2", scheduled_order=2, a_ns=140_000_000,
            b_ns=None, s_ns=None, f_ns=None, l_ns=None, d_ns=None, end_ns=200_000_000,
            content_event_count=0, interchunk_gaps_ns=[], input_tokens=512, output_tokens=None,
            streamed_usage_output_tokens=None, tokenizer_output_tokens=None, stop_reason="not_started",
            status="unsent", reason_code="not_dispatched", fixed_length_valid=None,
        )
        summary = summarize_cell([observation(), failed], 0, 200_000_000, cell)
        self.assertEqual(summary["counts"]["scheduled"], 2)
        self.assertEqual(summary["counts"]["unsent"], 1)
        self.assertEqual(summary["throughput"]["requests"]["wall_seconds"], .2)
        self.assertEqual(summary["throughput"]["request_goodput"]["value"], 5)

    def test_unknown_quality_makes_natural_goodput_unavailable(self):
        cell = {**CELLS[2], "requests": 1}
        natural = observation(
            cell_id="natural-quality", mode="natural_stop", input_tokens=73,
            output_tokens=4, streamed_usage_output_tokens=4, tokenizer_output_tokens=4,
            stop_reason="eos", fixed_length_valid=None, schema_valid=True,
            semantic_correct=None, nontruncated=True, quality_task_id="quality-01",
        )
        summary = summarize_cell([natural], 0, 135_000_000, cell)
        self.assertFalse(summary["throughput"]["request_goodput"]["available"])
        self.assertIsNone(summary["counts"]["slo_qualified"])

    def test_public_export_rejects_raw_or_paid_fixture_claim(self):
        plan = protocol("a" * 64, "b" * 64)
        cell = {**CELLS[0], "requests": 1}
        summary = summarize_cell([observation()], 0, 135_000_000, cell)
        with self.assertRaises(ValueError):
            export_public_fixture(plan, [summary], [])
        contaminated = {**summary, "endpoint": "https://private.invalid"}
        with self.assertRaises(ValueError):
            export_public_fixture(plan, [contaminated], [])
        paid = copy.deepcopy(summary)
        paid["classification"] = "provider_measurement"
        with self.assertRaises(ValueError):
            export_public_fixture(plan, [paid], [])

    def test_public_export_preserves_legitimate_unknown_goodput(self):
        root = Path(__file__).resolve().parents[1]
        plan = json.loads((root / "fixtures/episode1/episode1-planning.json").read_text())
        public = json.loads((root / "fixtures/episode1/public-aggregate.fixture.json").read_text())
        summaries = copy.deepcopy(public["summaries"])
        natural = next(item for item in summaries if item["cell_id"] == "natural-quality")
        natural["counts"]["slo_qualified"] = None
        natural["counts"]["qualified_output_tokens"] = None
        natural["throughput"]["request_goodput"].update(
            available=False, value=None, unavailable_reason="missing SLO or quality evidence"
        )
        natural["throughput"]["token_goodput"].update(
            available=False, value=None, unavailable_reason="missing SLO, quality, or token evidence"
        )
        exported = export_public_fixture(plan, summaries, public["telemetry"])
        result = next(item for item in exported["summaries"] if item["block_id"] == natural["block_id"] and item["cell_id"] == "natural-quality")
        self.assertIsNone(result["counts"]["slo_qualified"])
        self.assertFalse(result["throughput"]["request_goodput"]["available"])

    def test_public_export_rejects_available_rate_with_null_bound_count(self):
        root = Path(__file__).resolve().parents[1]
        plan = json.loads((root / "fixtures/episode1/episode1-planning.json").read_text())
        public = json.loads((root / "fixtures/episode1/public-aggregate.fixture.json").read_text())
        summaries = copy.deepcopy(public["summaries"])
        summaries[0]["counts"]["successful_output_tokens"] = None
        with self.assertRaisesRegex(ValueError, "availability does not match"):
            export_public_fixture(plan, summaries, public["telemetry"])

    def test_versioned_json_schemas_close_every_declared_object(self):
        root = Path(__file__).resolve().parents[1]
        schemas = sorted((root / "schemas").glob("episode1-*.schema.json"))
        self.assertEqual(len(schemas), 5)

        def assert_closed(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node.get("additionalProperties", True))
                for value in node.values():
                    assert_closed(value)
            elif isinstance(node, list):
                for value in node:
                    assert_closed(value)

        for path in schemas:
            schema = json.loads(path.read_text())
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            assert_closed(schema)
        aggregate = json.loads((root / "schemas/episode1-public-aggregate.schema.json").read_text())
        self.assertEqual(aggregate["properties"]["summaries"]["minItems"], 18)
        self.assertEqual(aggregate["properties"]["summaries"]["maxItems"], 18)

    def test_phase_ledger_detects_tampering_and_fixture_has_no_charge(self):
        ledger = []
        digest = "a" * 64
        phases = ("preflight", "startup", "warmup", "measurement", "export", "teardown", "settlement")
        for index, phase in enumerate(phases):
            append_phase(ledger, phase, index * 1_000_000_000, index * 1_000_000_000 + 1_000_000_000,
                         f"2026-09-22T00:00:{index:02d}Z", f"2026-09-22T00:00:{index + 1:02d}Z",
                         "not_applicable_fixture", None, digest)
        verify_phase_ledger(ledger)
        ledger[0]["phase"] = "startup"
        with self.assertRaises(ValueError):
            verify_phase_ledger(ledger)
        with self.assertRaises(ValueError):
            append_phase([], "preflight", 0, 1_000_000_000, "2026-09-22T00:00:00Z", "2026-09-22T00:00:01Z", "not_applicable_fixture", 0, digest)


if __name__ == "__main__":
    unittest.main()
