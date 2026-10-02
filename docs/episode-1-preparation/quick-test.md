# Episode 1 Quick test

Quick test is a local interactive diagnostic for one OpenAI-compatible endpoint
or a two-lane race. Both lanes receive the same prompt and sampling settings.
The UI streams text and reports runner-observed time to first token (TTFT),
end-to-end time, output-token count, and generation speed.

It is deliberately **not benchmark evidence**. Use the pinned ShareGPT serving
workload and GSM8K quality guard in [benchmark-standard.md](benchmark-standard.md)
for comparable Episode 1 claims.

## Zero-GPU demo

From the repository root, use the combined launcher. On a fresh checkout it
installs the pinned dashboard dependencies and builds the UI before starting
the loopback bridge; later launches reuse the existing build:

```bash
scripts/quick-test demo
```

Open <http://127.0.0.1:8765/#quick-test>. Choose a single request or two-lane
comparison, then press **Start**. The two built-in profiles are deterministic
local streaming fixtures; they create no provider resource and need no secret.
**Stop** aborts the browser request and signals the runner cancellation event,
which prevents later repetition waves from being dispatched.

Leave that process running. In another terminal, the matching CLI uses the
same bridge and configuration schema:

```bash
scripts/quick-test request \
  --profile demo-fast --prompt 'Explain TTFT in one sentence.' \
  --output /tmp/quick-test-result.json

scripts/quick-test compare \
  --profile demo-fast --profile demo-steady \
  --prompt 'Explain TTFT in one sentence.' --repetitions 3
```

Use **Save config** in the UI and replay it without translating fields:

```bash
scripts/quick-test compare \
  --config quick-test.json
```

## Live local endpoints

Keep endpoint URLs and API-key environment-variable names in a server-side
profile file. Never put a key value in the file or browser configuration:

```json
[
  {
    "id": "local-vllm",
    "label": "Local vLLM",
    "url": "http://127.0.0.1:8000/v1/chat/completions",
    "runtime_id": "vllm",
    "model": "served-model-name",
    "api_key_env": "LOCAL_LLM_API_KEY",
    "supported_optional_fields": ["seed", "stop"],
    "context_length": 32768
  }
]
```

Then start the bridge on loopback only:

```bash
LOCAL_LLM_API_KEY='set outside the browser' \
  scripts/quick-test serve \
  --profiles /private/path/quick-test-profiles.json
```

The bridge has no arbitrary proxy route. It accepts only configured profiles,
closed request fields, same-origin loopback browser calls, at most 20
repetitions, and at most four concurrent repetition waves.

## Measurement and privacy contract

- TTFT and end-to-end time come from the runner's monotonic clock.
- Generation speed is `(output tokens - 1) / (last content event - first
  content event)`. It is unavailable with fewer than two output tokens or a
  non-positive content span.
- Output-token count comes from the server's usage record. The UI does not
  estimate prompt tokens without a reviewed matching tokenizer.
- Default result files and **Export aggregate** omit prompts and response text.
  **Export private raw** is an explicit local action and includes them.
- Repetitions improve a quick diagnostic but do not turn it into the formal
  ShareGPT serving benchmark or GSM8K evaluation.

## Episode 1–16 console

The `#episode-runner` dashboard contains runnable endpoint rehearsal packs for
all 16 planned episodes. It exposes the same closed configuration through the
form, CLI flags, and JSON. `suite_repetitions` repeats the complete ordered pack
from the first cell to the last; `repetitions` controls requests inside each
cell.

```bash
scripts/quick-test episode \
  --episode 3 --profile vllm-runpod --profile sglang-runpod \
  --suite-repetitions 5 --repetitions 1 --batch-size 4 \
  --context-tokens 2048 --sequence-tokens 128 --timeout 120 \
  --output /tmp/episode-3-result.json

scripts/quick-test episode --config examples/episode-run.example.json
```

The UI reports TTFT, TPOT, end-to-end p95/p99, client inter-chunk p95, request
success, and runner throughput summaries. Client inter-chunk cadence is not
claimed as exact token ITL. GPU utilization and memory are shown only when the
bridge runs on the GPU host and the endpoint profile opts into
`local_nvidia_smi`; a remote OpenAI-compatible endpoint does not expose those
values. Runtime, GPU, cache/prefill/batching, and DP/TP/PP/EP fields describe an
already-running endpoint and are not mutations made by the test client.

## Local Docker deployment with VictoriaMetrics

Copy `examples/episode-run-profiles.example.json` to a private file, replace
the endpoint metadata, and export only the credential environment variables
named by that file. Then launch the local stack:

```bash
export EPISODE_PROFILES_FILE=/absolute/private/path/episode-profiles.json
export VLLM_API_KEY='set-in-this-shell-only'
export SGLANG_API_KEY='set-in-this-shell-only'
docker compose up --build -d
docker compose ps
```

- Console: <http://127.0.0.1:8765/#episode-runner>
- Health: <http://127.0.0.1:8765/healthz>
- Prometheus exposition: <http://127.0.0.1:8765/metrics>
- VictoriaMetrics VMUI: <http://127.0.0.1:8428/vmui/>

VictoriaMetrics scrapes every five seconds and retains data in the named
`victoria-metrics-data` volume for 30 days. The application has a Grafana-style
live summary; VMUI provides stored time-series queries. Stop the containers
without deleting history using `docker compose down`. To remove metrics too,
explicitly run `docker compose down -v`.

Rollback is `docker compose down`, followed by checkout of the prior commit and
`docker compose up --build -d`. No compose service creates, changes, or deletes
a RunPod resource.
