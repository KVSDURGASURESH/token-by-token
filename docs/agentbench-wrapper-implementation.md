# Local AgentBench wrapper implementation

**Status (2026-10-10): local synthetic loopback path implemented; real GPU
episodes remain unavailable.** The current implementation runs from a local
`agentbench-worker` executable selected by the user. There is no hosted API,
remote control plane, authentication service, or paid-run approval service.

## Current local path

```text
token-by-token episode 1 run-local --worker PATH --output NEW_FILE.tbt.json
  -> closed local capability and request schemas
  -> agentbench-worker binary
  -> AgentBench coordinator and worker process
  -> local 127.0.0.1 streaming mock server
  -> private temporary raw records
  -> positive-allowlist aggregate sanitizer
  -> synthetic_mock result JSON
```

The binary source is on `codex/local-agentbench-wrapper` in the private
AgentBench repository, based on upstream `6565b0a`. It accepts only the
`loopback-model` / `none` GPU / `single` load combination for Episode 01.
Its request schema rejects endpoints, profile paths, workloads, provider
credentials, engine flags, environment overrides, and unknown fields. The
binary starts its server on loopback only and removes temporary raw records
after producing the aggregate result. It has no provider adapter in this path.

The public CLI keeps the existing `capabilities --episode N` behavior:
real execution is unavailable and real model/GPU/load allowlists are empty.
`run-local` is an additional, explicitly synthetic diagnostic. It validates
the worker's closed capability and result documents and checks that the
written file matches the reported run ID. It passes a minimal environment
to the worker and does not use a shell. It bounds stdout and stderr while
reading them, terminates the worker process group on timeout or overflow,
and publishes the result file only after validating both copies.

## Build and trust boundary

The private source has `tools/build_local_worker.py` and
`tools/audit_local_worker.py`. The build uses PyInstaller 6.16.0 and the
AgentBench locked runtime; it writes a candidate binary and `SHA256SUMS` in
the ignored `dist/` directory. The archive audit requires the coordinator,
worker, local sanitizer and mock server modules, and rejects the broad
`agentbench.cli` command plus private repository resources and markers. The
audit requires an exact reviewed inventory of AgentBench modules in the
embedded Python archive. The worker clears proxy environment variables before
starting its loopback HTTP clients or subprocesses.

A PyInstaller executable can be inspected and extracted. Packaging does not
hide proprietary Python logic. Do not add private profiles, prompts, raw
evidence, credentials, account identifiers, or provider endpoints to modules
reachable by this binary. The current candidate is unsigned and unpublished;
users must verify a future approved release artifact before executing it.

## Verification and remaining work

On 2026-10-10, the following checks passed on macOS arm64:

| Check | Command and result |
|---|---|
| Public client tests | `PYTHONPATH=client/src .venv/bin/python -m pytest -q client/tests` — 64 passed |
| Private worker tests | `cd "$AGENTBENCH_ROOT" && PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider tests/test_local_worker.py tests/test_local_sanitizer.py tests/test_run_coordinator.py -q` — 21 passed |
| Public binary | `cd client && ../.venv/bin/python scripts/build_binary.py` — audit, offline self-test, and bundle verification passed; SHA-256 `80e4846cd52f481c31e02e6ce32841c2df2c376e8927b63d4830dbd9b0fa6edb` |
| Private binary | `.venv/bin/python tools/build_local_worker.py --output-dir /private/tmp/agentbench-locked-final-dist` — archive audit passed; SHA-256 `d0fc2175cfb6bb80f133246744092b804ba5d63ca2f90b5a46dbeae95701dd68` |
| Packaged pair | `client/dist/token-by-token episode 1 run-local --worker /private/tmp/agentbench-locked-final-dist/agentbench-worker --output /private/tmp/tbt-final-hardened-pair.tbt.json --format json` — exit 0, `synthetic_mock`, one valid request |

The local tests exercise a real coordinator, worker process, and HTTP stream
through the loopback server with no paid service. The public tests cover
result validation, output bounds, and rejection without publishing a file.

Before any real episode can run locally, approve a versioned protocol and
immutable aliases, define a safe local engine connection method, freeze the
workload and qualification gates, bound cost and cancellation behavior, and
add independently verifiable recorded evidence. A real episode result must
never be inferred from this synthetic diagnostic.

Development, staging, production, and published-release behavior remain
unverified. No paid GPU was started, and no artifact was published or pushed.

Episode 02 selection uses closed packaged schemas and a bounded worker invocation. The worker reports public source/material/adapter/check digests; paths, credentials, endpoints and recipes are excluded. An exact combination and fresh proof are required before the client writes a selection. Hashes identify proof bytes; independent review and the private operator's current authorization establish authority. No public client module imports AgentBench profiles or creates provider resources. Actual measured-worker capability remains unavailable until the private adapter and provider smoke checks are verified.
