from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_static_benchmark_evidence.py"
SCHEMA = ROOT / "schemas" / "public-inference-evidence.v1.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "private-evidence-minimal.json"


def load_module():
    if not SCRIPT.exists():
        raise AssertionError("static evidence generator is missing")
    spec = importlib.util.spec_from_file_location("build_static_benchmark_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StaticEvidencePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.source = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def build(self, source=None):
        return self.module.build_public_document(copy.deepcopy(source or self.source))

    def test_builds_only_allowlisted_public_arms_and_loads(self):
        document = self.build()

        self.assertEqual(document["schema_version"], "public-inference-evidence.v1")
        self.assertEqual([arm["engine"] for arm in document["arms"]], ["vLLM", "SGLang"])
        self.assertEqual(document["levels"], [12, 16, 24])
        self.assertEqual(
            [[point["users"] for point in arm["points"]] for arm in document["arms"]],
            [[12, 16, 24], [12, 16, 24]],
        )
        serialized = json.dumps(document, sort_keys=True).lower()
        for forbidden in (
            "profile",
            "configuration",
            "engine_version",
            "runtime_version",
            "private-run-14",
            "private-third-profile",
            "never-publish-this-recipe",
            "/users/",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertNotRegex(serialized, r'"engine"\s*:\s*"(?:vllm|sglang)[- ]?\d')

    def test_output_validates_against_closed_schema(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.build())

    def test_serialization_is_byte_stable_and_terminated(self):
        first = self.module.serialize_public_document(self.build())
        second = self.module.serialize_public_document(self.build())
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(first.count(b"\n"), 1)

    def test_write_if_valid_does_not_replace_destination_on_failure(self):
        invalid = self.build()
        invalid["arms"][0]["points"][0]["users"] = 14
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "public.json"
            destination.write_bytes(b"approved\n")
            with self.assertRaises(ValueError):
                self.module.write_if_valid(invalid, SCHEMA, destination)
            self.assertEqual(destination.read_bytes(), b"approved\n")

    def test_write_if_valid_rejects_private_free_text_before_replacement(self):
        document = self.build()
        document["study"]["title"] = "private engine v9.9 at /srv/internal/results"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "public.json"
            destination.write_bytes(b"approved\n")
            with self.assertRaisesRegex(ValueError, "privacy"):
                self.module.write_if_valid(document, SCHEMA, destination)
            self.assertEqual(destination.read_bytes(), b"approved\n")

    def test_rejects_unapproved_engine(self):
        source = copy.deepcopy(self.source)
        source["source_arms"][0]["engine"] = "OtherEngine"
        with self.assertRaisesRegex(ValueError, "engine"):
            self.build(source)

    def test_rejects_unapproved_load_even_when_marked_publishable(self):
        source = copy.deepcopy(self.source)
        source["source_arms"][0]["points"][0]["users"] = 14
        with self.assertRaisesRegex(ValueError, "load"):
            self.build(source)

    def test_rejects_invalid_level_presented_as_valid(self):
        source = copy.deepcopy(self.source)
        point = source["source_arms"][0]["points"][0]
        point["metrics"]["error_rate_pct"] = 1.01
        point["level_valid"] = True
        with self.assertRaisesRegex(ValueError, "error rate"):
            self.build(source)

    def test_rejects_invalid_level_even_when_marked_invalid(self):
        source = copy.deepcopy(self.source)
        point = source["source_arms"][0]["points"][0]
        point["metrics"]["error_rate_pct"] = 50
        point["level_valid"] = False
        with self.assertRaisesRegex(ValueError, "invalid level"):
            self.build(source)

    def test_receipts_require_successful_dashboard_checks_and_bind_each_run_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = []
            receipts = []
            for index in range(3):
                run = root / f"run-{index}"
                archive = run / "metrics" / "metrics.csv.gz"
                archive.parent.mkdir(parents=True)
                archive.write_bytes(f"archive-{index}".encode())
                runs.append(run)
                receipt = root / f"receipt-{index}.json"
                receipt.write_text(json.dumps({
                    "schema": "private-metrics-validation.v1",
                    "status": "passed",
                    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "window": {"start_epoch": 1, "end_epoch": 2},
                    "dashboard_checks": {"client": "passed", "engine": "passed", "gpu": "passed"},
                }))
                receipts.append(receipt)
            self.module._assert_receipts(receipts, runs)
            failed = json.loads(receipts[0].read_text())
            failed["dashboard_checks"]["gpu"] = "failed"
            receipts[0].write_text(json.dumps(failed))
            with self.assertRaisesRegex(ValueError, "dashboard"):
                self.module._assert_receipts(receipts, runs)

    def test_rejects_averaged_percentiles(self):
        source = copy.deepcopy(self.source)
        source["source_arms"][0]["points"][0]["percentile_origin"] = "average"
        with self.assertRaisesRegex(ValueError, "percentile"):
            self.build(source)

    def test_unavailable_metric_is_null_with_reason_and_never_zero(self):
        document = self.build()
        reading = document["arms"][1]["points"][0]["readings"]["cache_context"]
        self.assertEqual(
            reading,
            {
                "available": False,
                "value": None,
                "unit": "%",
                "reason": "Not available with a comparable public definition.",
                "evidence_state": "unavailable",
            },
        )

    def test_rejects_nonfinite_values_and_negative_counts(self):
        for mutation, message in ((math.inf, "finite"), (-1, "nonnegative")):
            with self.subTest(mutation=mutation):
                source = copy.deepcopy(self.source)
                if mutation == math.inf:
                    source["source_arms"][0]["points"][0]["metrics"]["output_tps"] = mutation
                else:
                    source["source_arms"][0]["points"][0]["valid_requests"] = mutation
                with self.assertRaisesRegex(ValueError, message):
                    self.build(source)

    def test_rejects_duplicate_engine_load_pairs(self):
        source = copy.deepcopy(self.source)
        source["source_arms"][0]["points"].append(
            copy.deepcopy(source["source_arms"][0]["points"][0])
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.build(source)

    def test_closed_schema_rejects_extra_nested_and_top_level_keys(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for path in ("top", "nested"):
            with self.subTest(path=path):
                document = self.build()
                if path == "top":
                    document["source_path"] = "/" + "Users" + "/example/private"
                else:
                    document["arms"][0]["profile"] = "private"
                errors = list(Draft202012Validator(schema).iter_errors(document))
                self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
