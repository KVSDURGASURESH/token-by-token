from __future__ import annotations

import json
from pathlib import Path
import unittest

from token_by_token_cli.contracts import episode_manifest
from token_by_token_cli.offline import run_synthetic_episode


EXPECTED = Path(__file__).with_name("fixtures") / "offline-expected-events.json"


class OfflineEngineTests(unittest.TestCase):
    def test_same_manifest_produces_byte_identical_events(self) -> None:
        manifest = episode_manifest(2)
        first = [event.to_json() for event in run_synthetic_episode(manifest, users=4, seed=42, stop_requested=lambda: False)]
        second = [event.to_json() for event in run_synthetic_episode(manifest, users=4, seed=42, stop_requested=lambda: False)]
        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(EXPECTED.read_text(encoding="utf-8")))

    def test_episode_identity_changes_the_synthetic_stream(self) -> None:
        first = [event.to_json() for event in run_synthetic_episode(episode_manifest(0), users=4, seed=42, stop_requested=lambda: False)]
        second = [event.to_json() for event in run_synthetic_episode(episode_manifest(1), users=16, seed=42, stop_requested=lambda: False)]
        self.assertNotEqual(first, second)
        self.assertEqual(first[0]["payload"]["episode"], 0)
        self.assertEqual(second[0]["payload"]["episode"], 1)

    def test_stop_request_emits_terminal_interrupted_event(self) -> None:
        calls = iter([False, False, True])
        events = list(run_synthetic_episode(episode_manifest(2), users=4, seed=42, stop_requested=lambda: next(calls, True)))
        self.assertEqual(events[-1].kind, "run_interrupted")
        self.assertFalse(any(event.kind == "run_completed" for event in events))

    def test_users_must_be_declared_by_the_episode(self) -> None:
        with self.assertRaisesRegex(ValueError, "not declared"):
            list(run_synthetic_episode(episode_manifest(2), users=3, seed=42, stop_requested=lambda: False))


if __name__ == "__main__":
    unittest.main()
