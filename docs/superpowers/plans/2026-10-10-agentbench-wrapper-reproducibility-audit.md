# AgentBench wrapper reproducibility audit and implementation plan

**Date:** 2026-10-10  
**Public repository reviewed:** `token-by-token` at `02dc9f2` / `origin/main`  
**Private repository reviewed:** AgentBench at `7020f85` / `origin/main`  
**Scope:** read-only review of AgentBench; no provider action, benchmark traffic,
deployment, release, commit, or push is authorized by this plan.

## Finding

An external user cannot currently run Episode 00, Episode 01, or a future episode
through the real AgentBench harness from the Token by Token client.

What works today is intentionally narrower:

- `token-by-token episodes` and `episode N describe` expose the public 00–16 catalog;
- `doctor --offline` and `episode N selftest --offline` exercise deterministic local
  client and evidence-bundle plumbing only;
- `evidence verify` validates the current synthetic bundle format;
- the website reads publication-reviewed static Episode 00 and 01 aggregates.

AgentBench itself is a private Python package whose `agentbench` console script exposes
the broad operator command `agentbench bench`. That command accepts private combo and
workload paths plus low-level execution controls. There is no `agentbench-worker`
executable, closed request schema, signed capabilities document, public sanitizer, or
authenticated plan/run service. Copying AgentBench into this repository, publishing its
wheel, or shelling out from the public CLI to `agentbench bench` would expose internal
profiles and controls and contradict the approved privacy boundary.

## Decision: one canonical architecture

The hosted-worker boundary in
`2026-10-08-real-agentbench-wrapper-and-shared-campaign-design.md` is canonical. The
direct local preset proposal in `2026-10-09-agentbench-episode-presets-plan.md` may be
used by trusted operators, but it must not become the public end-user integration. A
signed executable or OCI image improves reproducibility; it does not make Python source,
bytecode, profiles, or observed requests secret on a customer's machine.

Public flow:

```text
token-by-token CLI
  -> authenticated plan API
  -> signed allowlisted capabilities and immutable quote
  -> explicit approval of the current plan
  -> private agentbench-worker on controlled infrastructure
  -> AgentBench orchestration
  -> private raw evidence
  -> positive-allowlist sanitizer and signed .tbt.zip
  -> public verifier and dashboard replay
```

Until that boundary exists, `token-by-token capabilities --episode N` must return
`execution_status: unavailable` with empty model/GPU/load allowlists. It must not infer
capabilities from local files, environment variables, or an installed `agentbench`
command.

## Required changes in private AgentBench

Implement these behind the private repository boundary:

1. Add a separate `agentbench-worker` entry point with only:
   `capabilities --json`, `validate --request -`, and
   `execute --request - --events-jsonl`.
2. Define versioned, `extra=forbid` request/event/result schemas. Public input contains
   opaque episode, model, GPU, load-profile, and engine aliases only. It never contains
   paths, URLs, provider identifiers, credentials, shell strings, environment overrides,
   engine arguments, corpus names, prompt content, or skip-gate flags.
3. Extract the orchestration used by `agentbench bench` into a callable service layer;
   do not invoke the Typer command through a shell. Resolve aliases to private immutable
   combo/workload/profile revisions inside the worker.
4. Add dry validation that performs no provider call and writes no run directory. Add a
   loopback test proving the real coordinator/worker/HTTP streaming path is exercised.
5. Emit structured progress events with a strict allowlist. Test every error/event field
   with canary secrets and private paths so leakage fails CI.
6. Preserve raw records, prompts, outputs, telemetry, billing receipts, configs, and
   provider resource identifiers privately. Produce public evidence only through a
   positive-allowlist sanitizer with provenance, qualification state, cost state, and
   signatures.
7. Build a pinned worker OCI image first. If a standalone binary is also required, build
   it as a private operator artifact with SBOM, signature, platform matrix, and extraction
   audit; do not describe it as protection against recipient inspection.

## Required service work

1. Authenticated capabilities endpoint returning a signed, expiring allowlist.
2. `plan` endpoint resolving aliases to an immutable private plan and maximum cost quote.
3. Explicit approval tied to the exact plan digest; material changes invalidate approval.
4. Idempotent submit/status/stop/collect operations with tenant isolation, deadlines,
   cancellation, partial-evidence preservation, and continuing-billing warnings.
