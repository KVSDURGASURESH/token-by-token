#!/usr/bin/env python3
"""Validate and launch two detached caffeinated local watchdog processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import secrets
import subprocess
import sys
import time
from pathlib import Path

from local_watchdog import (
    SubprocessRunpodClient,
    _atomic_json,
    _delete_with_proof,
    read_secure_resource_id,
)
from validated_plan import load_compiled_plan


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_script_hashes(plan: dict[str, object], watchdog: Path, launcher: Path) -> None:
    guards = plan.get("guards")
    if not isinstance(guards, dict) or guards.get("mode") != "local_only_acknowledged":
        raise ValueError("plan does not bind local-only guard mode")
    if _sha256(watchdog) != guards.get("watchdog_script_sha256"):
        raise ValueError("watchdog script digest does not match the approved plan")
    if _sha256(launcher) != guards.get("launcher_script_sha256"):
        raise ValueError("launcher script digest does not match the approved plan")


def build_watchdog_commands(
    *,
    python_bin: str,
    caffeinate_bin: str,
    watchdog_script: Path,
    plan_path: Path,
    resource_id_file: Path,
    evidence_dir: Path,
    launch_nonce: str = "",
) -> list[list[str]]:
    commands = []
    marker_dir = evidence_dir / "markers"
    for role in ("primary", "secondary"):
        commands.append(
            [
                caffeinate_bin,
                "-i",
                python_bin,
                str(watchdog_script),
                "--role",
                role,
                "--plan",
                str(plan_path),
                "--resource-id-file",
                str(resource_id_file),
                "--marker-dir",
                str(marker_dir),
                "--checkpoint",
                str(evidence_dir / f"watchdog-{role}.json"),
                "--armed-checkpoint",
                str(evidence_dir / f"watchdog-{role}-armed.json"),
                "--heartbeat",
                str(evidence_dir / f"watchdog-{role}-heartbeat.json"),
                "--launch-nonce",
                launch_nonce,
            ]
        )
    return commands


def launch_watchdog_processes(
    *,
    commands: list[list[str]],
    evidence_dir: Path,
    popen_factory=subprocess.Popen,
    settle_sleep=time.sleep,
    arming_timeout_seconds: int,
    launch_nonce: str,
    on_failure=None,
) -> dict[str, int]:
    """Launch both watchdogs and return only after both provider-poll handshakes."""

    roles = ("primary", "secondary")
    if not launch_nonce:
        raise ValueError("launch nonce must not be empty")
    for role in roles:
        for suffix in ("armed.json", "heartbeat.json"):
            path = evidence_dir / f"watchdog-{role}-{suffix}"
            if path.exists():
                path.unlink()
    _atomic_json(
        evidence_dir / "watchdog-launch.json",
        {"schema_version": 1, "launch_nonce": launch_nonce},
    )
    processes = {}
    logs = []
    try:
        for command, role in zip(commands, roles, strict=True):
            log = (evidence_dir / f"watchdog-{role}.log").open("ab", buffering=0)
            logs.append(log)
            processes[role] = popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        for _ in range(max(1, arming_timeout_seconds * 10)):
            if any(process.poll() is not None for process in processes.values()):
                raise RuntimeError("watchdog failed to stay alive during arming")
            handshakes = []
            for role in roles:
                path = evidence_dir / f"watchdog-{role}-armed.json"
                if not path.is_file():
                    break
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    break
                handshakes.append(
                    isinstance(payload, dict)
                    and payload.get("armed") is True
                    and payload.get("role") == role
                    and payload.get("launch_nonce") == launch_nonce
                )
            if len(handshakes) == len(roles) and all(handshakes):
                return {role: process.pid for role, process in processes.items()}
            settle_sleep(0.1)
        raise RuntimeError("watchdogs failed to arm before the bound timeout")
    except Exception:
        (evidence_dir / "markers").mkdir(parents=True, exist_ok=True)
        (evidence_dir / "markers" / "teardown-now").touch(exist_ok=True)
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        if on_failure is not None:
            on_failure()
        raise
    finally:
        for log in logs:
            log.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--resource-id-file", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--watchdog-script", type=Path, default=Path(__file__).with_name("local_watchdog.py"))
    args = parser.parse_args()

    plan = load_compiled_plan(args.plan)
    validate_script_hashes(plan, args.watchdog_script, Path(__file__))
    caffeinate_bin = shutil.which("caffeinate")
    if not caffeinate_bin:
        raise RuntimeError("caffeinate is required for local-only guard mode")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.evidence_dir, 0o700)
    resource_id = read_secure_resource_id(args.resource_id_file)
    launch_nonce = secrets.token_hex(32)
    commands = build_watchdog_commands(
        python_bin=sys.executable,
        caffeinate_bin=caffeinate_bin,
        watchdog_script=args.watchdog_script,
        plan_path=args.plan,
        resource_id_file=args.resource_id_file,
        evidence_dir=args.evidence_dir,
        launch_nonce=launch_nonce,
    )
    guards = plan["guards"]

    def emergency_teardown() -> None:
        proof = _delete_with_proof(
            client=SubprocessRunpodClient(
                cli_timeout_seconds=int(guards["cli_timeout_seconds"])
            ),
            resource_id=resource_id,
            delays=tuple(guards["delete_retry_delays_seconds"]),
            sleep=time.sleep,
        )
        _atomic_json(args.evidence_dir / "watchdog-arming-failure.json", proof)
        if not all(
            proof[key]
            for key in (
                "deletion_acknowledged",
                "inventory_absent",
                "direct_not_found",
                "final_balance_observed",
            )
        ):
            raise RuntimeError("emergency teardown proof is incomplete")

    pids = launch_watchdog_processes(
        commands=commands,
        evidence_dir=args.evidence_dir,
        arming_timeout_seconds=int(plan["guards"]["arming_timeout_seconds"]),
        launch_nonce=launch_nonce,
        on_failure=emergency_teardown,
    )
    (args.evidence_dir / "watchdog-pids.json").write_text(
        json.dumps(pids, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
