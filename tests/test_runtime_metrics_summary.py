import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("summarize_runtime_metrics", ROOT / "scripts/summarize_runtime_metrics.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample(index, metrics, runtime="vllm"):
    return {"runtime": runtime, "monotonic_ns": (index + 1) * 1_000_000_000,
            "observed_at_utc": f"2026-09-21T12:00:{index:02d}Z", "metrics": metrics}


class RuntimeMetricsSummaryTests(unittest.TestCase):
    def test_duplicate_labeled_gauge_series_fail_closed(self):
        from runpod_benchmark.runtime_metrics import snapshot_from_prometheus

        with self.assertRaisesRegex(ValueError, "multiple Prometheus series"):
            snapshot_from_prometheus(
                "vllm",
                'vllm:kv_cache_usage_perc{worker="0"} 0.4\n'
                'vllm:kv_cache_usage_perc{worker="1"} 0.6\n',
                1,
            )

    def read(self, rows, runtime="vllm"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            return MODULE.read_samples(path, runtime)

    def test_collector_contract_and_phase_delta_not_cumulative_mean(self):
        from runpod_benchmark.runtime_metrics import snapshot_from_prometheus
        rows = []
        for index, (duration, count, waiting) in enumerate([(10, 5, 0), (12, 6, 10), (16, 8, 20)]):
            row = snapshot_from_prometheus("vllm", "\n".join([
                f"vllm:request_prefill_time_seconds_sum {duration}",
                f"vllm:request_prefill_time_seconds_count {count}",
                f"vllm:num_requests_waiting {waiting}",
            ]), (index + 1) * 1_000_000_000)
            row["observed_at_utc"] = sample(index, {})["observed_at_utc"]
            rows.append(row)
        result = MODULE.summarize(self.read(rows), "vllm")
        self.assertEqual(result["native_window"]["prefill_seconds_per_request"], 2)
        self.assertEqual(result["metric_samples"]["requests_waiting"]["p95"], 19)
        self.assertEqual(result["observed_sample_interval_seconds"]["mean"], 1)
        self.assertIsNone(result["native_window"]["decode_seconds_per_request"])

    def test_sglang_missing_phase_stays_unavailable(self):
        rows = [sample(0, {"kv_cache_usage": 0.5}, "sglang")]
        result = MODULE.summarize(self.read(rows, "sglang"), "sglang")
        self.assertIsNone(result["native_window"]["prefill_seconds_per_request"])
        self.assertIsNone(result["observed_sample_interval_seconds"])
        self.assertEqual(result["metric_samples"]["kv_cache_usage"]["mean"], 0.5)

    def test_invalid_records_fail_closed(self):
        cases = [
            [sample(0, {}, "sglang")],
            [sample(0, {"requests_waiting": float("nan")})],
            [sample(0, {"requests_waiting": float("inf")})],
            [sample(0, {"requests_waiting": True})],
            [sample(0, {"requests_waiting": -1})],
            [sample(0, {"unknown_private_label": 1})],
            [sample(0, {}), sample(0, {})],
            [{"runtime": "vllm", "monotonic_ns": 0, "metrics": {}}],
            [{**sample(0, {}), "monotonic_ns": -1}],
            [None],
            [],
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.read(rows)

    def test_counter_reset_is_detected_even_after_recovery(self):
        rows = [sample(i, {"prefill_seconds_sum": duration, "prefill_seconds_count": count})
                for i, (duration, count) in enumerate([(100, 10), (1, 1), (200, 20)])]
        result = MODULE.summarize(self.read(rows), "vllm")
        self.assertIsNone(result["native_window"]["prefill_seconds_per_request"])
        self.assertIn("prefill_seconds_sum", result["counter_resets_detected"])

    def test_window_has_explicit_same_host_bounds(self):
        rows = self.read([sample(i, {"requests_waiting": i}) for i in range(3)])
        result = MODULE.summarize(rows, "vllm", 2_000_000_000, 3_000_000_000)
        self.assertEqual(result["sample_count"], 2)
        with self.assertRaises(ValueError):
            MODULE.summarize(rows, "vllm", 0, None)
        with self.assertRaises(ValueError):
            MODULE.summarize(rows, "vllm", 0, 1)

    def test_cli_writes_private_summary_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture.jsonl"
            output = Path(directory) / "summary.json"
            source.write_text(json.dumps(sample(0, {"requests_running": 1})) + "\n")
            command = [sys.executable, str(ROOT / "scripts/summarize_runtime_metrics.py"),
                       "--input", str(source), "--runtime", "vllm", "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(output.read_text())["sample_count"], 1)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)


if __name__ == "__main__":
    unittest.main()
