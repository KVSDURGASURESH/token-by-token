#!/usr/bin/env python3
"""Thin Episode 1 watchdog entrypoint; provider construction remains digest-bound."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import episode1_watchdog as watchdog
from episode1_watchdog import WatchdogError, observe_clock_domain, read_permit, load_provider_factory, run_guard

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--role", choices=("primary", "secondary"), required=True)
    p.add_argument("--state-directory", type=Path, required=True)
    p.add_argument("--guard-directory", type=Path, required=True)
    p.add_argument("--adapter", required=True)
    p.add_argument("--adapter-source", type=Path, required=True)
    p.add_argument("--heartbeat-seconds", type=float, required=True)
    p.add_argument("--poll-timeout-seconds", type=float, required=True)
    p.add_argument("--retry-delay", action="append", type=float, required=True)
    a = p.parse_args()
    permit = read_permit(a.state_directory / "launch-permit.json")
    observed_clock_domain = observe_clock_domain()
    if observed_clock_domain != permit.clock_domain:
        raise WatchdogError("clock domain changed; stored monotonic deadlines are invalid")
    source_root = a.adapter_source.resolve(strict=True).parents[1]
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    provider = load_provider_factory(a.adapter, a.adapter_source, permit.adapter_sha256)
    try:
        run_guard(role=a.role, permit_path=a.state_directory / "launch-permit.json",
                  authority_path=a.state_directory / "authority.json",
                  binding_path=a.guard_directory / "worker-binding.json",
                  entrypoint_path=Path(__file__), library_path=Path(watchdog.__file__), adapter_source=a.adapter_source,
                  provider=provider, heartbeat_seconds=a.heartbeat_seconds,
                  poll_timeout_seconds=a.poll_timeout_seconds,
                  clock_domain=lambda: observed_clock_domain,
                  retry_delays=a.retry_delay)
    finally:
        close = getattr(provider, "close", None)
        if callable(close) and close() is not True:
            raise WatchdogError("cleanup provider transport broker was not reaped")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
