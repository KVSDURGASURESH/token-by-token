# Live endpoint benchmark and teardown

This is the ordered procedure for an approved run. It has not been executed by
the packaged repository. Provider commands are operator-driven and may run only
after the exact current plan is approved.

## Gate 0 — local validation and private workspace

Run the offline checks in the README. Create a local private evidence directory
outside the repository with mode `0700`. Keep raw requests, responses, provider
IDs, balances, and logs there. Verify the selected image resolves to the OCI
digest in the plan. Verify current `runpodctl` help for create, get, list, and
delete. Recheck the offer, price, balance, auto-recharge state, and pre-run cost
capture described in [evidence capture](evidence-capture.md).

Prefer a provider-enforced, provider-readable `--terminate-after` deadline.
The installed CLI must expose the flag, and a provider-owned read after
creation must round-trip the deadline. Documentation or successful argument
parsing alone is insufficient proof. If that behavior cannot be proved,
local-only mode requires the separate exact
`ACCEPT LOCAL-WATCHDOG RISK` acknowledgement, an execution-ready plan binding
both watchdog script hashes, and two detached `caffeinate` watchdogs. That
acknowledgement grants no spend permission.

## Gate 1 — create after exact approval

After the digest-and-cap approval, create only the Pod bound by the plan. A
current CLI shape is:

```bash
runpodctl pod create \
  --name inference-lab-approved-arm \
  --image DERIVED_OPERATOR_IMAGE@sha256:APPROVED_DIGEST \
  --gpu-id APPROVED_GPU_OFFER \
  --gpu-count 1 \
  --data-center-ids APPROVED_DATACENTER \
  --cloud-type SECURE \
  --container-disk-in-gb APPROVED_GB \
  --ssh=true \
  --terminate-after APPROVED_DURATION \
  -o json
```

Add `--registry-auth-id APPROVED_REGISTRY_AUTH_ID` only when the approved image
requires it and current CLI help exposes the flag. The identifier belongs in
private evidence and the approved plan; it is not a registry password.

The derived images set `ENTRYPOINT []` and `CMD ["sleep", "infinity"]`, so no
Runpod Docker arguments are needed. Use the exact flags printed by current help;
if the installed CLI differs, revise and reapprove the plan rather than guessing.
Do not add a volume, exposed port, public IP, fallback GPU, or alternate location
unless approved. Write the Pod ID to a pre-created local regular file with mode
`0600`; do not print it.

For local-only guard mode, immediately run:

```bash
python3 scripts/arm_local_watchdogs.py \
  --plan PRIVATE_EXECUTION_PLAN.json \
  --resource-id-file PRIVATE_POD_ID_FILE \
  --evidence-dir PRIVATE_WATCHDOG_DIR
```

Continue only after both nonce-bound armed records show a successful provider
poll. The runner checks both fresh heartbeats and bound arm order before cells.

## Gate 2 — inspect and start the one bound runtime

Use `runpodctl pod get` to confirm image digest, GPU offer/count, location,
disk/volume settings, and termination deadline. Abort and delete on mismatch.
Confirm the approved datacenter and network/SSH settings too. Connect using the
CLI-provided SSH instructions and prove one small round-trip upload/download
before loading model weights; this validates that the derived image accepts the
provider's SSH injection and that later evidence export is possible. Abort and
delete if SSH, forwarding, or transfer is unavailable.

Inside the Pod, `cd /opt/inference-lab` and record sanitized hardware metadata.
For the recommended vLLM operator image, the intended server arguments are:

```bash
vllm serve Qwen/Qwen2.5-32B-Instruct \
  --revision 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd \
  --served-model-name Qwen/Qwen2.5-32B-Instruct \
  --dtype bfloat16 --max-model-len 16384 \
  --enable-prefix-caching --enable-chunked-prefill \
  --host 127.0.0.1 --port 8000
```

For SGLang, inspect every flag against the exact derived image help before
approval when a compatible local container runtime is available, and verify it
again on the approved Pod before loading the model. Radix prefix caching is
enabled by default; do not disable it. The positive chunk size enables and
records chunked prefill:

```bash
python3 -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-32B-Instruct \
  --revision 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd \
  --dtype bfloat16 --context-length 16384 \
  --chunked-prefill-size 8192 --enable-metrics \
  --host 127.0.0.1 --port 8000
```

The historical study proves only that prefix caching and chunked prefill were
on; its chunk size and full launch lines are unknown. Record new help output,
command, runtime version, dependencies, and digest. A changed flag changes the
plan.

Smoke-test loopback `/v1/models`, one streamed chat request, exact token
accounting, and `/metrics`. Measurement begins only after model identity and
the expected runtime metrics are present.

Keep the server and collectors inside the Pod. On the operator workstation,
open the provider-documented SSH connection with local forwarding from port
8000 to Pod loopback port 8000. The exact SSH host, user, key, and port come
from the current Pod connection panel and stay in private evidence. Verify from
the workstation that `http://127.0.0.1:8000/v1/models` reaches only the selected
Pod. This keeps the compiled plan and monotonic watchdog heartbeats on the same
operator host as the benchmark client.

