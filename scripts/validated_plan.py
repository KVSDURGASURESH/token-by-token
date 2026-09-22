"""Load a compiler-produced plan envelope and verify its complete binding."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from compile_plan import PlanValidationError, approval_phrase, plan_digest


def load_compiled_plan(path: Path) -> dict[str, Any]:
    """Reject hand-written, tampered, planning-only, or digest-mismatched plans."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping) or set(document) != {
        "plan_sha256",
        "execution_ready",
        "approval_phrase",
        "plan",
    }:
        raise PlanValidationError("plan must be an exact compile_plan_cli envelope")
    plan = document["plan"]
    if not isinstance(plan, Mapping):
        raise PlanValidationError("compiled plan payload is invalid")
    observed_digest = plan_digest(plan)
    supplied_digest = document["plan_sha256"]
    if not isinstance(supplied_digest, str) or not hmac.compare_digest(
        supplied_digest, observed_digest
    ):
        raise PlanValidationError("plan_sha256 does not match compiler-derived plan")
    if document["execution_ready"] is not True or plan.get("execution_ready") is not True:
        raise PlanValidationError("plan is not execution-ready")
    if document["approval_phrase"] != approval_phrase(plan):
        raise PlanValidationError("approval phrase does not match compiler-derived plan")
    return dict(plan)
