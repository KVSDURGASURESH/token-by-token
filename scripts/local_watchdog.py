#!/usr/bin/env python3
"""Local monotonic Runpod deletion watchdog for an acknowledged degraded guard."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol

from validated_plan import load_compiled_plan


class RunpodClient(Protocol):
    def balance_usd(self) -> str: ...
    def delete_pod(self, resource_id: str) -> bool: ...
    def inventory_absent(self, resource_id: str) -> bool: ...
    def direct_not_found(self, resource_id: str) -> bool: ...


@dataclass(frozen=True)
class GuardConfig:
    max_usd: Decimal
    initial_balance_usd: Decimal
    hourly_usd: Decimal
    deadline_seconds: int
    poll_interval_seconds: int
    soft_stop_fraction: Decimal
    teardown_fraction: Decimal
    delete_retry_delays_seconds: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.max_usd <= 0 or self.hourly_usd <= 0 or self.initial_balance_usd < 0:
            raise ValueError("budget and hourly rate must be positive")
        if self.deadline_seconds < 1 or self.poll_interval_seconds < 1:
            raise ValueError("deadline and poll interval must be positive")
        if not Decimal("0") < self.soft_stop_fraction < self.teardown_fraction < Decimal("1"):
            raise ValueError("guard fractions must be ordered between zero and one")
        if len(self.delete_retry_delays_seconds) < 2:
            raise ValueError("at least two delete attempts are required")


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _mark(marker_dir: Path, name: str) -> None:
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / name).touch(exist_ok=True)


def read_secure_resource_id(path: Path) -> str:
    resource_stat = path.lstat()
    if not stat.S_ISREG(resource_stat.st_mode) or stat.S_ISLNK(resource_stat.st_mode):
        raise ValueError("resource id file must be a regular non-symlink file")
    if stat.S_IMODE(resource_stat.st_mode) != 0o600:
        raise ValueError("resource id file permissions must be exactly 0600")
    resource_id = path.read_text(encoding="utf-8").strip()
    if not resource_id:
        raise ValueError("resource id file must not be empty")
    return resource_id


def _delete_with_proof(
    *,
    client: RunpodClient,
    resource_id: str,
    delays: tuple[int, ...],
    sleep: Callable[[float], None],
) -> dict[str, object]:
    deletion_acknowledged = False
    inventory_absent = False
    direct_not_found = False
    attempts = 0
    final_balance = ""
    provider_failures = 0
    for delay in delays:
        if delay:
            sleep(delay)
        attempts += 1
        try:
            deletion_acknowledged = client.delete_pod(resource_id) or deletion_acknowledged
            inventory_absent = client.inventory_absent(resource_id)
            direct_not_found = client.direct_not_found(resource_id)
            final_balance = client.balance_usd()
            if inventory_absent and direct_not_found and final_balance:
                deletion_acknowledged = True
                break
        except RuntimeError:
            provider_failures += 1
    return {
        "delete_attempts": attempts,
        "deletion_acknowledged": deletion_acknowledged,
        "inventory_absent": inventory_absent,
        "direct_not_found": direct_not_found,
        "final_balance_observed": bool(final_balance),
        "final_balance_usd": final_balance,
        "provider_call_failures": provider_failures,
    }


def run_watchdog(
    *,
    config: GuardConfig,
    client: RunpodClient,
    resource_id: str,
    role: str,
    marker_dir: Path,
    checkpoint_path: Path,
    armed_checkpoint_path: Path | None = None,
    heartbeat_path: Path | None = None,
    launch_nonce: str = "",
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    if role not in {"primary", "secondary"}:
        raise ValueError("role must be primary or secondary")
    if not resource_id.strip():
        raise ValueError("resource id must not be empty")
    if armed_checkpoint_path is not None and not launch_nonce:
        raise ValueError("launch nonce is required for executable watchdog arming")

    start = monotonic()
    soft_stop_usd = config.max_usd * config.soft_stop_fraction
    teardown_usd = config.max_usd * config.teardown_fraction
    trigger = ""
    elapsed = Decimal("0")
    exposure = Decimal("0")
    modeled_exposure = Decimal("0")
    observed_debit = Decimal("0")
    current_balance = config.initial_balance_usd
    balance_poll_failures = 0
    armed = False
    while True:
        elapsed = Decimal(str(max(0.0, monotonic() - start)))
        modeled_exposure = config.hourly_usd * elapsed / Decimal(3600)
        try:
            current_balance = Decimal(client.balance_usd())
            if not armed:
                armed = True
                if armed_checkpoint_path is not None:
                    _atomic_json(
                        armed_checkpoint_path,
                        {
                            "schema_version": 1,
                            "role": role,
                            "armed": True,
                            "launch_nonce": launch_nonce,
                        },
                    )
            provider_poll_ok = True
        except RuntimeError:
            balance_poll_failures += 1
            provider_poll_ok = False
        if heartbeat_path is not None:
            _atomic_json(
                heartbeat_path,
                {
                    "schema_version": 1,
                    "role": role,
                    "launch_nonce": launch_nonce,
                    "monotonic_seconds": monotonic(),
                    "provider_poll_ok": provider_poll_ok,
                },
            )
        observed_debit = max(Decimal("0"), config.initial_balance_usd - current_balance)
        exposure = max(modeled_exposure, observed_debit)
        if exposure >= soft_stop_usd:
            _mark(marker_dir, "stop-new-arms")
        if exposure >= teardown_usd:
            trigger = "teardown_threshold"
        elif elapsed >= Decimal(config.deadline_seconds):
            trigger = "deadline"
        if trigger:
            _mark(marker_dir, "teardown-now")
            break
        sleep(config.poll_interval_seconds)

    proof = _delete_with_proof(
        client=client,
        resource_id=resource_id,
        delays=config.delete_retry_delays_seconds,
        sleep=sleep,
    )
    result = {
        "schema_version": 1,
        "role": role,
        "clock": "monotonic",
        "trigger": trigger,
        "elapsed_seconds": int(elapsed),
        "modeled_exposure_usd": format(modeled_exposure, ".6f"),
        "observed_balance_debit_usd": format(observed_debit, ".6f"),
        "guarded_exposure_usd": format(exposure, ".6f"),
        "balance_poll_failures": balance_poll_failures,
        **proof,
    }
    _atomic_json(checkpoint_path, result)
    if not (
        result["deletion_acknowledged"]
        and result["inventory_absent"]
        and result["direct_not_found"]
        and result["final_balance_observed"]
    ):
        raise RuntimeError("watchdog teardown proof is incomplete")
    return result


class SubprocessRunpodClient:
    def __init__(self, runpodctl_bin: str = "runpodctl", cli_timeout_seconds: int = 10) -> None:
        self.runpodctl_bin = runpodctl_bin
        self.cli_timeout_seconds = cli_timeout_seconds

    def _run(self, *args: str) -> tuple[int, object]:
        try:
            completed = subprocess.run(
                [self.runpodctl_bin, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.cli_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("runpodctl call timed out") from exc
        raw = completed.stdout.strip() or completed.stderr.strip() or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("runpodctl returned non-JSON output") from exc
        return completed.returncode, payload

    def balance_usd(self) -> str:
        code, payload = self._run("user")
        if code != 0 or not isinstance(payload, dict) or "clientBalance" not in payload:
            raise RuntimeError("unable to read final Runpod balance")
        return format(Decimal(str(payload["clientBalance"])), "f")

    def delete_pod(self, resource_id: str) -> bool:
        code, payload = self._run("pod", "delete", resource_id, "-o", "json")
        if code == 0:
            return True
        if isinstance(payload, dict) and payload.get("code") == "not_found":
            return False
        raise RuntimeError("permanent pod deletion failed")

    def inventory_absent(self, resource_id: str) -> bool:
        code, payload = self._run("pod", "list", "--all", "-o", "json")
        if code != 0:
            raise RuntimeError("unable to verify pod inventory")
        if isinstance(payload, list):
            pods = payload
        elif isinstance(payload, dict) and isinstance(payload.get("pods"), list):
            pods = payload["pods"]
        else:
            raise RuntimeError("unable to parse pod inventory")
        if any(
            not isinstance(pod, dict)
            or not isinstance(pod.get("id"), str)
            or not pod["id"]
            for pod in pods
        ):
            raise RuntimeError("unable to parse pod inventory entries")
        return all(pod["id"] != resource_id for pod in pods)

    def direct_not_found(self, resource_id: str) -> bool:
        code, payload = self._run("pod", "get", resource_id, "-o", "json")
        return bool(
            code != 0
            and isinstance(payload, dict)
            and payload.get("code") == "not_found"
        )


def _config_from_plan(plan: dict[str, object]) -> GuardConfig:
    guards = plan["guards"]
    cost = plan["cost"]
    budget = plan["budget"]
    live_inputs = plan["live_inputs"]
    if not isinstance(guards, dict) or guards.get("mode") != "local_only_acknowledged":
        raise ValueError("plan does not authorize local-only watchdog mode")
    if not isinstance(cost, dict) or not isinstance(budget, dict) or not isinstance(live_inputs, dict):
        raise ValueError("plan is missing cost or budget fields")
    account = live_inputs.get("account")
    if not isinstance(account, dict):
        raise ValueError("plan is missing the initial account balance")
    return GuardConfig(
        max_usd=Decimal(str(budget["max_usd"])),
        initial_balance_usd=Decimal(str(account["balance_usd"])),
        hourly_usd=Decimal(str(guards["hourly_usd_exact"])),
        deadline_seconds=int(guards["local_teardown_trigger_seconds"]),
        poll_interval_seconds=int(guards["poll_interval_seconds"]),
        soft_stop_fraction=Decimal(str(guards["start_no_new_arms_at_fraction"])),
        teardown_fraction=Decimal(str(guards["teardown_at_fraction"])),
        delete_retry_delays_seconds=tuple(guards["delete_retry_delays_seconds"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("primary", "secondary"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--resource-id-file", required=True, type=Path)
    parser.add_argument("--marker-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--armed-checkpoint", required=True, type=Path)
    parser.add_argument("--heartbeat", required=True, type=Path)
    parser.add_argument("--launch-nonce", required=True)
    parser.add_argument("--runpodctl-bin", default="runpodctl")
    args = parser.parse_args()

    plan = load_compiled_plan(args.plan)
    resource_id = read_secure_resource_id(args.resource_id_file)
    guards = plan["guards"]
    run_watchdog(
        config=_config_from_plan(plan),
        client=SubprocessRunpodClient(
            args.runpodctl_bin, int(guards["cli_timeout_seconds"])
        ),
        resource_id=resource_id,
        role=args.role,
        marker_dir=args.marker_dir,
        checkpoint_path=args.checkpoint,
        armed_checkpoint_path=args.armed_checkpoint,
        heartbeat_path=args.heartbeat,
        launch_nonce=args.launch_nonce,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