## Gate 3 — telemetry and deterministic traffic

Start one-second collectors in separate Pod terminals. Each command is a
long-running foreground process; do not paste them sequentially into one shell.
For example, run this in terminal A:

```bash
python3 scripts/capture_gpu_telemetry.py \
  --output PRIVATE_DIR/gpu.csv --interval-seconds 1
```

Run this in terminal B, selecting the active runtime:

```bash
python3 scripts/collect_runtime_metrics.py \
  --runtime vllm --url http://127.0.0.1:8000/metrics \
  --output PRIVATE_DIR/vllm-metrics.jsonl --interval-seconds 1
```

Run the declared warmups, full matrix, and all three repetitions in one client
invocation on the operator workstation. Warmups use the first matrix cell,
`min(warmup count, first-cell concurrency)`, and that cell's wall deadline;
they are recorded separately and never enter measured cells. Any warmup failure
aborts before measurement. This single invocation claims and completes one
guarded runtime arm:

```bash
python3 scripts/run_live_openai_benchmark.py \
  --runtime vllm \
  --endpoint http://127.0.0.1:8000/v1/chat/completions \
  --model Qwen/Qwen2.5-32B-Instruct \
  --model-revision 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd \
  --matrix 128:1,128:32,2048:4,2048:32,8192:8,8192:32 \
  --cell-timeouts 128:1:180,128:32:180,2048:4:300,2048:32:600,8192:8:900,8192:32:1800 \
  --request-count 128 --warmup-requests 8 --repetitions 3 \
  --max-output-tokens 128 --seed 20260920 \
  --transformers-version 5.17.0 \
  --plan PRIVATE_EXECUTION_PLAN.json \
  --output PRIVATE_LOCAL_DIR/vllm-all-repetitions.json
```

The command above is the provider-enforced-deadline mode. In the separately
acknowledged local-only fallback, append `--guard-dir PRIVATE_WATCHDOG_DIR`.
The plan is required in both modes. Guard state and the runner must remain on
the same machine because heartbeat freshness uses that host's monotonic clock.

For an SGLang allocation, use its separately compiled one-runtime plan and
`--runtime sglang`. Record every startup, smoke, warmup, measurement, timeout,
exclusion, and failure attempt. Three repetitions within one allocation do not
create three independent GPU allocations and do not make the arms paired.

After each arm, interrupt each collector with `Ctrl-C` in its own terminal and
confirm both processes exited before summarizing GPU telemetry and normalizing
results:

```bash
python3 scripts/summarize_gpu_telemetry.py \
  --input PRIVATE_DIR/gpu.csv --output PRIVATE_DIR/gpu-summary.json
python3 scripts/summarize_runtime_metrics.py \
  --input PRIVATE_DIR/vllm-metrics.jsonl --runtime vllm \
  --output PRIVATE_DIR/vllm-metrics-summary.json
python3 scripts/normalize_live_benchmark_results.py \
  --artifact PRIVATE_LOCAL_DIR/vllm-all-repetitions.json \
  --gpu "APPROVED_H100_OFFER" --precision bfloat16 \
  --output PRIVATE_LOCAL_DIR/vllm-normalized.json
```

The runtime summary covers the selected full telemetry window; it does not
attribute samples to cells. Keep every normalized row's `cell_id` and
`repetition` identity. Any cross-repetition aggregation must be predeclared and
implemented separately.

To inspect `vllm-normalized.json`, start the dashboard as described in the
README, open `#local-results`, and choose **Open local results**. The same page
can open the matching runtime-summary JSON; it intentionally does not accept a
GPU summary. The browser-local reader preserves cell and repetition labels and
shows latency/throughput results without silently joining the historical
Episode 0 telemetry. Opening files is an inspection step; it does not make the
result publishable.

Only sanitized aggregates may enter a publication bundle. Preserve requested
and delivered output lengths and stop reasons so unequal work stays visible.
Treat native occupancy as runtime-specific supporting observation.

## Gate 4 — export evidence, then permanently clean up

Before deletion, copy `gpu.csv`, the runtime metrics JSONL, both summaries,
sanitized launch/help/hardware metadata, and server logs from the Pod to the
private operator evidence directory using the exact `scp`/SFTP command shown
by the current Runpod connection panel. Compare local byte counts or hashes,
open each copied file, and confirm collectors have stopped. Do not delete until
the required evidence is local. Do not copy model weights, caches, credentials,
provider configuration, raw secrets, or unrelated logs.

Delete in every terminal path, including startup or smoke failure:

```bash
runpodctl pod delete PRIVATE_POD_ID -o json
runpodctl pod list --all -o json
runpodctl pod get PRIVATE_POD_ID -o json
```

Completion requires delete acknowledgement, fresh inventory absence, direct
structured `not_found`, and a final balance/billing read. Stopping is not
cleanup. Delete and verify every separately created volume, endpoint, public IP,
or billed resource. Capture the post-run cost page with the exact date range,
reconcile estimated versus actual cost, and retain private deletion evidence.

Sanitize and verify the publication bundle offline. Publication is a separate
owner action and is never implied by run approval.
