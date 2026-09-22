# Token by Token — Inference Lab roadmap

**Token by Token** is the working name for this learning series; **Inference Lab** is its tagline. Episode 0 is a completed exploratory warm-up with a local viewer and offline fixture workflow. Every later stage below is **planned**. This roadmap does not authorize GPU spending or claim that the integrations or experiments already exist.

This is the canonical sixteen-part map of future work. The main serving path is **measurement → equal-work baseline → single-GPU optimization → parallelism → routing and operations**. Sections 3–5 are companion studies to take alongside that path, not prerequisites for the next optimization experiment. The roadmap supports the [three capstone project families](capstone-projects.md); it does not create a fourth project.

## Evidence contract for every stage

Benchmarking and quality evaluation answer different questions and must travel together.

- **Benchmarking** measures resource use and service behavior: TTFT, TPOT, end-to-end latency, throughput, SLO-qualified goodput, memory, errors and cost under a declared workload.
- **Quality evaluation** measures whether an output or decision is useful and correct: task accuracy, semantic correctness, citation support, abstention, schema compliance and task-specific acceptance thresholds.

A faster configuration that fails the quality gate is not a winner. A quality comparison with uncontrolled prompts, decoding or workloads does not explain runtime behavior. Each measured lab therefore fixes the work contract, records both result classes and reports tradeoffs rather than collapsing them into one score.

For service experiments, preserve request and repetition IDs, input/output token counts, stop reasons, stream-event timestamps, warmup state, errors and request class. Record the exact model, tokenizer/template hashes, image digest, harness commit, runtime flags, hardware and pricing basis. Capture runtime queue, prefill, decode, KV-cache and scheduler counters when exposed, plus host, GPU and network telemetry at a documented sampling interval. Correlate request traces with OpenTelemetry, service metrics in Prometheus/Grafana and GPU counters from DCGM where supported. A missing metric stays unavailable with its reason.

Pooled percentiles, per-repetition percentiles and confidence intervals are different objects. Use uncertainty estimates appropriate to independent repetitions. Do not claim that a fixed sample count automatically makes p99 reliable, and never reconstruct request distributions from aggregate p50/p95/p99.

## The experiment map

### 1. Measurement and quality contracts

Choose a use case and declare its output contract, quality gate, latency SLO, memory ceiling and budget. Create deterministic natural-stop and fixed-output workload modes, raw-request export and a repetition policy. Keep schema validity separate from semantic correctness.

**Evidence:** versioned workload and quality sets, declared thresholds and denominators, exact provenance, raw per-request records and a report schema that can retain failed or inconclusive results.

### 2. Equal-work runtime baseline

Compare the same model, corpus, template, output contract and sampling settings across an HF/PyTorch control, vLLM and SGLang where compatible. Randomize or counterbalance execution order. Keep cold start separate from steady state, and compare output-length distributions before interpreting throughput.

**Evidence:** selected images and kernels, tokenizer/template hashes, per-repetition TTFT and end-to-end latency, output lengths, stop reasons, correctness checks, errors, device telemetry and attributable cost.

### 3. Model internals: weights to optimization

Use a small inspectable model to trace stored weights through embeddings, attention, the forward pass and logits. Then trace the backward pass through gradients, optimizer state and parameter updates. Connect these mechanisms to memory and compute costs without presenting the small-model exercise as a large-model benchmark.

**Evidence:** reproducible tensor-shape and parameter-count walkthroughs, attention inspection, gradient checks and optimizer-state accounting.

### 4. LoRA and QLoRA with held-out evaluation

Hold the dataset, prompt format, training budget and evaluation set fixed while comparing LoRA with QLoRA. In both cases the base weights remain frozen and low-rank adapters are trained; QLoRA quantizes the frozen base while gradients flow through it to the adapters. Record trainable parameters, base-weight precision, adapter configuration, peak memory, training time and checkpoint lineage. Evaluate both adapters on held-out task quality and serving behavior; successful training or lower loss alone does not establish improvement.

**Evidence:** deterministic lineage, learning curves, memory/time measurements, held-out quality results, uncertainty across repetitions where practical and inference cost for accepted adapters.

### 5. Jev and LLMs on labeled decision tasks

