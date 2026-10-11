#!/usr/bin/env python3
"""Cleanup-only Episode 1 restart worker; this entrypoint has no create operation."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import episode1_watchdog as watchdog
from episode1_watchdog import WatchdogError, load_provider_factory, observe_clock_domain, read_permit, restart_cleanup

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--state-directory", type=Path, required=True)
    p.add_argument("--plan-sha256", required=True)
    p.add_argument("--adapter", required=True)
    p.add_argument("--adapter-source", type=Path, required=True)
    p.add_argument("--retry-delay", action="append", type=float, required=True)
    a=p.parse_args()
    permit=read_permit(a.state_directory/"launch-permit.json")
    observed_clock_domain=observe_clock_domain()
    if observed_clock_domain != permit.clock_domain:
        raise WatchdogError("clock domain changed; original monotonic deadline cannot be extended")
    source_root=a.adapter_source.resolve(strict=True).parents[1]
    if str(source_root) not in sys.path:
        sys.path.insert(0,str(source_root))
    provider=load_provider_factory(a.adapter,a.adapter_source,permit.adapter_sha256)
    try:
        restart_cleanup(permit_path=a.state_directory/"launch-permit.json",
            authority_path=a.state_directory/"authority.json", provider=provider,
            current_plan_sha256=a.plan_sha256,
            clock_domain=lambda: observed_clock_domain,
            restart_entrypoint_path=Path(__file__), library_path=Path(watchdog.__file__),
            retry_delays=a.retry_delay)
    finally:
        close=getattr(provider,"close",None)
        if callable(close) and close() is not True:
            raise WatchdogError("cleanup provider transport broker was not reaped")
    return 0

if __name__ == "__main__": raise SystemExit(main())
