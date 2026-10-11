from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from token_by_token_cli.contracts import validate_document


CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"


class EpisodeDescribeTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONPATH": str(CLIENT_SRC)}
        return subprocess.run([sys.executable, "-m", "token_by_token_cli", *args], text=True, capture_output=True, env=env, check=False)

    def test_catalog_lists_every_episode_without_private_details(self) -> None:
        result = self.run_cli("episodes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(1 for line in result.stdout.splitlines() if line.startswith("Episode ")), 17)
        self.assertIn("Episode 00", result.stdout)
        self.assertIn("Episode 16", result.stdout)
        self.assertNotIn("profile", result.stdout.lower())

    def test_episode_2_describe_names_public_controls_and_exclusions(self) -> None:
        result = self.run_cli("episode", "2", "describe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Equal-work runtime baseline", result.stdout)
        self.assertIn("2, 4, 8, 12, 16, 24", result.stdout)
        self.assertIn("Speculative decoding: excluded", result.stdout)
        self.assertNotIn("profile", result.stdout.lower())

    def test_all_episode_descriptions_are_schema_valid(self) -> None:
        for number in range(17):
            with self.subTest(number=number):
                result = self.run_cli("episode", str(number), "describe", "--format", "json")
                self.assertEqual(result.returncode, 0, result.stderr)
                document = json.loads(result.stdout)
                validate_document("episode-manifest.v1", document)
                self.assertEqual(document["protocol"], f"episode-{number:02d}-public-v1")


if __name__ == "__main__":
    unittest.main()
