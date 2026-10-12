#!/usr/bin/env python3
"""Fail when private studio material is tracked in the public repository."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PREFIXES = (
    ".agents/skills/inference-lab-publication",
    ".agents/skills/token-by-token-video",
    ".superpowers/",
    "brag-output-",
    "dashboard/",
    "docs/publication-drafts/",
    "docs/seo-operations.md",
    "skills/inference-lab-publication/",
    "skills/token-by-token-video/",
    "tests/dashboard_",
    "tests/test_video_pipeline_v2.py",
    "video/",
)


def main() -> int:
    output = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    paths = sorted(item.decode("utf-8") for item in output.split(b"\0") if item)
    blocked = [path for path in paths if path.startswith(FORBIDDEN_PREFIXES)]
    if blocked:
        print("private studio paths are tracked in the public repository:")
        for path in blocked:
            print(f"- {path}")
        return 1
    print("Public repository boundary passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
