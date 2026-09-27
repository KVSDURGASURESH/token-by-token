# Episode 1 Quick test

Quick test is a local interactive diagnostic for one OpenAI-compatible endpoint
or a two-lane race. Both lanes receive the same prompt and sampling settings.
The UI streams text and reports runner-observed time to first token (TTFT),
end-to-end time, output-token count, and generation speed.

It is deliberately **not benchmark evidence**. Use the pinned ShareGPT serving
workload and GSM8K quality guard in [benchmark-standard.md](benchmark-standard.md)
for comparable Episode 1 claims.

## Zero-GPU demo

From the repository root, build the dashboard and start its loopback bridge:

```bash
npm --prefix dashboard run build && PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py demo
```

Open <http://127.0.0.1:8765/#quick-test>. Choose a single request or two-lane
comparison, then press **Start**. The two built-in profiles are deterministic
local streaming fixtures; they create no provider resource and need no secret.
**Stop** aborts the browser request and signals the runner cancellation event,
which prevents later repetition waves from being dispatched.

The matching CLI uses the same bridge and configuration schema:

```bash
PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py request \
  --profile demo-fast --prompt 'Explain TTFT in one sentence.' \
  --output /tmp/quick-test-result.json

PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py compare \
  --profile demo-fast --profile demo-steady \
  --prompt 'Explain TTFT in one sentence.' --repetitions 3
```

Use **Save config** in the UI and replay it without translating fields:

```bash
PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py compare \
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
  PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py serve \
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
