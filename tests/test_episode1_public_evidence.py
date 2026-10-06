from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_BUNDLE = ROOT / "dashboard" / "src" / "data" / "episode-1-public.v1.json"
SCHEMA = ROOT / "schemas" / "public-inference-evidence.v1.schema.json"

EXPECTED = {
    ("vLLM", 12): {
        "output_tps": 374.7588238735019,
        "ttft_p50_ms": 2327.0245,
        "ttft_p95_ms": 14548.081291,
        "tpot_p50_ms": 36.749324468085106,
        "decode_p10_tps": 21.647357597927805,
        "error_rate_pct": 0.1557632398753894,
        "running_requests_mean": 15.533333333333333,
        "waiting_requests_mean": 0.03333333333333333,
        "gpu_utilization_pct": 100.0,
        "gpu_memory_gib": 133.58978271484375,
        "gpu_power_w": 591.2128666666667,
    },
    ("vLLM", 16): {
        "output_tps": 376.7270594950265,
        "ttft_p50_ms": 2789.812041,
        "ttft_p95_ms": 17179.270167,
        "tpot_p50_ms": 49.54259679797979,
        "decode_p10_tps": 15.959221959779452,
        "error_rate_pct": 0.15015015015015015,
        "running_requests_mean": 23.266666666666666,
        "waiting_requests_mean": 0.03333333333333333,
        "gpu_utilization_pct": 99.91666666666667,
        "gpu_memory_gib": 133.58978271484375,
        "gpu_power_w": 600.8785833333333,
    },
    ("vLLM", 24): {
        "output_tps": 379.4803156121838,
        "ttft_p50_ms": 5455.011208,
        "ttft_p95_ms": 30787.455542,
        "tpot_p50_ms": 74.48276938613861,
        "decode_p10_tps": 9.581166807869453,
        "error_rate_pct": 0.0,
        "running_requests_mean": 36.61666666666667,
        "waiting_requests_mean": 0.2,
        "gpu_utilization_pct": 100.0,
        "gpu_memory_gib": 133.58978271484375,
        "gpu_power_w": 629.8228833333334,
    },
    ("SGLang", 12): {
        "output_tps": 497.36994127360805,
        "ttft_p50_ms": 1667.396959,
        "ttft_p95_ms": 8229.3205,
        "tpot_p50_ms": 20.63596386725664,
        "decode_p10_tps": 33.005161580540744,
        "error_rate_pct": 0.0,
        "running_requests_mean": 13.716666666666667,
        "waiting_requests_mean": 0.05,
        "gpu_utilization_pct": 98.86666666666666,
        "gpu_memory_gib": 125.672119140625,
        "gpu_power_w": 671.2198666666667,
    },
    ("SGLang", 16): {
        "output_tps": 480.43621543584874,
        "ttft_p50_ms": 2041.941292,
        "ttft_p95_ms": 9764.01125,
        "tpot_p50_ms": 27.706553358574613,
        "decode_p10_tps": 17.482769989167465,
        "error_rate_pct": 0.0,
        "running_requests_mean": 19.05,
        "waiting_requests_mean": 0.5833333333333334,
        "gpu_utilization_pct": 97.73333333333333,
        "gpu_memory_gib": 125.672119140625,
        "gpu_power_w": 682.3903999999999,
    },
    ("SGLang", 24): {
        "output_tps": 365.3459253216277,
        "ttft_p50_ms": 5451.441167,
        "ttft_p95_ms": 30014.645167,
        "tpot_p50_ms": 68.29774684126984,
        "decode_p10_tps": 8.162312232411331,
        "error_rate_pct": 0.0,
        "running_requests_mean": 34.516666666666666,
        "waiting_requests_mean": 1.2,
        "gpu_utilization_pct": 99.26666666666667,
        "gpu_memory_gib": 125.676025390625,
        "gpu_power_w": 692.1702000000001,
    },
}


class Episode1PublicEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PUBLIC_BUNDLE.exists():
            raise AssertionError("Episode 01 public evidence bundle is missing")
        cls.bundle = json.loads(PUBLIC_BUNDLE.read_text(encoding="utf-8"))

    def test_bundle_matches_closed_schema(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(self.bundle)

    def test_every_approved_aggregate_reconciles_exactly(self):
        points = {
            (arm["engine"], point["users"]): point
            for arm in self.bundle["arms"]
            for point in arm["points"]
        }
        self.assertEqual(set(points), set(EXPECTED))
        for key, metrics in EXPECTED.items():
            with self.subTest(engine=key[0], users=key[1]):
                readings = points[key]["readings"]
                for metric, expected in metrics.items():
                    self.assertEqual(readings[metric]["value"], expected)
                self.assertFalse(readings["cache_context"]["available"])
                self.assertIsNone(readings["cache_context"]["value"])

    def test_claim_states_and_capacity_boundary_are_explicit(self):
        self.assertEqual(self.bundle["methodology"]["decode_threshold_tps"], 20.0)
        self.assertFalse(self.bundle["methodology"]["ttft_gated"])
        self.assertEqual(self.bundle["methodology"]["capacity_state"], "not_established")
        states = {
            (arm["engine"], point["users"]): point["readings"]["decode_p10_tps"]["evidence_state"]
            for arm in self.bundle["arms"]
            for point in arm["points"]
        }
        self.assertEqual(states[("vLLM", 12)], "threshold_met")
        self.assertEqual(states[("SGLang", 12)], "threshold_met")
        for key in set(EXPECTED) - {("vLLM", 12), ("SGLang", 12)}:
            self.assertEqual(states[key], "threshold_missed")

    def test_synchronized_series_cover_every_lane_engine_and_load(self):
        series = self.bundle["synchronized_series"]
        observed = {(item["lane"], item["engine"], item["users"]) for item in series}
        expected = {
            (lane, engine, users)
            for lane in ("client", "engine", "gpu")
            for engine, users in EXPECTED
        }
        self.assertTrue(expected.issubset(observed))
        for item in series:
            self.assertGreaterEqual(len(item["samples"]), 2)
            offsets = [sample[0] for sample in item["samples"]]
            self.assertEqual(offsets, sorted(offsets))
            self.assertGreaterEqual(offsets[0], 0)
            self.assertLessEqual(offsets[-1], 300)

    def test_bundle_contains_no_private_metadata_or_excluded_level(self):
        serialized = json.dumps(self.bundle, sort_keys=True).lower()
        forbidden = (
            "/users/",
            "run_id",
            "commit",
            "profile",
            "configuration",
            "base_url",
            "service_instance",
            "agentbench",
            "mirastacklabs",
            "runpod",
        )
        for token in forbidden:
            self.assertNotIn(token, serialized)
        self.assertNotRegex(serialized, r'"users"\s*:\s*14(?:\D|$)')


if __name__ == "__main__":
    unittest.main()
