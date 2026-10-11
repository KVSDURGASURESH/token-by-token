from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from runpod_benchmark.canonical_launch import (
    CanonicalBundle,
    CanonicalLaunchController,
    CanonicalLaunchError,
    REQUIRED_INPUTS,
    SCHEMA_VERSION,
)
from test_episode1_orchestrator import approved_plan


class CanonicalLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/execute_episode1.py").write_text("# bound command\n")
        plan = approved_plan()[0]
        self.digest = plan["plan_sha256"]
        (self.root / "plan.json").write_text(json.dumps(plan))
        inputs = {key: f"private/{key}.json" for key in REQUIRED_INPUTS}
        inputs["plan"] = "plan.json"
        inputs["unique_name"] = "episode1-candidate-run-01"
        inputs["private_evidence_directory"] = "private/evidence/run-01"
        self.bundle_path = self.root / "bundle.json"
        self.bundle_path.write_text(json.dumps({
            "schema_version": SCHEMA_VERSION, "episode": 1, "inputs": inputs,
        }))

    def tearDown(self):
        self.temporary.cleanup()

    def result(self, mode: str):
        return subprocess.CompletedProcess(
            [], 0, json.dumps({
                "plan_sha256": self.digest,
                "closure_receipt_sha256": "b" * 64,
                "mode": mode,
                **({"status": "complete", "deletion_verified": True} if mode == "run" else {}),
            }), "",
        )

    def test_browser_inputs_cannot_change_fixed_command(self):
        bundle = CanonicalBundle.load(self.bundle_path, self.root)
        command = bundle.command(self.root, "preflight")
        self.assertEqual(command[1], str(self.root / "scripts/execute_episode1.py"))
        self.assertNotIn("--provider-adapter", command)
        self.assertEqual(command[command.index("--plan") + 1], "plan.json")
        with self.assertRaises(CanonicalLaunchError):
            bundle.command(self.root, "arbitrary-command")

    def test_bundle_rejects_path_escape(self):
        raw = json.loads(self.bundle_path.read_text())
        raw["inputs"]["plan"] = "../plan.json"
        self.bundle_path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(CanonicalLaunchError, "stay within"):
            CanonicalBundle.load(self.bundle_path, self.root)

    def test_unconfigured_preflight_stays_not_configured(self):
        controller = CanonicalLaunchController(None, self.root)
        with self.assertRaisesRegex(CanonicalLaunchError, "no canonical launch bundle"):
            controller.preflight()
        self.assertEqual(controller.status()["phase"], "not-configured")

    def test_preflight_is_read_only_mode_and_digest_bound(self):
        commands = []
        def executor(command):
            commands.append(list(command))
            return self.result("preflight")
        controller = CanonicalLaunchController(self.bundle_path, self.root, executor=executor)
        result = controller.preflight()
        self.assertEqual(result["plan_sha256"], self.digest)
        self.assertEqual(commands[0][2], "preflight")
        self.assertEqual(controller.status()["phase"], "preflight-passed")

    def test_launch_requires_switch_and_exact_approval_then_runs_async(self):
        disabled = CanonicalLaunchController(self.bundle_path, self.root, executor=lambda command: self.result("run"))
        with self.assertRaisesRegex(CanonicalLaunchError, "disabled"):
            disabled.launch(disabled.bundle.approval_phrase)

        commands = []
        def executor(command):
            commands.append(list(command))
            return self.result("run")
        controller = CanonicalLaunchController(
            self.bundle_path, self.root, launch_enabled=True, executor=executor,
        )
        with self.assertRaisesRegex(CanonicalLaunchError, "exact digest-bound"):
            controller.launch("APPROVE SOMETHING ELSE")
        accepted = controller.launch(controller.bundle.approval_phrase)
        self.assertTrue(accepted["accepted"])
        for _ in range(100):
            if controller.status()["phase"] != "running":
                break
            time.sleep(.001)
        self.assertEqual(controller.status()["phase"], "complete")
        self.assertEqual(commands[0][2], "run")

    def test_failed_result_never_claims_completion(self):
        failed = subprocess.CompletedProcess([], 2, "", "Episode 1 production command rejected (ValueError)\n")
        controller = CanonicalLaunchController(
            self.bundle_path, self.root, launch_enabled=True, executor=lambda command: failed,
        )
        controller.launch(controller.bundle.approval_phrase)
        for _ in range(100):
            if controller.status()["phase"] != "running":
                break
            time.sleep(.001)
        self.assertEqual(controller.status()["phase"], "run-rejected")
        self.assertIn("rejected", controller.status()["last_result"]["error"])

    def test_run_without_verified_deletion_never_claims_completion(self):
        result = self.result("run")
        value = json.loads(result.stdout)
        value["deletion_verified"] = False
        unverified = subprocess.CompletedProcess([], 0, json.dumps(value), "")
        controller = CanonicalLaunchController(
            self.bundle_path, self.root, launch_enabled=True, executor=lambda command: unverified,
        )
        controller.launch(controller.bundle.approval_phrase)
        for _ in range(100):
            if controller.status()["phase"] != "running":
                break
            time.sleep(.001)
        self.assertEqual(controller.status()["phase"], "run-failed")


if __name__ == "__main__":
    unittest.main()
