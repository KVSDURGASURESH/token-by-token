from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
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
        self.assertIn("evidence", result.stdout)
        self.assertNotIn("runs submit", result.stdout)
        self.assertNotIn("auth login", result.stdout)

    def test_unknown_command_is_a_clean_usage_error(self) -> None:
        result = self.run_cli("runs", "submit")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_episode_command_accepts_the_catalog_range(self) -> None:
        result = self.run_cli("episode", "16", "describe")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("NOT_IMPLEMENTED", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
