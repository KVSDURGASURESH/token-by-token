from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_benchmark_metrics.py"


def load_module():
    if not SCRIPT.exists():
        raise AssertionError("metrics validator is missing")
    spec = importlib.util.spec_from_file_location("validate_benchmark_metrics", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, payload: bytes = b"", status: int = 204):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.payload


class RecordingOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def export_response(*, include_gpu: bool = True, series: int = 6, samples: int = 24, reset: bool = False, duplicate_conflict: bool = False) -> Response:
    names = [
        "agentbench_requests_total",
        "vllm_num_requests_running",
        "agentbench_gpu_power_watts",
        "agentbench_request_ttft_visible_seconds_sum",
        "vllm_num_requests_waiting",
        "agentbench_gpu_utilization_percent",
    ][:series]
    if not include_gpu:
        names = [name for name in names if not name.startswith("agentbench_gpu_")]
        while len(names) < series:
            names.append(f"vllm_fixture_{len(names)}")
    rows = []
    remaining = samples
    for index, name in enumerate(names):
        slots = min(4, remaining)
        remaining -= slots
        values = [float(index + offset + 1) for offset in range(slots)]
        if reset and name.endswith("_total") and len(values) >= 3:
            values[2] = 0.0
        rows.append(
            {
                "metric": {"__name__": name, "validation_namespace": "101", "series": str(index)},
                "values": values,
                "timestamps": [1710000000000 + offset * 100000 for offset in range(slots)],
            }
        )
    if remaining:
        rows[-1]["values"].extend(float(index) for index in range(remaining))
        rows[-1]["timestamps"].extend(1710000000000 + (4 + index) * 1000 for index in range(remaining))
    rows[-1]["values"][-1] = None
    if duplicate_conflict:
        rows.append(
            {
                "metric": dict(rows[0]["metric"]),
                "values": [999.0],
                "timestamps": [rows[0]["timestamps"][0]],
            }
        )
    return Response(("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8"), 200)


class BenchmarkMetricsValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def make_spec(self, directory: str, *, sha256: str | None = None, size_delta: int = 0, expected_samples: int = 24):
        root = Path(directory)
        archive = root / "metrics.native.gz"
        archive.write_bytes(gzip.compress(b"native-fixture"))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest = {
            "start_s": 1710000000.0,
            "end_s": 1710000300.0,
            "series": 6,
            "samples": expected_samples,
            "match": "{__name__=~\"vllm_.*|agentbench_.*\"}",
            "files": {"metrics.native.gz": archive.stat().st_size + size_delta},
        }
        if sha256 is not None:
            manifest["sha256"] = sha256
        manifest_path = root / "metrics_export.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        spec = self.module.ImportSpec(
            archive=archive,
            manifest=manifest_path,
            start=datetime.fromtimestamp(manifest["start_s"], tz=timezone.utc),
            end=datetime.fromtimestamp(manifest["end_s"], tz=timezone.utc),
            namespace="101",
        )
        return spec, digest

    def test_accepts_only_loopback_http_targets(self):
        for allowed in ("http://127.0.0.1:8428", "http://localhost:8428", "http://[::1]:8428"):
            self.module.assert_loopback_url(allowed)
        private_target = "http://" + "10.0." + "0.8" + ":8428"
        for blocked in ("https://example.com", private_target, "file:///tmp/data"):
            with self.subTest(blocked=blocked), self.assertRaisesRegex(ValueError, "loopback"):
                self.module.assert_loopback_url(blocked)

    def test_verifies_size_and_optional_digest_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, digest = self.make_spec(directory, sha256="0" * 64)
            with self.assertRaisesRegex(ValueError, "checksum"):
                self.module.verify_export(spec)
            spec, _ = self.make_spec(directory, sha256=digest, size_delta=1)
            with self.assertRaisesRegex(ValueError, "size"):
                self.module.verify_export(spec)

    def test_import_posts_archive_only_to_tenant_native_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, _ = self.make_spec(directory)
            opener = RecordingOpener([Response()])
            result = self.module.import_native_export(
                spec, "http://127.0.0.1:8428", opener=opener
            )
            request, timeout = opener.requests[0]
            self.assertEqual(
                request.full_url,
                "http://127.0.0.1:8428/api/v1/import/native?extra_label=validation_namespace%3D101",
            )
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.get_header("Content-encoding"), "gzip")
            self.assertEqual(request.data, spec.archive.read_bytes())
            self.assertEqual(timeout, 60)
            self.assertTrue(result.imported)

    def test_validation_queries_are_bounded_and_match_manifest_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, _ = self.make_spec(directory)
            opener = RecordingOpener([export_response()])
            result = self.module.run_validation_queries(
                spec, "http://localhost:8428", opener=opener
            )
            self.assertTrue(result.passed)
            self.assertEqual(result.series_count, 6)
            self.assertEqual(result.sample_count, 24)
            self.assertEqual(
                result.query_names,
                ("series_count", "sample_count", "client_family", "engine_family", "gpu_family", "counter_resets"),
            )
            self.assertEqual(len(opener.requests), 1)
            for request, _timeout in opener.requests:
                self.assertEqual(
                    urlsplit(request.full_url).path,
                    "/api/v1/export",
                )
                form = parse_qs(request.data.decode("ascii"))
                self.assertEqual(form["start"], ["1710000000.000000"])
                self.assertEqual(form["end"], ["1710000300.000000"])
                self.assertIn('validation_namespace="101"', form["match[]"][0])

    def test_rejects_count_mismatch_and_missing_metric_family(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, _ = self.make_spec(directory)
            mismatch = RecordingOpener([export_response(series=5, samples=24)])
            with self.assertRaisesRegex(ValueError, "series-count-mismatch"):
                self.module.run_validation_queries(
                    spec,
                    "http://localhost:8428",
                    opener=mismatch,
                    visibility_timeout_seconds=0,
                )
            missing = RecordingOpener([export_response(include_gpu=False)])
            with self.assertRaisesRegex(ValueError, "missing-metric-family"):
                self.module.run_validation_queries(spec, "http://localhost:8428", opener=missing)

    def test_retries_until_imported_counts_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, _ = self.make_spec(directory)
            opener = RecordingOpener(
                [export_response(series=5, samples=20), export_response()]
            )
            sleeps = []
            result = self.module.run_validation_queries(
                spec,
                "http://localhost:8428",
                opener=opener,
                visibility_timeout_seconds=1,
                poll_interval_seconds=0,
                sleeper=sleeps.append,
            )
            self.assertTrue(result.passed)
            self.assertEqual(len(opener.requests), 2)
            self.assertEqual(sleeps, [0])

    def test_reconciles_raw_count_then_deduplicates_conflicting_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, _ = self.make_spec(directory, expected_samples=25)
            opener = RecordingOpener([export_response(duplicate_conflict=True)])
            result = self.module.run_validation_queries(
                spec, "http://localhost:8428", opener=opener
            )
            self.assertEqual(result.sample_count, 25)
            self.assertEqual(result.duplicate_samples, 1)

    def test_exact_export_detects_counter_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, _ = self.make_spec(directory)
            opener = RecordingOpener([export_response(reset=True)])
            with self.assertRaisesRegex(ValueError, "counter-reset"):
                self.module.run_validation_queries(spec, "http://localhost:8428", opener=opener)

    def test_normalizes_duplicates_and_rejects_out_of_window_samples(self):
        start = datetime.fromtimestamp(1710000000, tz=timezone.utc)
        end = datetime.fromtimestamp(1710000300, tz=timezone.utc)
        payload = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"__name__": "agentbench_requests_total", "kind": "ok"},
                        "values": [[1710000000, "1"], [1710000000, "1"], [1710000300, "2"]],
                    }
                ],
            },
        }
        samples = self.module.normalize_matrix_samples(payload, start, end)
        self.assertEqual(len(samples), 2)
        payload["data"]["result"][0]["values"].append([1709999999, "0"])
        with self.assertRaisesRegex(ValueError, "out-of-window"):
            self.module.normalize_matrix_samples(payload, start, end)

    def test_detects_counter_reset_without_echoing_labels(self):
        secret = "private-instance-label"
        samples = [
            self.module.Sample("agentbench_requests_total", (("instance", secret),), 1.0, 9.0),
            self.module.Sample("agentbench_requests_total", (("instance", secret),), 2.0, 3.0),
        ]
        with self.assertRaises(ValueError) as caught:
            self.module.assert_no_counter_resets(samples)
        self.assertEqual(str(caught.exception), "counter-reset")
        self.assertNotIn(secret, str(caught.exception))

    def test_private_receipt_contains_categories_not_paths_or_query_values(self):
        with tempfile.TemporaryDirectory() as directory:
            spec, _ = self.make_spec(directory)
            opener = RecordingOpener([export_response()])
            result = self.module.run_validation_queries(
                spec, "http://localhost:8428", opener=opener
            )
            destination = Path(directory) / "receipt.json"
            self.module.write_private_receipt(result, destination)
            receipt = json.loads(destination.read_text(encoding="utf-8"))
            self.assertNotIn(str(spec.archive), json.dumps(receipt))
            self.assertNotIn("query", json.dumps(receipt).lower())
            self.assertEqual(receipt["status"], "passed")
            self.module.record_dashboard_checks(
                destination,
                {"client": "passed_with_declared_gaps", "engine": "passed", "gpu": "passed"},
            )
            updated = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["dashboard_checks"],
                {"client": "passed_with_declared_gaps", "engine": "passed", "gpu": "passed"},
            )
            with self.assertRaisesRegex(ValueError, "dashboard"):
                self.module.write_private_receipt(result, ROOT / "dashboard" / "receipt.json")


if __name__ == "__main__":
    unittest.main()
