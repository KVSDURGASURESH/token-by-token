#!/usr/bin/env python3
"""Compile a manifest with explicit live-input JSON without provider calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compile_plan import approval_phrase, compile_plan, plan_digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--live-inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    live_inputs = json.loads(args.live_inputs.read_text(encoding="utf-8"))
    plan = compile_plan(manifest, live_inputs)
    digest = plan_digest(plan)
    envelope: dict[str, object] = {
        "plan_sha256": digest,
        "execution_ready": plan["execution_ready"],
        "approval_phrase": approval_phrase(plan) if plan["execution_ready"] else None,
        "plan": plan,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "plan_sha256": digest,
        "execution_ready": plan["execution_ready"],
        "provider_calls": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
