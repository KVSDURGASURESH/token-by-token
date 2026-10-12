# Episodes 1–16 mock and dark-dashboard validation handoff

## Ownership and bounds

- Implementation owner: Codex `gpt-5.6-sol`, medium reasoning
- Branch: `codex/episode-1-local-prep`
- Baseline commit: `4548317`
- Review: round 2 closed clean; maximum remains 3 rounds
- Scope: local synthetic episode execution, truthful dashboard metrics, dark surfaces, browser acceptance, and labeled VictoriaMetrics ingestion
- Safety: no provider API, paid resource, real vLLM/SGLang installation, or GPU was used

## Completed state

All 16 episode packs ran locally with five suite repetitions and both built-in demo profiles. The result was 230 attempted, 230 successful, and zero failed requests across 115 cell-round results. GPU telemetry remained unavailable. The demo profiles' `vllm` and `sglang` runtime identifiers are synthetic labels only.

The dashboard now renders measured min–max ranges across every profile and suite round for TTFT p95, TPOT p95, E2E p99, and client inter-chunk p95. Decorative `LIVE` bars and first-lane-only values were removed. The episode index, runner, and planner surfaces have dark-theme coverage.

Python Playwright passed all 16 episode selections, 20 configured cells, the Episode 16 UI run at 20/20 requests, four measured latency panels, unavailable GPU panels, dark desktop/mobile rendering, and mobile overflow. Targeted pytest passed 13 tests. VictoriaMetrics contains 16 episode series and 128 latency series, all isolated by `validation_source="synthetic-mock"` and separate `inference_lab_mock_*` names.

The full sanitized report, commands, queries, and screenshots are in [the validation index](../docs/validation/mock-2026-10-01/README.md).

## Running services

- Main rebuilt dashboard: `http://127.0.0.1:8765/` (healthy; original profiles mount preserved)
- Synthetic preview: `http://127.0.0.1:8877/#episode-runner`
- VictoriaMetrics: `http://127.0.0.1:8428/`

These are local process states and must not be assumed to survive a machine restart.

## Known limitation

The completed-request and error-rate panels show a `NO DATA` badge even when their numeric values are populated, because the badge currently derives from the presence of latency samples. This is nonblocking and is recorded rather than opening another review cycle.

## Exact next-machine commands

From the repository root:

```bash
docker build -t inference-lab-episode-console:local .
docker run --rm --name inference-lab-mock-preview \
  -p 127.0.0.1:8877:8765 inference-lab-episode-console:local \
  demo --host 0.0.0.0 --port 8765 --dashboard-dir /app/dashboard/dist
```

In another terminal, install Playwright in an isolated environment if necessary, then run:

```bash
python3 -m venv /private/tmp/episode-playwright-venv
/private/tmp/episode-playwright-venv/bin/pip install playwright
/private/tmp/episode-playwright-venv/bin/python \
  tests/dashboard_episode_mock_acceptance.py \
  http://127.0.0.1:8877 docs/validation/mock-2026-10-01

PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_episode_suite.py tests/test_playground.py tests/test_publication_privacy.py
```

To restore the main local stack with the same checked-in profile mount:

```bash
EPISODE_PROFILES_FILE="$PWD/examples/episode-run-profiles.example.json" \
  docker compose up -d --no-deps episode-console
curl -fsS http://127.0.0.1:8765/healthz
```

Do not interpret the synthetic evidence as canonical benchmark data. Raw JSON remains in ignored `private/` storage and must not be committed.