Compare Jev by TypeSafe AI with selected LLM approaches on the same labeled classification, routing or scoring tasks. Use Jev's typed decision forms, such as Choice, Score and Noul, only where they match the task contract. Define the decision inputs, allowed outputs, ground truth and scoring rules before running either system. Report decision accuracy, calibration where applicable, abstention or invalid outcomes, latency and cost. Keep this study separate from general text-generation rankings because it tests decision behavior under a shared task contract.

**Evidence:** versioned labeled task set, adapter or API configuration, exact decision schema, per-example outcomes, aggregate metrics with uncertainty and an error analysis. Product-specific integration details remain contingent on the selected Jev interface and version.

### 6. Packaging, accelerator preflight and memory containment

Build reproducible serving containers and verify the NVIDIA container runtime/CDI path, driver/library compatibility, model loading and streaming contract. Create controlled accelerator-not-visible and memory-pressure drills. Locate a repeatable KV-cache or OOM boundary and verify at least one admission, rejection or recovery control.

**Evidence:** immutable manifests and digests, compatibility matrix, effective launch flags, failure signatures, memory telemetry, client-visible behavior and verified recovery state.

### 7. Saturation, SLO and cost

Hold input/output length fixed while sweeping concurrency. Separately hold the request mix fixed while sweeping offered arrival rate. Measure schedule lag and offered versus achieved rate so client overload is not mistaken for server capacity. Find the highest SLO-qualified goodput, not merely the highest raw throughput.

**Evidence:** predeclared TTFT/TPOT/end-to-end SLOs, warmup policy, request schedule, achieved rate, errors, client CPU/network load, latency distributions and cost per qualifying unit of work.

### 8. Prefix reuse

Within each runtime, compare cache enabled and disabled where supported. Control exact shared-prefix ratios and separate cold from warm behavior. Keep the model revision, tenant or isolation context, tokenizer, adapters and other eligibility conditions fixed. Exact-token reuse is not semantic caching.

**Evidence:** eligible and reused tokens, cache-hit definition, KV capacity, evictions or recomputation, prefill duration, TTFT and SLO-qualified goodput. Reset cache state between the appropriate arms.

### 9. Batching, scheduling and mixed traffic

Hold the workload fixed while changing chunked-prefill support or configuration, chunk size and token budget one variable at a time. Then vary the long/short traffic mix. Continuous batching is part of the scheduler; do not assume every engine exposes a valid off mode. A static-batch reference is a separate workload if the runtime supports it.

**Evidence:** verified effective flags, running/waiting requests, scheduled tokens per iteration when exposed, queue time, TTFT and decode gaps by request class, maximum wait, starvation indicators and KV time series.

### 10. Attention kernels and precision

Compare two supported attention backends with verified dispatch, then run a separate weight/KV precision comparison. Unsupported combinations are excluded rather than forced. Record the actual attention backend and version; “Flash on/off” is insufficient provenance.

**Evidence:** compatibility record, profiler confirmation where available, memory use, latency, useful throughput and results on the fixed quality set against its acceptance threshold.

### 11. Speculative decoding and structured outputs

Compare a target-only baseline with a compatible draft/verification path while sweeping proposal length and load. Separately compare prompt-only structured output with constrained generation under equivalent contracts. Parse or schema validity and independently judged semantic correctness remain separate outcomes.

**Evidence:** accepted tokens per step and its definition, draft and verification duration, added memory, TTFT/TPOT/goodput, retries, schema validity, semantic correctness, unsupported claims and total cost.

### 12. Parallelism within one node

Compare **data parallelism (DP)** replicas with **tensor parallelism (TP)** partitioning under the same total GPU budget and workload. Add **pipeline parallelism (PP)** when model fit or topology justifies it. For mixture-of-experts models, study **expert parallelism (EP)** and expert load balance as a separate dimension.

DP replicates model workers and partitions requests or training examples; TP divides tensor work; PP divides layers or stages; EP places experts across devices. The useful combination depends on model architecture, memory, batch shape, topology and communication cost.

**Evidence:** GPU topology and NVLink/PCIe paths, placement, memory per rank, collective time/bytes, PP stage balance, expert load/skew, throughput and request tails.

### 13. Parallelism across nodes

Compare replica placement and TP/PP/EP layouts on a documented network topology. Do not carry within-node assumptions across Ethernet or InfiniBand boundaries. Scale only when model fit or measured capacity justifies the communication and operational cost.

