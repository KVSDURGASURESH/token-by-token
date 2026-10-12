# Live Runpod inference-runtime study

Date: 2026-09-19
Classification: exploratory, noncanonical learning lab

## Outcome

This study measures one current vLLM configuration and one explicitly labelled
SGLang CUDA-12.8 compatibility configuration on the same GPU, model revision,
precision, prompt construction, output cap, concurrency matrix, and client.
TGI, TensorRT-LLM, a raw Transformers loop, and Ollama are recorded as preflight
decisions rather than presented as unmeasured benchmark rows.

The purpose is to learn how serving metrics move with prompt length and
concurrency. It is not a universal runtime ranking.

## Frozen workload

- GPU: one NVIDIA RTX PRO 6000 Blackwell Server Edition, 96 GB VRAM
- Model: `Qwen/Qwen2.5-32B-Instruct`
- Immutable revision: `5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd`
- Weights: BF16; default KV-cache dtype
- Context limit: 8,192 tokens
- Prompt targets: 128, 1,024, and 4,096 chat-template tokens
- Concurrency: 1 and 8 at every prompt length
- Output cap: exactly 64 tokens for every successful measured request
- Sampling: temperature 0, top-p 1, seed 17
- Load: closed-loop; 100 requests per cell; loopback HTTP streaming
- Cache boundary: every prompt carries a unique leading request ID so prefix or
  radix caching cannot turn the baseline into a repeated-prefix benchmark

All reported p99 values are descriptive. With 100 requests per cell, the p99 is
near the single slowest observation and is not a production-capacity claim.

## Metric meanings

- **TTFT:** client socket send to the first non-empty streamed content event.
- **TPOT:** `(E2E - TTFT) / (output tokens - 1)` for each successful request.
- **ITL:** time between consecutive non-empty streamed content events. This is a
  client inter-event metric; a runtime may emit chunks containing more than one
  token.
- **E2E:** client socket send through terminal `[DONE]` handling.
- **Output throughput:** successful output tokens divided by measured cell wall
  time. It is aggregate cell throughput, not per-request decode speed.

## Reference objectives, not universal ideals

An “ideal p99” exists only after the product declares its workload and SLO. For
this learning lab, the following are useful review lines, not industry claims:

| Signal | Learning objective | Why |
|---|---:|---|
| Short-prompt TTFT p99 | under 1,000 ms | interactive first-token response |
| TPOT p99 | at or below 50 ms/token | at least 20 output tokens/s per request |
| ITL p99 | under 100 ms, with no large stalls | smooth streaming cadence |
| Error rate | 0% in the bounded matrix | latency is irrelevant if work fails |
| Long-prompt/concurrent TTFT | find and explain the knee | prefill cost and queueing are workload-dependent |

E2E is evaluated against the declared 64-token output cap. A different output
length changes E2E even if TTFT and TPOT remain identical.

## Measured results

| Runtime | Profile | TTFT p50 / p95 / p99 (ms) | TPOT p99 (ms/tok) | ITL p99 (ms) | E2E p99 (ms) | Output tok/s | Success |
|---|---:|---:|---:|---:|---:|---:|---:|
| SGLang | 128tok-c1 | 85.9 / 87.3 / 88.5 | 46.3 | 46.9 | 3006.7 | 21.2 | 100/100 |
| vLLM | 128tok-c1 | 60.9 / 74.5 / 79.7 | 47.1 | 47.4 | 3042.9 | 21.0 | 100/100 |
| SGLang | 128tok-c8 | 183.2 / 985.2 / 1040.5 | 47.7 | 98.3 | 3916.6 | 145.8 | 100/100 |
| vLLM | 128tok-c8 | 161.4 / 192.4 / 222.5 | 47.0 | 54.1 | 3107.8 | 153.9 | 100/100 |
| SGLang | 1024tok-c1 | 213.7 / 214.6 / 214.9 | 46.9 | 47.5 | 3166.5 | 20.1 | 100/100 |
| vLLM | 1024tok-c1 | 187.5 / 197.6 / 200.6 | 47.0 | 47.6 | 3161.4 | 20.1 | 100/100 |
| SGLang | 1024tok-c8 | 1281.5 / 1347.0 / 1355.2 | 66.1 | 225.9 | 4443.0 | 109.3 | 100/100 |
| vLLM | 1024tok-c8 | 1233.4 / 1343.5 / 1351.8 | 64.2 | 48.5 | 4345.6 | 114.4 | 100/100 |
| SGLang | 4096tok-c1 | 760.3 / 768.1 / 769.1 | 48.7 | 49.5 | 3835.7 | 16.6 | 100/100 |
| vLLM | 4096tok-c1 | 730.6 / 740.2 / 743.8 | 47.6 | 48.1 | 3741.1 | 17.0 | 100/100 |
| SGLang | 4096tok-c8 | 3633.3 / 5823.7 / 5881.7 | 133.1 | 751.3 | 9202.9 | 54.8 | 100/100 |
| vLLM | 4096tok-c8 | 2875.3 / 4366.1 / 5050.2 | 128.3 | 1450.1 | 10328.7 | 56.6 | 100/100 |

