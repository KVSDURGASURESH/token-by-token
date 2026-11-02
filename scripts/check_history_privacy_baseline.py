#!/usr/bin/env python3
"""Require reachable-history privacy findings to match an approved fingerprint set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import check_publication_privacy as privacy


def fingerprint(finding: privacy.Finding) -> tuple[str, int, str]:
    return (finding.location, finding.line, finding.category)


def load_baseline(path: Path) -> set[tuple[str, int, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "token-by-token.history-privacy-baseline.v1":
        raise ValueError("unsupported history privacy baseline schema")
    return {
        (item["location"], int(item["line"]), item["category"])
        for item in data.get("approved_findings", [])
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("privacy/history-privacy-baseline.v1.json"),
    )
    args = parser.parse_args()
    try:
        expected = load_baseline(args.baseline)
        observed = {fingerprint(item) for item in privacy.check(args.root, history=True)}
    except (OSError, ValueError, json.JSONDecodeError, privacy.PrivacyCheckError) as exc:
        print(f"history-privacy-baseline error: {exc}")
        return 2

    added = sorted(observed - expected)
    removed = sorted(expected - observed)
    if added or removed:
        for location, line, category in added:
            print(f"new file={location} line={line} category={category}")
        for location, line, category in removed:
            print(f"missing file={location} line={line} category={category}")
        print(
            "history-privacy-baseline failed: "
            f"approved={len(expected)} observed={len(observed)} "
            f"new={len(added)} missing={len(removed)}"
        )
        return 1

    print(
        "history-privacy-baseline passed: "
        f"observed findings exactly match {len(expected)} approved fingerprints"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
