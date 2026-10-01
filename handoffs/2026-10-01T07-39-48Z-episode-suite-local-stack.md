---
handoff_version: 1
created_utc: 2026-10-01T07:39:48Z
topic: episode-suite-local-stack
repository: KVSDURGASURESH/token-by-token
branch: codex/episode-1-local-prep
baseline_commit: 4bcec7f363d2d363f2a2f85c908e4bc9c195d884
status: locally-deployed-ready-for-endpoint-configuration
---

# Episodes 1–16 local stack handoff

## Outcome

The dashboard and CLI can now run bounded endpoint-rehearsal packs for Episodes
1–16. The same configuration is accepted from the form, command-line flags, or
JSON. Whole-suite repetitions are bounded to 1–10. Results retain all rounds
and report TTFT, TPOT, end-to-end latency, inter-chunk latency, p95/p99 tails,
request counts, errors, and best-effort bridge-host GPU utilization/memory.

The production dashboard is containerized with the Python bridge. A local
VictoriaMetrics service scrapes `/metrics` every five seconds and retains data
for 30 days. Both ports bind only to `127.0.0.1`. The bridge runs as a non-root
user with a read-only filesystem, all Linux capabilities dropped, and
`no-new-privileges` enabled.

## Start tomorrow

```bash
git switch codex/episode-1-local-prep
git pull --ff-only
EPISODE_PROFILES_FILE=/absolute/path/to/private-profiles.json docker compose up --build -d
```

Put endpoint credentials in the environment variables referenced by the
private profile file; do not place secrets in JSON or commit them. Then open:

- Dashboard and episode runner: `http://127.0.0.1:8765/#episode-runner`
- VictoriaMetrics query UI/API: `http://127.0.0.1:8428/vmui/`

The checked-in profile file uses `.example.invalid` endpoints deliberately.
No real request succeeds until the receiving machine supplies private endpoint
profiles and the referenced API-key environment variables.

CLI equivalents:

```bash
scripts/quick-test episode --help
scripts/quick-test episode --config examples/episode-run.example.json
```

Stop the local stack without deleting metrics:

```bash
docker compose down
```

Delete the local metrics volume only when its retained data is no longer
needed:

```bash
docker compose down --volumes
```

## Configuration contract

Profiles declare engine (`vllm` or `sglang`), GPU type/count/nodes, model and
tokenizer revisions, context and sequence limits, prompt caching, chunked
prefill, continuous batching, quantization, speculative decoding, and
DP/TP/PP/EP topology. These declarations describe already-running endpoints;
the rehearsal bridge does not create pods or change runtime flags.

Per-run inputs include episode, selected profile IDs, context target, sequence
limit, batch/concurrency, requests per cell, whole-suite repetitions, and
timeout. Example schemas are in `examples/episode-run-profiles.example.json`
and `examples/episode-run.example.json`.

## Verification completed

- Full Python suite: `528 passed, 3 skipped in 79.36s`.
- Focused episode-suite tests: `8 passed`.
- Python compilation, JSON parsing, `git diff --check`, and
  `docker compose config --quiet`: passed.
- Docker frontend build: TypeScript project build and Vite production build
  passed; npm reported zero vulnerabilities.
- Local services: episode console healthy on `127.0.0.1:8765`; VictoriaMetrics
  running on `127.0.0.1:8428`.
- Scrape evidence: target `1/1 up`, zero scrape failures, and
  `inference_lab_up=1` stored in VictoriaMetrics.
- Production bundle includes the Episodes 01–16 runner, whole-suite repetition
  control, GPU panels, and operations overview.

Browser automation was unavailable in this workspace, so visual interaction
was not automated. The production bundle, HTTP APIs, health endpoint, metrics
endpoint, and metrics ingestion were verified directly.

## Ownership and review budget

- Architecture planning was previously bounded to Astra ultra and ended at the
  handoff.
- Implementation policy and ownership: primary Codex implementation under the
  repository-required `gpt-5.6-sol`, medium-reasoning profile. No claim is made
  that the desktop task itself changed models without tool confirmation.
- Scope: endpoint-only rehearsal runner, CLI/JSON parity, metrics, local
  container stack, dashboard, tests, and operating handoff.
- Acceptance criteria: all 16 rehearsal packs selectable; required knobs and
  repeat count represented; measured latency aggregates exposed; local stack
  healthy; VictoriaMetrics ingestion proven; no paid-resource mutation.
- Review rounds: one consolidated implementation/verification round of the
  maximum three; two remain. No unresolved correctness blocker is known.

## Safety and evidence boundary

No RunPod pod, endpoint, volume, model download, paid session, provider
mutation, or canonical benchmark was created or run. These packs are labelled
endpoint rehearsals and do not replace each episode's pinned benchmark,
quality gate, runtime telemetry, randomization, or provider-side cleanup
evidence. GPU telemetry is available only when `nvidia-smi` is visible to the
bridge host; endpoint APIs alone cannot provide it.
