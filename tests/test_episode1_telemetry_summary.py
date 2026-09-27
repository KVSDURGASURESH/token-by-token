import math
import unittest

from runpod_benchmark.telemetry_summary import ContractError, Series, Window, summarize


WINDOW = Window("pod-monotonic-1", 1_000_000_000, 3_000_000_000, 1_500_000_000,
                "pid-7", "start-abc", "vllm", "block-1")


def sample(t, value, *, runtime="vllm", process="pid-7", start="start-abc", block="block-1",
           metric="vllm:prompt_tokens_total", labels=None, domain="pod-monotonic-1",
           status="ok", reason=None):
    return {"clock_domain": domain, "monotonic_ns": t, "process_identity": process,
            "process_start_identity": start, "runtime": runtime, "block": block,
            "metric_name": metric, "labels": labels or {}, "value": value,
            "status": status, "reason": reason}


class CounterTests(unittest.TestCase):
    def test_exact_counter_delta_and_rate(self):
        result = summarize([sample(1_000_000_000, 100), sample(2_000_000_000, 105),
                            sample(3_000_000_000, 110)], WINDOW,
                           Series.create("counter", "vllm:prompt_tokens_total"))
        self.assertTrue(result["available"])
        self.assertEqual("window_exact", result["coverage"])
        self.assertEqual(10, result["counter"]["delta"])
        self.assertEqual(5, result["counter"]["rate_per_second"])

    def test_bracketing_uses_observed_interval_without_interpolation(self):
        result = summarize([sample(500_000_000, 90), sample(2_000_000_000, 100),
                            sample(3_500_000_000, 120)], WINDOW,
                           Series.create("counter", "vllm:prompt_tokens_total"))
        self.assertEqual("sampled_interval_covering_window", result["coverage"])
        self.assertEqual(500_000_000, result["first_sample_monotonic_ns"])
        self.assertEqual(3_500_000_000, result["last_sample_monotonic_ns"])
        self.assertEqual(30, result["counter"]["delta"])
        self.assertEqual(10, result["counter"]["rate_per_second"])

    def test_intermediate_decrease_is_unavailable(self):
        result = summarize([sample(1_000_000_000, 100), sample(2_000_000_000, 0),
                            sample(3_000_000_000, 110)], WINDOW,
                           Series.create("counter", "vllm:prompt_tokens_total"))
        self.assertFalse(result["available"])
        self.assertEqual("counter_decreased", result["unavailable_reason"])
        self.assertIsNone(result["counter"])

    def test_repro_identity_a_b_b_is_unavailable_not_delta_ten(self):
        result = summarize([sample(1_000_000_000, 100, process="A", start="A0"),
                            sample(2_000_000_000, 0, process="B", start="B0"),
                            sample(3_000_000_000, 110, process="B", start="B0")], WINDOW,
                           Series.create("counter", "vllm:prompt_tokens_total"))
        self.assertFalse(result["available"])
        self.assertEqual("identity_changed", result["unavailable_reason"])

    def test_rejects_gap_missing_nonfinite_order_duplicate_and_domain(self):
        cases = [
            ([sample(1_000_000_000, 1), sample(3_000_000_000, 2)], "sampling_gap_exceeded"),
            ([sample(1_000_000_000, 1), sample(2_000_000_000, None, status="missing", reason="not_reported"), sample(3_000_000_000, 2)], "sample_missing"),
            ([sample(1_000_000_000, 1), sample(2_000_000_000, math.nan), sample(3_000_000_000, 2)], "nonfinite_value"),
            ([sample(2_000_000_000, 1), sample(1_000_000_000, 1), sample(3_000_000_000, 2)], "out_of_order"),
            ([sample(1_000_000_000, 1), sample(1_000_000_000, 1), sample(3_000_000_000, 2)], "duplicate_timestamp"),
            ([sample(1_000_000_000, 1), sample(3_000_000_000, 2, domain="other")], "incompatible_clock_domain"),
        ]
        for samples, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(reason, summarize(samples, WINDOW, Series.create("counter", "vllm:prompt_tokens_total"))["unavailable_reason"])

    def test_negative_counter_and_overflowing_rate_are_unavailable(self):
        series = Series.create("counter", "vllm:prompt_tokens_total")
        negative = summarize([sample(1_000_000_000, -2), sample(2_000_000_000, -1),
                              sample(3_000_000_000, 0)], WINDOW, series)
        self.assertEqual("counter_negative", negative["unavailable_reason"])
        narrow = Window("pod-monotonic-1", 1, 2, 1, "pid-7", "start-abc", "vllm", "block-1")
        overflow = summarize([sample(1, 0), sample(2, 1e308)], narrow, series)
        self.assertEqual("derived_nonfinite", overflow["unavailable_reason"])
        huge_ns = 10 ** 400
        huge_window = Window("pod-monotonic-1", 0, huge_ns, huge_ns,
                             "pid-7", "start-abc", "vllm", "block-1")
        huge_span = summarize([sample(0, 0), sample(huge_ns, 1)], huge_window, series)
        self.assertEqual("derived_nonfinite", huge_span["unavailable_reason"])

    def test_requires_both_brackets(self):
        series = Series.create("counter", "vllm:prompt_tokens_total")
        self.assertEqual("missing_left_bracket", summarize([sample(2_000_000_000, 1), sample(3_000_000_000, 2)], WINDOW, series)["unavailable_reason"])
        self.assertEqual("missing_right_bracket", summarize([sample(1_000_000_000, 1), sample(2_000_000_000, 2)], WINDOW, series)["unavailable_reason"])


