# Episode 1 runtime source preflight

Evidence class: public source and registry metadata inspection on 2026-09-22. No image layers, model weights, GPU execution or paid resource were used for this inspection. These findings narrow the candidate; they do not establish runtime compatibility or authorize execution. The [implementation brief](implementation-brief.md) remains planning-only.

## Versions and immutable image references

The source pins are vLLM `v0.29.0` at `98dff2a81d747d1dba01a47f939f48c3526d4206` and SGLang `v0.5.20` at dereferenced commit `94602c9c2b7cbdb8efd5c52802dac6a1c180089e`. Sources: [vLLM release](https://github.com/vllm-project/vllm/releases/tag/v0.29.0), [SGLang release](https://github.com/sgl-project/sglang/releases/tag/v0.5.20).

Public registry manifest metadata observed beginning `2026-09-22T11:07:05Z`:

| Official image tag | OCI index digest | Linux amd64 image manifest digest |
|---|---|---|
| `vllm/vllm-openai:v0.29.0` | `sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1` | `sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b` |
| `vllm/vllm-openai:v0.29.0-cu129` | `sha256:7ef5a35d1ef8ce2cf9d671dd91eec6e367c5849262e0362b4d3d4a26be0d87d2` | `sha256:3e10e8189823e0f7ae4620c271bcdaaf64127ec7d0edc351591a508498b7684a` |
| `lmsysorg/sglang:v0.5.20-runtime` | `sha256:00b02004501e402332827ffd5343a225a8960d99adc990b37d6f31085b8f6800` | `sha256:4bf342cb756a7105e6df9ae81abeb62e891ff70d34b83fdd7a891fa46a494eca` |
| `lmsysorg/sglang:v0.5.20` | `sha256:06e4f2ed21afde4ff513cda65070124e727ba23ccaeff7712b8c40e1097d611f` | `sha256:b27fce60bc5494c118c4910702812bcfa8cee67abcdd1ff8b0902f21647552f4` |

Pin the selected platform image and record the index separately. Refresh registry observations before approval; a tag is mutable. SGLang's tagged [installation guide](https://github.com/sgl-project/sglang/blob/v0.5.20/docs/docs/get-started/install.mdx) recommends its runtime variant for serving. These are upstream base images, not a built and verified dual-runtime operator environment. The common-allocation launcher remains a separate engineering requirement.

Reproduce the metadata-only lookup for each image reference; `inspect --raw` does not pull image layers. On macOS use `shasum -a 256` to hash the exact raw index bytes:

```bash
image_ref=docker.io/vllm/vllm-openai:v0.29.0
skopeo inspect --raw "docker://$image_ref" | shasum -a 256
skopeo inspect --raw "docker://$image_ref" |
  jq -r '.manifests[] | select(.platform.os=="linux" and .platform.architecture=="amd64") | .digest'
```

vLLM's default image uses CUDA 13 and its `-cu129` image is an alternative. SGLang 0.5.20 retired its CUDA 12 lane. The selected host's driver and the final environment must support both actual runtime builds. A digest does not prove driver compatibility, BF16 execution, model fit or kernel availability. Sources: the release pages above.

## Candidate launch and request controls

These are source-verified fragments for a future launcher. The launcher must additionally enforce the four-active-request limit, private tunnel, process ownership, timeout, fresh-process boundaries and verified teardown. Both fragments deliberately use loopback and the same port; the runtimes run sequentially.

```bash
vllm serve Qwen/Qwen2.5-32B-Instruct \
  --revision 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd \
  --tokenizer-revision 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd \
  --dtype bfloat16 --kv-cache-dtype bfloat16 \
  --gpu-memory-utilization 0.90 --generation-config vllm \
  --max-model-len 4096 --max-num-seqs 4 --no-enable-prefix-caching \
  --host 127.0.0.1 --port 8000

python3 -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-32B-Instruct \
  --revision 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd \
  --dtype bfloat16 --kv-cache-dtype bfloat16 \
  --mem-fraction-static 0.90 --sampling-defaults openai \
  --context-length 4096 --max-running-requests 4 \
  --disable-radix-cache --enable-metrics \
  --host 127.0.0.1 --port 8000
```

The exact vLLM prefix-off switch is `--no-enable-prefix-caching`. SGLang passes its model revision to tokenizer loading and uses `--disable-radix-cache`. Sources: [vLLM versioned CLI](https://docs.vllm.ai/en/v0.29.0/cli/serve/), SGLang [model arguments](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/arg_groups/fields/model.py), [cache arguments](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/arg_groups/fields/memory.py), [observability arguments](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/arg_groups/fields/observability.py).

The active-request controls are vLLM `--max-num-seqs 4` and SGLang `--max-running-requests 4`. Sources: [vLLM scheduler arguments](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/engine/arg_utils.py#L1595-L1602), [SGLang scheduler arguments](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/arg_groups/fields/schedule.py#L33-L41). For request-level top-k disabling, send `"top_k": 0` to vLLM and `"top_k": -1` to SGLang. Bind this dialect difference explicitly so model generation defaults cannot silently alter the comparison. Sources: [vLLM sampling parameters](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/sampling_params.py), [SGLang sampling parameters](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/sampling/sampling_params.py).

Both tagged chat request schemas accept `max_completion_tokens: 128` and the nonstandard extension `ignore_eos: true`. Fixed-output requests omit stop strings and stop-token overrides, disable sampling with the validated dialect, and require exactly 128 usage tokens plus `finish_reason: "length"`. A request flag alone cannot prevent aborts, errors, context overflow or a runtime ignoring it. Natural-stop quality requests omit `ignore_eos` and treat length truncation as a quality failure. Sources: [vLLM chat protocol](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/entrypoints/openai/chat_completion/protocol.py), [SGLang OpenAI protocol](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/entrypoints/openai/protocol.py).

The pinned Qwen generation configuration includes nonneutral sampling and repetition settings. vLLM `--generation-config vllm` and SGLang `--sampling-defaults openai` prevent model-default inheritance; still send explicit temperature 0, top-p 1, runtime-specific disabled top-k, repetition penalty 1, and the mode's output controls. Sources: [vLLM model configuration](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/config/model.py#L326-L337), [SGLang serving defaults](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/arg_groups/fields/serving.py#L223-L230), [pinned Qwen generation configuration](https://huggingface.co/Qwen/Qwen2.5-32B-Instruct/raw/5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd/generation_config.json).

The 4096-token limit includes input and output, leaving at most 3968 input tokens for a 128-token generation. Freeze the fully rendered chat-template token IDs for both 512- and 2048-token shapes. A whitespace filler test is not verification against the pinned tokenizer. The [tokenizer-only preflight](tokenizer-preflight.md) demonstrated both exact shapes using downloaded tokenizer assets only.

## KV memory arithmetic

The pinned [Qwen config](https://huggingface.co/Qwen/Qwen2.5-32B-Instruct/raw/5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd/config.json) declares 64 layers, hidden size 5120, 40 attention heads and 8 KV heads. Thus head dimension is 128. Derived raw BF16 KV storage is:

```text
64 layers × 8 KV heads × 128 dimensions × 2 (K and V) × 2 bytes
= 262,144 bytes/token = 256 KiB/token
```

A fully populated 4096-token sequence requires 1 GiB raw KV, and four such sequences require 4 GiB. The 128-token decode portion adds 32 MiB per sequence. This estimate excludes weights, allocator/page slack, graph capture, workspaces and runtime reservation. Record observed allocated KV capacity and actual device memory separately; model arithmetic is not a measured capacity result.

The proposed 0.90 flags do not reserve identical categories of memory. vLLM budgets its model executor, whereas SGLang budgets static weights plus KV pool, leaving activations and graph buffers outside that fraction. Sources: [vLLM cache configuration](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/config/cache.py#L111-L118), [SGLang memory semantics](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/arg_groups/memory_hook.py#L47-L69). A separate experiment rule is to abort if observed total device memory after load and graph capture reaches 95% of driver-reported capacity. Changing a memory fraction changes the plan and requires a new bound approval; no adaptive tuning during measured blocks.

## Native metrics and live verification

| Concept | vLLM 0.29.0 | SGLang 0.5.20 | Interpretation |
|---|---|---|---|
| Active / waiting requests | `vllm:num_requests_running`, `vllm:num_requests_waiting` | `sglang:num_running_reqs`, `sglang:num_queue_reqs` | Native gauges; preserve source semantics and time windows |
| KV occupancy | `vllm:kv_cache_usage_perc` | `sglang:full_token_usage` | Both fractions; SGLang excludes evictable blocks, so values are not equivalent |
| Queue time histogram | `vllm:request_queue_time_seconds` | `sglang:queue_time_seconds` | Counter/histogram deltas must share the measured cell boundaries |
| Prefill / decode | `vllm:request_prefill_time_seconds`, `vllm:request_decode_time_seconds` histograms | `sglang:realtime_tokens_total{mode="prefill_compute"\|"prefill_cache"\|"decode"}` counters | SGLang does not provide direct equivalents for the per-request phase-duration histograms |

Sources: [vLLM tagged metric implementation](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/v1/metrics/loggers.py), [vLLM metric documentation](https://docs.vllm.ai/en/v0.29.0/design/metrics/), [SGLang tagged metric implementation](https://github.com/sgl-project/sglang/blob/v0.5.20/python/sglang/srt/observability/metrics_collector.py). A missing native phase metric stays unavailable; client TTFT or token throughput must not be renamed as server prefill/decode duration.

SGLang's `sglang:prefill_effective_tokens_total` separates `input`, `device_hit`, `host_hit` and `storage_hit` and avoids recounting retracted requests. `sglang:prompt_tokens_total` and `sglang:generation_tokens_total` are counters with an `is_streaming` label. Record labels and scrape coverage before taking deltas. Its `sglang:token_usage` is a bottleneck across cache types; prefer `full_token_usage` for this full-attention Qwen candidate. Expected zero cache reuse with radix disabled still needs a live check. Source: the tagged SGLang metrics implementation above.

During a separately approved startup, verify one visible H100, driver/CUDA, exact packages and model revision, effective dtypes/flags, startup free memory, allocated KV capacity, loopback-only bindings, metrics availability and one exact 128-token probe. Verify that the previous runtime process and descendants have exited before starting the next block. Failure consumes the bounded startup allowance and triggers the declared abort/cleanup path; do not silently change model, image, precision or isolation design.
