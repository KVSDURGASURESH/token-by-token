from __future__ import annotations

import os
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"


class CliSurfaceTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONPATH": str(CLIENT_SRC)}
        return subprocess.run(
            [sys.executable, "-m", "token_by_token_cli", *args],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_help_exposes_only_public_offline_commands(self) -> None:
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("episodes", result.stdout)
        self.assertIn("episode", result.stdout)
        self.assertIn("capabilities", result.stdout)
        self.assertIn("doctor", result.stdout)
        self.assertIn("evidence", result.stdout)
        self.assertNotIn("runs submit", result.stdout)
        self.assertNotIn("auth login", result.stdout)

    def test_unknown_command_is_a_clean_usage_error(self) -> None:
        result = self.run_cli("runs", "submit")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_episode_command_accepts_the_catalog_range(self) -> None:
        result = self.run_cli("episode", "16", "describe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Episode 16", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_security_relevant_flags_do_not_accept_abbreviations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "abbreviated.tbt.zip"
            result = self.run_cli("episode", "2", "selftest", "--off", "--output", str(output))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())

    def test_capabilities_fail_closed_when_real_service_is_unavailable(self) -> None:
        result = self.run_cli("capabilities", "--episode", "1", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["episode"], 1)
        self.assertEqual(document["execution_status"], "unavailable")
        self.assertFalse(document["real_submission"])
        self.assertEqual(document["models"], [])
        self.assertEqual(document["gpus"], [])

    def test_offline_doctor_checks_install_without_leaving_a_bundle(self) -> None:
        result = self.run_cli("doctor", "--offline", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["status"], "pass")
        self.assertEqual(document["network"], "forbidden")
        self.assertEqual(document["classification"], "synthetic_mock")
        self.assertEqual(document["meaning"], "client_installation_diagnostic_only")


if __name__ == "__main__":
    unittest.main()