Across both runtimes, all 1,200 measured requests succeeded. vLLM had the
lower TTFT p99 and higher throughput in five of six matched workload cells.
The 4,096-token/concurrency-8 cell exposed the important tail trade-off:
SGLang's compatibility configuration had the lower E2E and ITL p99, while vLLM
retained slightly higher throughput and lower TTFT p99. This is evidence for a
targeted scheduler/prefill follow-up, not a general runtime winner.

The historical rendered charts are excluded from this sanitized package. They
can be regenerated from `live-study.json` after its evidence envelopes pass the
current publication validator.

## GPU telemetry

| Runtime | Samples | GPU util mean / p95 (%) | VRAM mean / max (MiB) | Power mean / p95 / max (W) | Temp mean / max (C) |
|---|---:|---:|---:|---:|---:|
| vLLM | 1,222 | 97.8 / 100.0 | 86,632 / 87,322 | 404.4 / 590.1 / 617.3 | 51.3 / 65 |
| SGLang | 1,177 | 98.6 / 100.0 | 90,930 / 91,525 | 407.3 / 595.4 / 614.2 | 51.8 / 66 |

These are approximately one-second `nvidia-smi` samples clipped to each
measurement window. They show both arms were compute-saturated and that the
SGLang compatibility configuration reserved about 4.3 GiB more VRAM on average.

## Runtime comparability boundary

- **vLLM 0.29.0:** measured with FlashAttention. FlashInfer sampling was
  disabled because the CUDA 12.8 image could not identify SM 12.x correctly.
- **SGLang 0.5.20:** its default Blackwell path stopped before measurement
  because DeepGEMM required NVCC 12.9+. The measured arm disables JIT DeepGEMM
  and uses Triton attention, PyTorch sampling, and Torch BF16 GEMM. It is a
  compatibility result, not an optimal SGLang score.
- **TGI:** excluded after preflight. The upstream repository is archived and in
  maintenance mode, and its maintainers recommend vLLM or SGLang going forward.
- **TensorRT-LLM:** excluded after preflight. The current pip installation path
  requires CUDA Toolkit 13.2 and a CUDA-13-aligned PyTorch build; this pod is
  CUDA 12.8 and does not provide nested Docker.
- **Raw Transformers:** excluded by design because a model loop is not an
  equivalent concurrent OpenAI-compatible serving scheduler.
- **Ollama:** deferred. Its packaging and common quantized formats would add a
  model-format variable to a same-weight BF16 runtime study.

The exact machine-readable status is in
`runtime-attempts.json`.

## What to optimize for each signal

| Metric symptom | First mechanisms to isolate | Required validation |
|---|---|---|
| TTFT rises with prompt length | chunked prefill, prefill scheduling, faster attention kernels, prompt shortening | compare equal prompt tokens and inspect queue/prefill telemetry |
| TTFT rises with concurrency | admission control, continuous-batching limits, scheduler queueing | open-loop arrival-rate sweep and queue-age p99 |
| TPOT is high | speculative decoding, weight quantization, kernel/backend choice, tensor parallelism | hold acceptance rate, quality, and batch shape constant |
| ITL has rare large stalls | prefill/decode interference, preemption, scheduler policy, chunk size | correlate request timestamps with running/waiting/preemption metrics |
| E2E is high but TTFT is fine | decode path and output length | normalize by output tokens and inspect TPOT/ITL |
| VRAM or KV pressure is high | KV-cache dtype, weight quantization, cache block sizing, tensor parallelism | track cache occupancy, preemptions, failures, and quality |
| Repeated-prefix traffic is slow | automatic prefix/prompt caching | run a separate controlled repeated-prefix experiment |
| Throughput is low at safe latency | continuous batching and concurrency tuning | find the highest goodput below the p99 SLO knee |

