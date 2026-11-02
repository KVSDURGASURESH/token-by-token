from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"


class Episode04RehearsalTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONPATH": str(CLIENT_SRC)}
        return subprocess.run(
            [sys.executable, "-m", "token_by_token_cli", *args],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_complete_episode04_offline_user_path(self) -> None:
        describe = self.run_cli("episode", "4", "describe", "--format", "json")
        self.assertEqual(describe.returncode, 0, describe.stderr)
        manifest = json.loads(describe.stdout)
        self.assertEqual(manifest["status"], "recorded")
        self.assertEqual(manifest["protocol_status"], "recorded_reference")
        self.assertEqual(manifest["load_levels"], [1])
        self.assertEqual(manifest["speculative_decoding"], "study_variable")
        self.assertEqual(manifest["selftest"]["classification"], "synthetic_mock")

        capabilities = self.run_cli("capabilities", "--episode", "4", "--format", "json")
        self.assertEqual(capabilities.returncode, 0, capabilities.stderr)
        capability = json.loads(capabilities.stdout)
        self.assertEqual(capability["episode_status"], "recorded")
        self.assertEqual(capability["execution_status"], "unavailable")
        self.assertFalse(capability["real_submission"])
        self.assertEqual(capability["models"], [])
        self.assertEqual(capability["gpus"], [])
        self.assertEqual(capability["load_profiles"], [])

        doctor = self.run_cli("doctor", "--offline", "--format", "json")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertEqual(json.loads(doctor.stdout)["classification"], "synthetic_mock")

        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "episode-04.tbt.zip"
            selftest = self.run_cli(
                "episode", "4", "selftest", "--offline", "--users", "1",
                "--seed", "42", "--output", str(bundle), "--format", "json",
            )
            self.assertEqual(selftest.returncode, 0, selftest.stderr)
            self.assertEqual(json.loads(selftest.stdout)["classification"], "synthetic_mock")

            verify = self.run_cli("evidence", "verify", str(bundle), "--format", "json")
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["valid"])
            self.assertEqual(json.loads(verify.stdout)["classification"], "synthetic_mock")

            with zipfile.ZipFile(bundle) as archive:
                events = [json.loads(line) for line in archive.read("events.jsonl").splitlines()]
            arms = [event["payload"]["arm"] for event in events if event["kind"] == "arm_started"]
            self.assertEqual(arms, ["synthetic-target-only", "synthetic-eagle3"])
            self.assertEqual(events[0]["payload"]["classification"], "synthetic_mock")
            self.assertEqual(events[-1]["payload"]["classification"], "synthetic_mock")

    def test_provider_and_gpu_options_fail_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "forbidden.tbt.zip"
            for option in ("--provider", "--gpu", "--endpoint", "--profile"):
                with self.subTest(option=option):
                    result = self.run_cli(
                        "episode", "4", "selftest", "--offline", option, "value",
                        "--output", str(output),
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(output.exists())
                    self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
