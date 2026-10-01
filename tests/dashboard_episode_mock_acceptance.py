"""Synthetic browser acceptance test for the episode dashboard.

This test requires a locally running demo bridge and never contacts provider APIs.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys

from playwright.sync_api import sync_playwright


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8877").rstrip("/")
OUTPUT = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/validation/mock-2026-10-01")
EXPECTED_CELLS = [2, 2, 1, 1, 1, 2, 1, 2, 2, 1, 1, 1, 1, 2, 1, 2]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.environ.get(
                "CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ),
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"{BASE}/#episode-runner", wait_until="networkidle")
            page.get_by_role("heading", name="Fire the test pack. Keep the claim honest.").wait_for()
            background = page.locator("body").evaluate("node => getComputedStyle(node).backgroundColor")
            channels = [int(value) for value in re.findall(r"\d+", background)[:3]]
            assert sum(channels) < 180, f"expected dark background, observed {background}"

            episode_select = page.locator(".runner-controls select")
            for episode, expected in enumerate(EXPECTED_CELLS, start=1):
                episode_select.select_option(str(episode))
                observed = page.locator(".runner-cells > article").count()
                assert observed == expected, f"episode {episode}: expected {expected} cells, got {observed}"

            page.get_by_role("button", name="Run Episode 16").click()
            page.get_by_text("Run complete", exact=True).wait_for(timeout=30_000)
            page.get_by_text("20/20", exact=True).wait_for()
            assert page.get_by_text("LIVE", exact=True).count() == 0
            assert page.get_by_text("MEASURED", exact=True).count() == 4
            assert page.get_by_text("Unavailable from endpoint API", exact=True).count() == 2
            metric_values = page.locator(".grafana-panel:has-text('MEASURED') > strong")
            assert metric_values.count() == 4
            for index in range(metric_values.count()):
                assert "–" in metric_values.nth(index).inner_text()
            assert page.locator(".spark-bars b").count() > 0
            page.screenshot(path=str(OUTPUT / "episode-16-complete-desktop.png"), full_page=True)

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.goto(f"{BASE}/#episodes", wait_until="networkidle")
            mobile.get_by_role("heading", name="Token by Token", exact=True).wait_for()
            overflow = mobile.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            assert not overflow, "episode index has horizontal overflow at 390px"
            mobile_background = mobile.locator("body").evaluate("node => getComputedStyle(node).backgroundColor")
            mobile_channels = [int(value) for value in re.findall(r"\d+", mobile_background)[:3]]
            assert sum(mobile_channels) < 180, f"expected dark mobile background, observed {mobile_background}"
            mobile.screenshot(path=str(OUTPUT / "episode-index-mobile.png"), full_page=True)
            assert not errors, f"page errors: {errors}"
            print("episodes=16 cells=20 requests=20/20 metric_panels=4 gpu_unavailable=2 theme=dark")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