**Evidence:** node and accelerator placement, NIC/link speeds, selected transport, collective latency, throughput, transfer volume, failures and recovery behavior.

### 14. Prefill/decode disaggregation and cache-aware routing

Compare a colocated baseline with supported disaggregated serving under the same arrival process, then vary the prefill/decode capacity ratio. Compare simple routing with queue-aware, cache-aware and prompt-length-aware policies. Cache reuse must be balanced against queue delay, load skew and fairness.

Prompt length is observable at routing time; completion length usually is not. A short-request pool needs an admission rule, overflow policy and fairness metric, not just a prompt-token threshold.

**Evidence:** KV-transfer bytes and duration, queue and utilization in both pools, cache ownership, cancellation/failure behavior, routing decisions, hit benefit versus queue delay, class-specific SLO attainment, starvation and maximum wait.

### 15. Slurm and Kubernetes orchestration

Use Slurm for representative queued batch training, scheduled experiments and tightly coordinated multi-node jobs. Use Kubernetes for representative long-running services, platform APIs, deployment controllers, autoscaling and serving orchestration. Validate GPU discovery and allocation with the NVIDIA GPU Operator/device plugin, then study GitOps-managed KServe and Ray Serve deployment, with operators such as KubeRay managing the relevant cluster lifecycle. Run a metrics-driven autoscaling load test and a controlled scaling incident; use measured SLO capacity and recorded prices to build a capacity plan. Compare these platform choices separately from runtime engines such as vLLM, SGLang and TensorRT-LLM. Treat these as common strengths rather than exclusive boundaries: Kubernetes can schedule training, and Slurm environments can host inference services.

**Evidence:** comparable job and service definitions plus an explicit decision based on queue semantics, gang scheduling, topology awareness, failure recovery, service discovery, rollout control and operator burden. Keep platform health evidence separate from engine benchmarks.

### 16. Release gates, recovery and capstone synthesis

Combine promising settings for the declared use case and test interactions against the original baseline. Record regressions and reject configurations that miss the quality, latency or budget gate. Exercise cold/warm behavior, bounded admission, an intentionally bad candidate, rollback and recovery. Build a reproducible release candidate with dependency inventory, image/model digests and verified artifact provenance; record a controlled reliability drill for each selected failure mode. Trace retrieval through generation when the RAG capstone is ready, then produce the portfolio report and public demo from verified evidence.

**Evidence:** fixed workload and gates, repeated measurements, rejected configurations, immutable release manifest, pre-promotion rejection, recovery time, retained failure evidence, end-to-end traces and successful cleanup. A local mock validates gate logic only; it does not validate production availability, autoscaling or provider billing.

## Current status

**Measured or verified in the Episode 0 candidate:** sanitized historical aggregates, the native dashboard, metric/schema checks, synthetic offline rehearsal and a manual existing-endpoint benchmarking path. Each capability is labeled with its actual validation status in the package.

**Planned:** the experiments above beyond the Episode 0 foundations. TensorRT-LLM can join after its model, image, launch, streaming and output-validation contracts pass. NVIDIA Triton Inference Server is a planned deployment comparison with its execution backend identified explicitly; it is distinct from the Triton attention backend recorded in Episode 0. TGI remains a compatibility candidate only if its selected version fits the intended scope. No backend receives a chart entry for a run that never happened.

Each later topic can produce a concept post and a measured lab note. Do not publish a claimed result before the experiment exists. The minimum useful contribution is one named hypothesis, one reproducible configuration, one interpretable chart, and a report that includes a failed or inconclusive result when that is what happened.

## Technical references

- [NVIDIA parallelism guide](https://docs.nvidia.com/megatron-core/developer-guide/latest/user-guide/parallelism-guide.html): DP, TP, PP and EP.
- [Hugging Face PEFT](https://huggingface.co/docs/transformers/peft): frozen base weights, trainable adapters and quantized adaptation.
- [TypeSafe AI: Jev](https://docs.typesafe.ai/introduction): typed decision primitives and their outputs.
- [Slurm and Kubernetes](https://slurm.schedmd.com/kubernetes.html) and [Kubernetes workload controllers](https://kubernetes.io/docs/concepts/workloads/controllers/): scheduling and service roles.

These sources define mechanisms and interfaces. The experiments and acceptance criteria above are our proposed learning plan.
