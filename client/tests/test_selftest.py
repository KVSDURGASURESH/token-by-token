from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from token_by_token_cli.contracts import episode_manifest
from token_by_token_cli.errors import ClientError
from token_by_token_cli.selftest import run_selftest
from token_by_token_cli.verify import verify_bundle


CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"


class SelfTestCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "selftest.tbt.zip"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONPATH": str(CLIENT_SRC)}
        return subprocess.run([sys.executable, "-m", "token_by_token_cli", *args], text=True, capture_output=True, env=env, check=False)

    def test_selftest_requires_literal_offline_flag(self) -> None:
        result = self.run_cli("episode", "2", "selftest", "--output", str(self.output))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--offline", result.stderr)
        self.assertFalse(self.output.exists())

    def test_selftest_refuses_existing_output_archive(self) -> None:
        self.output.write_bytes(b"preserve me")
        result = self.run_cli("episode", "2", "selftest", "--offline", "--output", str(self.output))
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.output.read_bytes(), b"preserve me")
        self.assertNotIn("Traceback", result.stderr)

    def test_selftest_produces_a_verified_synthetic_bundle(self) -> None:
        result = self.run_cli("episode", "2", "selftest", "--offline", "--users", "4", "--seed", "42", "--output", str(self.output), "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["classification"], "synthetic_mock")
        self.assertEqual(report["episode"], 2)
        self.assertEqual(report["users"], 4)
        self.assertEqual(verify_bundle(self.output).digest, report["digest"])

    def test_every_episode_runs_the_same_safe_offline_path(self) -> None:
        for number in range(17):
            with self.subTest(number=number):
                output = self.root / f"episode-{number:02d}.tbt.zip"
                users = episode_manifest(number)["load_levels"][0]
                result = self.run_cli("episode", str(number), "selftest", "--offline", "--users", str(users), "--output", str(output), "--format", "json")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["episode"], number)
                self.assertEqual(verify_bundle(output).classification, "synthetic_mock")

    def test_undeclared_users_fail_without_creating_output(self) -> None:
        result = self.run_cli("episode", "2", "selftest", "--offline", "--users", "3", "--output", str(self.output))
        self.assertEqual(result.returncode, 3)
        self.assertIn("INVALID_USERS", result.stderr)
        self.assertFalse(self.output.exists())

    def test_publish_failure_preserves_concurrent_owner_output(self) -> None:
        def fail_after_owner_create(source: Path, destination: Path) -> None:
            Path(destination).write_bytes(b"concurrent owner data")
            raise OSError("simulated link failure")

        with mock.patch("token_by_token_cli.selftest.os.link", side_effect=fail_after_owner_create):
            with self.assertRaisesRegex(ClientError, "OUTPUT_WRITE_FAILED"):
                run_selftest(
                    self.output,
                    episode=2,
                    users=4,
                    seed=42,
                    offline=True,
                    stop_requested=lambda: False,
                )
        self.assertEqual(self.output.read_bytes(), b"concurrent owner data")


if __name__ == "__main__":
    unittest.main()
