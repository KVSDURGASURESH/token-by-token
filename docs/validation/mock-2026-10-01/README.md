# Synthetic episode dashboard validation — 2026-10-01

This is local mock evidence, not a provider benchmark. No pod, endpoint, GPU, or paid resource was created. The `vllm` and `sglang` runtime identifiers are labels on the built-in `demo-fast` and `demo-steady` engines; they are not real vLLM or SGLang installations. GPU telemetry correctly remained unavailable.

## Results

- Episodes: 16/16
- Suite repetitions: 5 per episode
- Profiles: `demo-fast`, `demo-steady`
- Cell-round results: 115
- Requests: 230 attempted, 230 successful, 0 failed
- TTFT p95 observed range: 0.488–10.805 ms
- TPOT p95 observed range: 19.826–38.353 ms
- E2E p99 observed range: 456.946–891.121 ms
- Client inter-chunk p95 observed range: 22.489–42.039 ms
- GPU availability: false for every result

The dashboard now labels latency values as ranges across all measured profiles and suite rounds. Bars use measured samples only; there is no decorative `LIVE` state. One nonblocking display limitation remains: the completed-request and error-rate panels show `NO DATA` because their status badge is derived from latency samples even though their numeric values are populated.

## Browser evidence

Python Playwright checked all 16 episode selections and 20 configured cells, ran Episode 16 through the UI (20/20 requests), asserted four measured latency panels, asserted both GPU panels were unavailable, checked the dark desktop and mobile surfaces, and checked the 390 px episode index for horizontal overflow.

- [Desktop Episode 16 result](episode-16-complete-desktop.png)
- [Mobile episode index](episode-index-mobile.png)

Observed result:

```text
episodes=16 cells=20 requests=20/20 metric_panels=4 gpu_unavailable=2 theme=dark
```

Reproduce the browser check with one Docker demo process serving both the built dashboard and mock API, plus a Python environment containing Playwright:

```bash
docker build -t inference-lab-episode-console:local .
docker run --rm --name inference-lab-mock-preview \
  -p 127.0.0.1:8877:8765 inference-lab-episode-console:local \
  demo --host 0.0.0.0 --port 8765 --dashboard-dir /app/dashboard/dist
python tests/dashboard_episode_mock_acceptance.py http://127.0.0.1:8877 docs/validation/mock-2026-10-01
```

## Episode pack command

The following bounded command was run for each episode number 1 through 16 against the separate demo bridge that was started on port 8876:

```bash
PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py demo --port 8876 --host 127.0.0.1
PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py episode \
  --bridge http://127.0.0.1:8876 --episode "$episode" \
  --profile demo-fast --profile demo-steady \
  --suite-repetitions 5 --repetitions 1 --batch-size 2 \
  --context-tokens 2048 --sequence-tokens 128 --timeout 30 \
  --output "private/mock-validation-2026-10-01/episode-${episode}.json"
```

Raw result files remain under the ignored `private/` tree. Only this sanitized aggregate and screenshots are published.

## VictoriaMetrics evidence

Sanitized aggregates were imported at `http://127.0.0.1:8428/api/v1/import/prometheus` with the mandatory extra label `validation_source=synthetic-mock`. The synthetic metric names are separate from application metrics, so no unlabeled production-like series were modified.

Successful instant queries:

```promql
count(count by (episode) (inference_lab_mock_episode_requests_total{validation_source="synthetic-mock",status="successful"}))
# 16

sum(inference_lab_mock_episode_requests_total{validation_source="synthetic-mock",status="successful"})
# 230

count(inference_lab_mock_episode_metric_ms{validation_source="synthetic-mock"})
# 128 (16 episodes × 4 metrics × min/max)
```

The imported latency metrics are `ttft_p95`, `tpot_p95`, `e2e_p99`, and `client_inter_chunk_p95`, each with `minimum` and `maximum` statistics. `inference_lab_mock_gpu_available` is `0` for every episode.

## Proportional checks

```text
PYTHONPATH=src .venv/bin/pytest -q tests/test_episode_suite.py tests/test_playground.py tests/test_publication_privacy.py
13 passed in 4.57s

docker build -t inference-lab-episode-console:local .
dashboard TypeScript/Vite build passed (34 modules)
```

The rebuilt image is serving at `http://127.0.0.1:8765/` with the pre-existing profiles file mount preserved. A separate mock preview remains available at `http://127.0.0.1:8877/#episode-runner`.
