from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OfflineWorkflowTests(unittest.TestCase):
    def test_historical_snapshot_verifies(self):
        verifier = load("verify_bundle")
        result = verifier.verify_bundle(ROOT / "data" / "public")
        self.assertTrue(result.ok, result.errors)

    def test_fixture_rehearsal_is_zero_cost_and_provider_free(self):
        rehearsal = load("rehearse_workflow")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            result = rehearsal.rehearse(output)
            self.assertEqual(result["classification"], "fixture_zero_cost")
            self.assertEqual(result["paid_resources_created"], 0)
            self.assertEqual(result["provider_attempts"], 0)
            self.assertTrue(result["verification"].ok)
            plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
            self.assertFalse(plan["execution_ready"])
            self.assertFalse(plan["approvable"])
            self.assertEqual(plan["cost"]["maximum_usd"], "0.00")
            attempts = json.loads(
                (output / "runtime-attempts.json").read_text(encoding="utf-8")
            )
            self.assertFalse(attempts["provider_calls_made"])
            self.assertEqual(attempts["attempts"], [])

    def test_dashboard_data_is_bound_to_public_snapshot(self):
        if not (ROOT / "dashboard").is_dir():
            self.skipTest("dashboard intentionally omitted from packager-only test")
        self.assertEqual(
            (ROOT / "dashboard" / "src" / "data" / "latest.json").read_bytes(),
            (ROOT / "data" / "public" / "dashboard" / "latest.json").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