gRPC can reduce client/transport overhead in a distributed deployment, but it
does not make GPU prefill begin earlier when the scheduler, queue, or model
compute is the bottleneck. This loopback HTTP test intentionally minimizes the
network variable; a later remote-client test should measure transport separately.

## Prefill and decode visibility

Client metrics infer the phase boundary: TTFT is dominated by queueing plus
prefill, while TPOT/ITL describe decode delivery. Runtime-native Prometheus
histograms and counters are preserved where exposed, but client values are not
renamed as server prefill/decode time. Future runs should capture an explicit
measurement-window Prometheus delta for server queue, prefill, decode,
preemption, prefix-cache, and KV-cache series.

## Troubleshooting lessons

The full incident journal is `journal.md`. The most
reusable fixes were:

1. Treat catalog stock as a hint, not a reservation.
2. Use independent local and in-pod deletion guards for paid resources.
3. Pin one source root after transfer; do not reconstruct remote paths from the
   local repository layout.
4. Keep each runtime in an isolated environment and share only the immutable
   model cache.
5. Match Blackwell to CUDA 12.9+ before rental; current default SGLang and
   FlashInfer paths need a newer toolchain than this image supplied.
6. Preflight Ninja and venv `PATH` before SGLang CUDA-graph warm-up.
7. Force Hugging Face offline mode after the exact model/tokenizer revision is
   cached so metadata requests do not add startup variability.
8. Never import a heavy runtime package during a measured cell just to print a
   version; use distribution metadata before the run.

## Cost and limitations

- Runpod rate: **$2.09/GPU-hour** for the Secure Cloud pod.
- Total session charge: **$4.1280**. Starting and final account balances are
  retained only in private teardown evidence.
- vLLM's 1,208.942-second measurement window cost approximately **$0.7019**;
  SGLang's 1,223.389-second window cost approximately **$0.7102**.
- Each runtime emitted 38,400 measured output tokens, or approximately **$18.28**
  and **$18.50 per million measured output tokens**, respectively. These figures
  exclude input-token accounting and should not be compared directly with hosted
  API pricing.
- The remaining **$2.7159** covered provisioning, immutable-model download,
  environment setup, server startup/warm-up, compatibility troubleshooting,
  preflights, evidence copy-back, and cleanup.
- The pod was permanently deleted after evidence verification; a subsequent
  all-pods listing was empty and a direct lookup returned `not_found`.

- One GPU and one model were tested.
- Each cell has one repetition and 100 requests; production p99 work needs more
  observations and repeated randomized runs.
- The client is on the same pod, so public-network and gateway latency are not
  represented.
- Closed-loop concurrency does not reveal the full saturation curve; an
  open-loop offered-load sweep is the correct next capacity experiment.
- vLLM's final 4,096-token concurrency-1 segment overlapped a CPU-side version
  probe for about 13 requests. GPU utilization remained saturated, but the cell
  carries that disclosure.
- SGLang is a compatibility fallback, so differences cannot be attributed to
  engine architecture alone.
- The earlier RTX PRO 4500 SE pod is not plotted. Runpod's displayed `94 GB
  Memory` value was host RAM, not GPU VRAM, and no equivalent validated matrix
  was retained from that setup. Its troubleshooting lessons are preserved in
  the journal without manufacturing a quantitative comparison.

## Next experiments viewers can watch for

1. vLLM continuous-batching and `max-num-batched-tokens` sweep at a fixed p99 SLO.
2. Chunked-prefill tuning for 4,096-token prompts, with ITL-stall correlation.
3. Automatic prefix caching with controlled shared-prefix percentages.
4. Speculative decoding with acceptance rate, quality, TPOT, and GPU power.
5. BF16 versus weight quantization and KV-cache quantization, including quality
   and maximum safe concurrency.
6. Tensor, pipeline, and data-parallel strategies on a multi-GPU pod, evaluated
   against interconnect topology rather than GPU count alone.
7. A current CUDA 13 image rerun of default SGLang and TensorRT-LLM.

## Primary references

External links from the historical report are intentionally excluded from this
sanitized package rather than retained as broken or stale links.
