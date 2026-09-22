#!/usr/bin/env python3
"""Render the README episode table from the dashboard's single episode registry."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BEGIN = "<!-- BEGIN EPISODE INDEX -->"
END = "<!-- END EPISODE INDEX -->"


def table(registry: Path, root: Path) -> str:
    catalog = json.loads(registry.read_text(encoding="utf-8"))
    rows = ["| Episode | Experiment | Status | Evidence |", "|---:|---|---|---|"]
    ids, numbers = set(), set()
    for episode in catalog["episodes"]:
        identifier, number = episode["id"], episode["number"]
        if not re.fullmatch(r"episode-\d+", identifier) or identifier in ids:
            raise ValueError("Episode IDs must be unique and use episode-N.")
        if type(number) is not int or number < 0 or number in numbers or identifier != f"episode-{number}":
            raise ValueError("Episode numbers must be unique nonnegative integers matching their IDs.")
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