class GaugeAndContractTests(unittest.TestCase):
    def test_gauge_has_stats_and_never_counter_fields(self):
        result = summarize([sample(1_000_000_000, 0.2, metric="vllm:kv_cache_usage_perc"),
                            sample(2_000_000_000, 0.8, metric="vllm:kv_cache_usage_perc"),
                            sample(3_000_000_000, 0.4, metric="vllm:kv_cache_usage_perc")], WINDOW,
                           Series.create("gauge", "vllm:kv_cache_usage_perc"))
        self.assertTrue(result["available"])
        self.assertIsNone(result["counter"])
        self.assertEqual(0.8, result["gauge"]["maximum"])
        self.assertEqual(0.4, result["gauge"]["median"])

    def test_overflowing_gauge_arithmetic_is_unavailable(self):
        narrow = Window("pod-monotonic-1", 1, 2, 1, "pid-7", "start-abc", "vllm", "block-1")
        result = summarize([sample(1, 1e308, metric="vllm:kv_cache_usage_perc"),
                            sample(2, 1e308, metric="vllm:kv_cache_usage_perc")], narrow,
                           Series.create("gauge", "vllm:kv_cache_usage_perc"))
        self.assertFalse(result["available"])
        self.assertEqual("derived_nonfinite", result["unavailable_reason"])

    def test_missing_is_null_and_explicit_not_zero(self):
        result = summarize([sample(1_000_000_000, None, status="missing", reason="not_reported"),
                            sample(2_000_000_000, 0),
                            sample(3_000_000_000, 0)], WINDOW,
                           Series.create("gauge", "vllm:prompt_tokens_total"))
        self.assertFalse(result["available"])
        self.assertEqual("sample_missing", result["unavailable_reason"])
        self.assertIsNone(result["gauge"])

    def test_labels_are_exact_independent_series(self):
        samples = [sample(1_000_000_000, 1, labels={"model": "a"}), sample(2_000_000_000, 2, labels={"model": "a"}),
                   sample(3_000_000_000, 3, labels={"model": "a"}), sample(1_000_000_000, 100, labels={"model": "b"}),
                   sample(2_000_000_000, 200, labels={"model": "b"}), sample(3_000_000_000, 300, labels={"model": "b"})]
        result = summarize(samples, WINDOW, Series.create("counter", "vllm:prompt_tokens_total", {"model": "a"}))
        self.assertEqual(2, result["counter"]["delta"])
        self.assertEqual({"model": "a"}, result["labels"])

    def test_sgl_full_token_usage_remains_native_distinct_metric(self):
        window = Window("pod-monotonic-1", 1_000_000_000, 3_000_000_000, 2_000_000_000,
                        "pid-7", "start-abc", "sglang", "block-1")
        samples = [sample(1_000_000_000, 10, runtime="sglang", metric="sglang:full_token_usage"),
                   sample(3_000_000_000, 20, runtime="sglang", metric="sglang:full_token_usage")]
        result = summarize(samples, window, Series.create("gauge", "sglang:full_token_usage"))
        self.assertEqual("sglang:full_token_usage", result["metric_name"])
        self.assertNotIn("kv", result["metric_name"])

    def test_closed_contract_rejects_unknown_keys_and_bad_missing(self):
        bad = sample(1_000_000_000, 1)
        bad["hostname"] = "secret"
        with self.assertRaisesRegex(ContractError, "sample_keys"):
            summarize([bad], WINDOW, Series.create("counter", "vllm:prompt_tokens_total"))
        with self.assertRaisesRegex(ContractError, "missing_sample_reason"):
            summarize([sample(1_000_000_000, None, status="missing", reason="scrape_failed")], WINDOW,
                      Series.create("counter", "vllm:prompt_tokens_total"))

    def test_window_and_series_require_exact_types(self):
        bad_windows = [
            Window("pod-monotonic-1", 1.0, 3_000_000_000, 1_000_000_000, "pid", "start", "vllm", "block"),
            Window("pod-monotonic-1", True, 3_000_000_000, 1_000_000_000, "pid", "start", "vllm", "block"),
            Window("pod-monotonic-1", 1, 3, 1.0, "pid", "start", "vllm", "block"),
            Window("pod-monotonic-1", 1, 3, True, "pid", "start", "vllm", "block"),
            Window("pod-monotonic-1", 1, 3, 1, 7, "start", "vllm", "block"),
        ]
        for bad_window in bad_windows:
            with self.subTest(window=bad_window), self.assertRaises(ContractError):
                summarize([], bad_window, Series.create("counter", "metric"))
        malformed_series = [Series("counter", "metric", {"x": "y"}),
                            Series("counter", "metric", (("x", 1),)),
                            Series("counter", "metric", (("z", "1"), ("a", "2"))),
                            Series("counter", "metric", (("x", "1"), ("x", "2"))),
                            Series("counter", 7, ())]
        for bad_series in malformed_series:
            with self.subTest(series=bad_series), self.assertRaises(ContractError):
                summarize([], WINDOW, bad_series)
        with self.assertRaises(ContractError):
            Series.create("counter", "metric", [("x", "y")])

    def test_non_mapping_sample_is_contract_error(self):
        with self.assertRaisesRegex(ContractError, "sample_mapping"):
            summarize([42], WINDOW, Series.create("counter", "vllm:prompt_tokens_total"))

    def test_malformed_sample_identity_and_reason_are_contract_errors(self):
        bad_identity = sample(1_000_000_000, 1)
        bad_identity["metric_name"] = 7
        with self.assertRaisesRegex(ContractError, "sample_identity"):
            summarize([bad_identity], WINDOW, Series.create("counter", "vllm:prompt_tokens_total"))
        bad_reason = sample(1_000_000_000, None, status="error", reason=["scrape_failed"])
        with self.assertRaisesRegex(ContractError, "unavailable_sample_value"):
            summarize([bad_reason], WINDOW, Series.create("counter", "vllm:prompt_tokens_total"))


if __name__ == "__main__":
    unittest.main()
