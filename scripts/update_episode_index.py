#!/usr/bin/env python3
"""Render the README episode table from the dashboard's single episode registry."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BEGIN = "<!-- BEGIN EPISODE INDEX -->"
END = "<!-- END EPISODE INDEX -->"
NUMBERING_VERSION = "episode-catalog.v2"
OLD_TO_CURRENT = {0: 0, 1: 1, 2: 2, 3: 11, 4: 12, 5: 13, 6: 14, 7: 15,
                  8: 3, 9: 4, 10: 5, 11: 6, 12: 7, 13: 8, 14: 9, 15: 10, 16: 16}


def table(registry: Path, root: Path) -> str:
    catalog = json.loads(registry.read_text(encoding="utf-8"))
    numbering = catalog.get("episodeNumbering", {})
    if numbering.get("version") != NUMBERING_VERSION:
        raise ValueError(f"Episode registry must use {NUMBERING_VERSION}.")
    if numbering.get("oldToCurrent") != {str(old): new for old, new in OLD_TO_CURRENT.items()}:
        raise ValueError("Episode registry old-to-current compatibility map is invalid.")
    rows = ["| Episode | Experiment | Status | Evidence |", "|---:|---|---|---|"]
    ids, numbers = set(), set()
    for episode in catalog["episodes"]:
        identifier, number = episode["id"], episode["number"]
        if not re.fullmatch(r"episode-\d+", identifier) or identifier in ids:
            raise ValueError("Episode IDs must be unique and use episode-N.")
        if type(number) is not int or number < 0 or number in numbers or identifier != f"episode-{number}":
            raise ValueError("Episode numbers must be unique nonnegative integers matching their IDs.")
        previous = episode.get("previousNumber")
        if type(previous) is not int or OLD_TO_CURRENT.get(previous) != number:
            raise ValueError("Episode previousNumber must match the versioned compatibility map.")
        ids.add(identifier)
        numbers.add(number)
        status = episode["status"]
        if status not in {"available", "planned"}:
            raise ValueError("Episode status must be available or planned.")
        title, evidence = episode["title"], episode["evidence"]
        for value in (title, evidence):
            if not isinstance(value, str) or not value.strip() or any(c in value for c in "|\n\r[]<>"):
                raise ValueError("Episode title/evidence must be plain single-line table text.")
        if status == "available":
            guide = episode["guide"]
            if not re.fullmatch(r"episodes/[a-z0-9-]+/README\.md", guide) or not (root / guide).is_file():
                raise ValueError("Available episodes need an existing episodes/<slug>/README.md guide.")
            if not (root / guide).resolve().is_relative_to(root.resolve()):
                raise ValueError("Episode guide must stay inside the repository.")
            title = f"[{title}]({guide})"
        rows.append(f"| {number} | {title} | {status.capitalize()} | {evidence} |")
    if [episode["number"] for episode in catalog["episodes"]] != list(range(17)):
        raise ValueError("Episode registry must be ordered from 0 through 16.")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--registry", type=Path, help="Override only when preparing a package from source.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    readme = args.root / "README.md"
    source = readme.read_text(encoding="utf-8")
    if source.count(BEGIN) != 1 or source.count(END) != 1 or source.index(BEGIN) >= source.index(END):
        raise ValueError("README must contain one ordered pair of episode-index markers.")
    registry = args.registry or args.root / "dashboard/src/data/episodes.json"
    replacement = BEGIN + "\n" + table(registry, args.root) + "\n" + END
    updated = source[:source.index(BEGIN)] + replacement + source[source.index(END) + len(END):]
    if args.check:
        if updated != source:
            raise SystemExit("Episode index is stale. Run python3 scripts/update_episode_index.py")
        print("Episode index matches the registry.")
    else:
        readme.write_text(updated, encoding="utf-8")
        print("Updated README episode index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
