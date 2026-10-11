from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from token_by_token_cli.bundle import write_synthetic_bundle
from token_by_token_cli.contracts import episode_manifest
from token_by_token_cli.errors import ClientError
from token_by_token_cli.offline import run_synthetic_episode
from token_by_token_cli.verify import verify_bundle


CLIENT_SRC = Path(__file__).resolve().parents[1] / "src"


class BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "bundle.tbt.zip"
        manifest = episode_manifest(2)
        self.events = list(run_synthetic_episode(manifest, users=4, seed=42, stop_requested=lambda: False))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_bundle_round_trip_is_complete_and_synthetic(self) -> None:
        bundle = write_synthetic_bundle(self.events, self.output)
        report = verify_bundle(bundle)
        self.assertEqual(report.classification, "synthetic_mock")
        self.assertEqual(report.files, ("events.jsonl", "replay.json"))
        self.assertEqual(len(report.digest), 64)

    def test_bundle_bytes_are_deterministic(self) -> None:
        first = write_synthetic_bundle(self.events, self.output)
        second = write_synthetic_bundle(self.events, self.root / "second.tbt.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_writer_refuses_wrong_extension_and_existing_file(self) -> None:
        with self.assertRaisesRegex(ClientError, "BUNDLE_PATH"):
            write_synthetic_bundle(self.events, self.root / "bundle.zip")
        self.output.write_bytes(b"owner data")
        with self.assertRaisesRegex(ClientError, "OUTPUT_EXISTS"):
            write_synthetic_bundle(self.events, self.output)
        self.assertEqual(self.output.read_bytes(), b"owner data")

    def test_writer_preserves_dangling_output_symlink(self) -> None:
        dangling = self.root / "dangling.tbt.zip"
        dangling.symlink_to(self.root / "missing-owner-target")
        with self.assertRaisesRegex(ClientError, "OUTPUT_EXISTS"):
            write_synthetic_bundle(self.events, dangling)
        self.assertTrue(dangling.is_symlink())

    def test_cli_verifies_bundle_as_json(self) -> None:
        write_synthetic_bundle(self.events, self.output)
        env = {**os.environ, "PYTHONPATH": str(CLIENT_SRC)}
        result = subprocess.run(
            [sys.executable, "-m", "token_by_token_cli", "evidence", "verify", str(self.output), "--format", "json"],
            text=True, capture_output=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["classification"], "synthetic_mock")
        self.assertTrue(document["valid"])

    def test_mixed_classification_is_rejected(self) -> None:
        write_synthetic_bundle(self.events, self.output)
        with zipfile.ZipFile(self.output, "r") as archive:
            events = archive.read("events.jsonl")
            inventory = json.loads(archive.read("inventory.json"))
            replay = json.loads(archive.read("replay.json"))
        replay["classification"] = "recorded"
        replay_bytes = (json.dumps(replay, sort_keys=True, separators=(",", ":")) + "\n").encode()
        replay_entry = next(entry for entry in inventory["entries"] if entry["path"] == "replay.json")
        replay_entry["size"] = len(replay_bytes)
        replay_entry["sha256"] = hashlib.sha256(replay_bytes).hexdigest()
        inventory_bytes = (json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n").encode()
        self.output.unlink()
        with zipfile.ZipFile(self.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("inventory.json", inventory_bytes)
            archive.writestr("events.jsonl", events)
            archive.writestr("replay.json", replay_bytes)
        with self.assertRaisesRegex(ClientError, "MIXED_CLASSIFICATION"):
            verify_bundle(self.output)


if __name__ == "__main__":
    unittest.main()
