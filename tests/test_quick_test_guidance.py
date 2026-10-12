from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QuickTestGuidanceTests(unittest.TestCase):
    def test_quick_test_docs_describe_the_supported_cli_surface(self) -> None:
        guide = (ROOT / "docs/episode-1-preparation/quick-test.md").read_text(encoding="utf-8")

        self.assertNotIn("#quick-test", guide)
        self.assertNotIn("#episode-runner", guide)
        self.assertNotIn("press **Start**", guide)
        self.assertNotIn("Use **Save config**", guide)
        self.assertIn("public dashboard is informational", guide)
        self.assertIn("scripts/quick-test request", guide)
        self.assertIn("scripts/quick-test compare", guide)
        self.assertIn("scripts/quick-test episode", guide)

    def test_bridge_startup_message_does_not_advertise_removed_browser_controls(self) -> None:
        launcher = (ROOT / "scripts/episode1_playground.py").read_text(encoding="utf-8")

        self.assertNotIn("Episode test console:", launcher)
        self.assertNotIn("/#episode-runner", launcher)
        self.assertIn("request controls are CLI-only", launcher)