5. Server-side provider credentials and resource lifecycle controls. The public client
   must never accept provider tokens or arbitrary endpoints.

## Episode readiness

| Episode | What can be reproduced now | Real wrapper readiness |
| --- | --- | --- |
| 00 | Published historical aggregates; synthetic client diagnostic | Requires an immutable private protocol mapping. Historical evidence must not be rewritten as a new run. |
| 01 | Published historical H200 comparison; synthetic client diagnostic | AgentBench can perform the underlying private sweep, but a closed worker mapping, service-attested baseline protocol, qualification gate, sanitizer, and cost reconciliation are missing. |
| 02–16 | Public descriptions and synthetic diagnostics | Not runnable as public studies. Each needs an approved protocol, private workload/profile mapping, validation gates, sanitizer projection, and capability entry. Episodes 11–13 are companion studies and cannot be assumed to fit the inference harness. |

The repository currently contains two curriculum proposals: the implemented 00–16
catalog and an unimplemented 00–13 consolidation in the wrapper design. Do not ship
signed manifests or run aliases until one versioned catalog and historical alias policy
is approved. The public CLI remains on the implemented 00–16 catalog meanwhile.

## Ordered delivery and exit gates

1. **Contract fixture:** publish schema-only examples containing no private values.
   Exit: public and private validators accept the same safe fixture and reject unknown
   fields, paths, URLs, commands, and environment overrides.
2. **Private worker:** implement the three-command worker and loopback adapter.
   Exit: a fixture request traverses actual AgentBench orchestration against a local fake
   endpoint, with zero provider calls.
3. **Sanitization:** implement signed evidence v2 and hostile archive/leakage tests.
   Exit: private canaries never occur in the public bundle or dashboard projection.
4. **Development service:** connect auth, capabilities, plans, approvals, progress,
   cancellation, collection, and tenant isolation on controlled infrastructure.
   Exit: tampered/expired/duplicate/cross-user cases fail closed.
5. **Episode mappings:** start with 00 and 01; add future episodes only when their protocol
   and evidence gates are approved. Exit: each capability points to immutable private
   revisions and a tested public projection.
6. **Paid execution:** compile an exact provider/model/GPU/cost/cleanup plan and stop for
   explicit owner approval. A local or loopback pass does not authorize H200 spend.
7. **Release:** complete signing, SBOM, licensing, support, retention, staging, production,
   and documentation gates. Local builds alone are not release evidence.

## End-user commands after the missing service exists

```bash
token-by-token capabilities --episode 1
token-by-token episode 1 plan \
  --model <allowlisted-alias> \
  --gpu <allowlisted-alias> \
  --load-profile <allowlisted-alias> \
  --max-quote-usd <budget>
token-by-token episode 1 run --plan <signed-plan>
token-by-token runs status <run-id>
token-by-token runs collect <run-id> --output episode-01.tbt.zip
token-by-token evidence verify episode-01.tbt.zip
```

These commands are a target contract, not a claim of current availability.

## Local verification performed

Using Homebrew Python 3.12.13 on macOS arm64:

- `PYTHONPATH=client/src .../python -m unittest discover -s client/tests -p
  'test_*.py' -v` — **60 tests passed**;
- `(cd client && /opt/homebrew/bin/python3.12 scripts/build_binary.py)` — **passed**
  with the locked requirements, module/resource privacy audit, standalone smoke test,
  and bundle verification;
- standalone `token-by-token capabilities --episode 1 --format json` — **passed**
  and reported real execution unavailable with empty allowlists;
- standalone `token-by-token doctor --offline --format json` — **passed** and
  reported `synthetic_mock` / `client_installation_diagnostic_only`;
- `(cd client/dist && shasum -a 256 -c SHA256SUMS)` — **passed**.

The generated macOS candidate is an ignored local artifact, not a signed or published
release. No AgentBench benchmark was run. A direct `python -m agentbench --help` from a
plain interpreter could not start because its locked environment had not been installed;
more importantly, static package inspection confirms the only installed script is the
broad `agentbench` CLI and no constrained `agentbench-worker` entry point exists.
