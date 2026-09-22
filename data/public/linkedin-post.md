I ran hands-on serving measurements for two runtime configurations: SGLang, vLLM.

Model: Qwen/Qwen2.5-32B-Instruct (bfloat16)
GPU: NVIDIA H100 80GB HBM3
Revision: 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd

Comparability note:
- vLLM: v0.29.0; FlashAttention-3; prefix caching and chunked prefill enabled.
- SGLang: v0.5.20; Triton attention and PyTorch sampling; prefix caching and chunked prefill enabled.
- Both runtimes used the same physical H100 offer, model revision, dtype, prompt construction, sampling, and client harness within each run.
- Baseline cells used 64 output tokens and three repetitions; stress cells used 128 output tokens and two repetitions.


The report retains attempted/success/failed counts and metric-specific sample counts. TTFT, TPOT, client inter-chunk latency, E2E latency, aggregate output rate, goodput, and failures are not treated as interchangeable samples.

- SGLang / 128tok-c16: TTFT p50/p95/p99 136.9/1424.1/1428.9 ms; n=64; TPOT p99 26.4 ms (n=64); 483.6 aggregate output tok/s; goodput unavailable (nonempty latency SLO contract required for goodput); 64 successful of 64 attempted; 8192 delivered output tokens, mean 128.00 per successful request.
- vLLM / 128tok-c16: TTFT p50/p95/p99 107.7/162.7/167.1 ms; n=64; TPOT p99 25.8 ms (n=64); 527.3 aggregate output tok/s; goodput unavailable (nonempty latency SLO contract required for goodput); 64 successful of 64 attempted; 8192 delivered output tokens, mean 128.00 per successful request.
- SGLang / 2048tok-c24: TTFT p50/p95/p99 10688.2/15314.6/15444.5 ms; n=96; TPOT p99 120.6 ms (n=96); 176.7 aggregate output tok/s; goodput unavailable (nonempty latency SLO contract required for goodput); 96 successful of 96 attempted; 12288 delivered output tokens, mean 128.00 per successful request.
- vLLM / 2048tok-c24: TTFT p50/p95/p99 6404.8/7638.2/7917.6 ms; n=96; TPOT p99 43.2 ms (n=96); 263.0 aggregate output tok/s; goodput unavailable (nonempty latency SLO contract required for goodput); 96 successful of 96 attempted; 12288 delivered output tokens, mean 128.00 per successful request.
- SGLang / 8192tok-c32: TTFT p50/p95/p99 88319.8/89338.9/89355.3 ms; n=128; TPOT p99 38.1 ms (n=128); 43.7 aggregate output tok/s; goodput unavailable (nonempty latency SLO contract required for goodput); 128 successful of 128 attempted; 16384 delivered output tokens, mean 128.00 per successful request.
- vLLM / 8192tok-c32: TTFT p50/p95/p99 47936.1/51888.5/53377.1 ms; n=128; TPOT p99 215.7 ms (n=128); 57.5 aggregate output tok/s; goodput unavailable (nonempty latency SLO contract required for goodput); 128 successful of 128 attempted; 12786 delivered output tokens, mean 99.89 per successful request.

These are observed results for this exact workload and hardware, not universal “ideal” numbers. The output-token setting is a maximum, not a guarantee of equal delivered work. p99 is descriptive and should always be read with its sample size, workload shape, cache state, and concurrency.

The useful reminder: throughput and tail latency can move in different directions. One average latency number is not enough for an inference SLO.

Preflight evidence:
- Every measured arm passed SSH, H100 identity, NVIDIA driver, runtime import, server readiness, and warmup gates.
- All 936 measured requests succeeded; every created pod was deleted and provider inventory was verified empty.


Exclusions:
- TGI and TensorRT-LLM were not measured in these runs because their validated deployment contracts were incompatible with the pinned image.
- eBPF tracing was unavailable because the container lacked CAP_BPF/CAP_PERFMON/CAP_SYS_ADMIN, tracefs, bpftrace, and bpftool.
- Goodput is unavailable because no latency SLO contract was declared before measurement.


Future work:
- Repeat saturation cells as independent experimental runs and predeclare a tail-precision target; report uncertainty instead of treating any fixed request count as proof that p99 is stable.
- Run a controlled open-loop arrival-rate sweep to estimate SLO-qualified capacity instead of closed-loop saturation alone.


#LLM #Inference #MLOps #GPU #PerformanceEngineering
