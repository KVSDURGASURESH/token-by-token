# Token by Token — Inference Lab roadmap

**Token by Token** is the working name for this learning series; **Inference Lab** is its tagline. Episodes 00–02 have recorded public studies. Episode 03 has retained measurements and a local dashboard/article awaiting owner release review. Episodes 04 onward are **planned**. This roadmap does not authorize GPU spending or claim that the integrations or experiments already exist.

This is the canonical sixteen-part map of future work. The main serving path is **measurement → equal-work baseline → single-GPU optimization → parallelism → routing and operations**. Sections 11–13 are companion studies to take alongside that path, not prerequisites for the next optimization experiment. The roadmap supports the [three capstone project families](capstone-projects.md); it does not create a fourth project.

## Evidence contract for every stage

Benchmarking and quality evaluation answer different questions and must travel together.

- **Benchmarking** measures resource use and service behavior: TTFT, TPOT, end-to-end latency, throughput, SLO-qualified goodput, memory, errors and cost under a declared workload.
- **Quality evaluation** measures whether an output or decision is useful and correct: task accuracy, semantic correctness, citation support, abstention, schema compliance and task-specific acceptance thresholds.

A faster configuration that fails the quality gate is not a winner. A quality comparison with uncontrolled prompts, decoding or workloads does not explain runtime behavior. Each measured lab therefore fixes the work contract, records both result classes and reports tradeoffs rather than collapsing them into one score.

For service experiments, preserve request and repetition IDs, input/output token counts, stop reasons, stream-event timestamps, warmup state, errors and request class. Record the exact model, tokenizer/template hashes, image digest, harness commit, runtime flags, hardware and pricing basis. Capture runtime queue, prefill, decode, KV-cache and scheduler counters when exposed, plus host, GPU and network telemetry at a documented sampling interval. Correlate request traces with OpenTelemetry, service metrics in Prometheus/Grafana and GPU counters from DCGM where supported. A missing metric stays unavailable with its reason.

Pooled percentiles, per-repetition percentiles and confidence intervals are different objects. Use uncertainty estimates appropriate to independent repetitions. Do not claim that a fixed sample count automatically makes p99 reliable, and never reconstruct request distributions from aggregate p50/p95/p99.

Packaging, accelerator visibility, reproducible inputs and bounded cleanup are prerequisites for every paid experiment. Episode 14 is a dedicated reliability/containment study, not the first time those prerequisites are checked. New speculative and MoE profiles remain unverified until model/runtime compatibility and the full local execution path are demonstrated.

## The experiment map

**Numbering provenance:** this is `episode-catalog.v2`, effective 2026-10-02. Historical evidence, handoffs and result packs keep the Episode 0–16 numbers recorded under `episode-catalog.v1`; use the explicit old-to-current map in `public-data/contracts/episode-catalog.v2.json` when comparing them with this roadmap. The reorder changes planning identity only and does not relabel stored results.

### 1. Measurement and quality contracts

Choose a use case and declare its output contract, quality gate, latency SLO, memory ceiling and budget. Create deterministic natural-stop and fixed-output workload modes, raw-request export and a repetition policy. Keep schema validity separate from semantic correctness.

**Evidence:** versioned workload and quality sets, declared thresholds and denominators, exact provenance, raw per-request records and a report schema that can retain failed or inconclusive results.

### 2. Equal-work runtime baseline

Compare the same model, corpus, template, output contract and sampling settings across an HF/PyTorch control, vLLM and SGLang where compatible. Randomize or counterbalance execution order. Keep cold start separate from steady state, and compare output-length distributions before interpreting throughput.

**Evidence:** selected images and kernels, tokenizer/template hashes, per-repetition TTFT and end-to-end latency, output lengths, stop reasons, correctness checks, errors, device telemetry and attributable cost.

### 3. Prefix reuse

Within each runtime, compare cache enabled and disabled where supported. Control exact shared-prefix ratios and separate cold from warm behavior. Keep the model revision, tenant or isolation context, tokenizer, adapters and other eligibility conditions fixed. Exact-token reuse is not semantic caching.

**Evidence:** eligible and reused tokens, cache-hit definition, KV capacity, evictions or recomputation, prefill duration, TTFT and SLO-qualified goodput. Reset cache state between the appropriate arms.

### 4. Speculative decoding

Compare a target-only baseline with a runtime-verified compatible draft or proposal path. Hold model, quality contract and workload fixed; record proposal acceptance, draft/verification overhead and memory. Test short and longer outputs separately. Structured-output compatibility is a separate control, not an assumed speedup.

**Evidence:** accepted tokens per step, target/draft/verification time, TTFT/TPOT, delivered token counts, task correctness, memory and full cost.

### 5. Mixture-of-experts inference

Fix one supported MoE model and runtime. Establish a single-device or minimum-fit baseline; vary only supported routing/batching settings with quality held fixed. Record total versus active parameters and expert routing skew. A dense-versus-MoE comparison is contextual unless output quality and work can be matched; it is not an architecture winner claim.

**Evidence:** total/active parameter basis, router/expert utilization, expert imbalance, memory residency, token throughput, TTFT/TPOT tails, output quality and cost.

### 6. Serving tune-up: scheduling and precision

Study A changes chunked-prefill/token budgets and then long/short traffic mix, one factor at a time. Study B holds scheduling fixed while comparing verified attention backends, then separately weight/KV precision. Keep model, delivered work and quality checks fixed within each study. Unsupported paths stay unavailable. Earlier episodes recorded these settings but did not complete these isolated comparisons.

**Evidence:** effective settings, queue/prefill/decode timings by class, starvation/KV counters, verified kernel dispatch, memory, quality, latency, throughput and cost.

### 7. Parallelism within one node

Study A compares DP replicas and TP partitioning on a fixed model and GPU budget; add PP only when model fit or topology justifies it. Study B uses one MoE model to compare supported EP and compatible DP/TP/EP combinations, measuring expert balance and all-to-all overhead. Do not pool different models or hardware budgets.

**Evidence:** GPU/NVLink/PCIe topology, placement, memory per rank, collective time/bytes, PP stage balance when used, expert skew/all-to-all overhead, request tails, goodput and cost.

### 8. Parallelism across nodes

Compare replica placement and TP/PP/EP layouts on a documented network topology. Do not carry within-node assumptions across Ethernet or InfiniBand boundaries. Scale only when model fit or measured capacity justifies the communication and operational cost.

**Evidence:** node and accelerator placement, NIC/link speeds, selected transport, collective latency, throughput, transfer volume, failures and recovery behavior.

### 9. Prefill/decode disaggregation and cache-aware routing

Compare a colocated baseline with supported disaggregated serving under the same arrival process, then vary the prefill/decode capacity ratio. Compare simple routing with queue-aware, cache-aware and prompt-length-aware policies. Cache reuse must be balanced against queue delay, load skew and fairness.

Prompt length is observable at routing time; completion length usually is not. A short-request pool needs an admission rule, overflow policy and fairness metric, not just a prompt-token threshold.

**Evidence:** KV-transfer bytes and duration, queue and utilization in both pools, cache ownership, cancellation/failure behavior, routing decisions, hit benefit versus queue delay, class-specific SLO attainment, starvation and maximum wait.

### 10. Slurm and Kubernetes orchestration

Use Slurm for representative queued batch training, scheduled experiments and tightly coordinated multi-node jobs. Use Kubernetes for representative long-running services, platform APIs, deployment controllers, autoscaling and serving orchestration. Validate GPU discovery and allocation with the NVIDIA GPU Operator/device plugin, then study GitOps-managed KServe and Ray Serve deployment, with operators such as KubeRay managing the relevant cluster lifecycle. Run a metrics-driven autoscaling load test and a controlled scaling incident; use measured SLO capacity and recorded prices to build a capacity plan. Compare these platform choices separately from runtime engines such as vLLM, SGLang and TensorRT-LLM. Treat these as common strengths rather than exclusive boundaries: Kubernetes can schedule training, and Slurm environments can host inference services.

**Evidence:** comparable job and service definitions plus an explicit decision based on queue semantics, gang scheduling, topology awareness, failure recovery, service discovery, rollout control and operator burden. Keep platform health evidence separate from engine benchmarks.

### 11. Model internals: weights to optimization

Use a small inspectable model to trace stored weights through embeddings, attention, the forward pass and logits. Then trace the backward pass through gradients, optimizer state and parameter updates. Connect these mechanisms to memory and compute costs without presenting the small-model exercise as a large-model benchmark.

**Evidence:** reproducible tensor-shape and parameter-count walkthroughs, attention inspection, gradient checks and optimizer-state accounting.

### 12. LoRA and QLoRA with held-out evaluation

Hold the dataset, prompt format, training budget and evaluation set fixed while comparing LoRA with QLoRA. In both cases the base weights remain frozen and low-rank adapters are trained; QLoRA quantizes the frozen base while gradients flow through it to the adapters. Record trainable parameters, base-weight precision, adapter configuration, peak memory, training time and checkpoint lineage. Evaluate both adapters on held-out task quality and serving behavior; successful training or lower loss alone does not establish improvement.

**Evidence:** deterministic lineage, learning curves, memory/time measurements, held-out quality results, uncertainty across repetitions where practical and inference cost for accepted adapters.

### 13. Jev and LLMs on labeled decision tasks

Compare Jev by TypeSafe AI with selected LLM approaches on the same labeled classification, routing or scoring tasks. Use Jev's typed decision forms, such as Choice, Score and Noul, only where they match the task contract. Define the decision inputs, allowed outputs, ground truth and scoring rules before running either system. Report decision accuracy, calibration where applicable, abstention or invalid outcomes, latency and cost. Keep this study separate from general text-generation rankings because it tests decision behavior under a shared task contract.

**Evidence:** versioned labeled task set, adapter or API configuration, exact decision schema, per-example outcomes, aggregate metrics with uncertainty and an error analysis. Product-specific integration details remain contingent on the selected Jev interface and version.

### 14. Packaging, accelerator preflight and memory containment

Build reproducible serving containers and verify the NVIDIA container runtime/CDI path, driver/library compatibility, model loading and streaming contract. Create controlled accelerator-not-visible and memory-pressure drills. Locate a repeatable KV-cache or OOM boundary and verify at least one admission, rejection or recovery control.

**Evidence:** immutable manifests and digests, compatibility matrix, effective launch flags, failure signatures, memory telemetry, client-visible behavior and verified recovery state.

### 15. Saturation, SLO and cost

Hold input/output length fixed while sweeping concurrency. Separately hold the request mix fixed while sweeping offered arrival rate. Measure schedule lag and offered versus achieved rate so client overload is not mistaken for server capacity. Find the highest SLO-qualified goodput, not merely the highest raw throughput.

**Evidence:** predeclared TTFT/TPOT/end-to-end SLOs, warmup policy, request schedule, achieved rate, errors, client CPU/network load, latency distributions and cost per qualifying unit of work.

**Dashboard backlog:** add campaign-level quoted, accrued and reconciled cost with
coverage and billing basis; phase-level setup, warmup, measurement, retry and collection
allocation; cost per valid request, per one million delivered output tokens and per
qualified concurrent-user-hour; and performance-versus-cost views. A comparison may
select at most three episode views. It must deduplicate shared campaign charges and
measurements, disclose allocation assumptions, gate ratios on compatible denominators,
and show **Unavailable** rather than zero when evidence is incomplete.

### 16. Release gates, recovery and capstone synthesis

Combine promising settings for the declared use case and test interactions against the original baseline. Record regressions and reject configurations that miss the quality, latency or budget gate. Exercise cold/warm behavior, bounded admission, an intentionally bad candidate, rollback and recovery. Build a reproducible release candidate with dependency inventory, image/model digests and verified artifact provenance; record a controlled reliability drill for each selected failure mode. Trace retrieval through generation when the RAG capstone is ready, then produce the portfolio report and public demo from verified evidence.

**Evidence:** fixed workload and gates, repeated measurements, rejected configurations, immutable release manifest, pre-promotion rejection, recovery time, retained failure evidence, end-to-end traces and successful cleanup. A local mock validates gate logic only; it does not validate production availability, autoscaling or provider billing.

## Current status

**Measured or verified in the Episode 0 candidate:** sanitized historical aggregates, the native dashboard, metric/schema checks, synthetic offline rehearsal and a manual existing-endpoint benchmarking path. Each capability is labeled with its actual validation status in the package.

**Planned:** Episodes 04 onward in the revised order. Earlier episodes recording a setting does not count as an isolated test of it. TensorRT-LLM can join after its model, image, launch, streaming and output-validation contracts pass. NVIDIA Triton Inference Server is a planned deployment comparison with its execution backend identified explicitly; it is distinct from the Triton attention backend recorded in Episode 0. TGI remains a compatibility candidate only if its selected version fits the intended scope. No backend receives a chart entry for a run that never happened.

Each later topic can produce a concept post and a measured lab note. Do not publish a claimed result before the experiment exists. The minimum useful contribution is one named hypothesis, one reproducible configuration, one interpretable chart, and a report that includes a failed or inconclusive result when that is what happened.

## Technical references

- [NVIDIA parallelism guide](https://docs.nvidia.com/megatron-core/developer-guide/latest/user-guide/parallelism-guide.html): DP, TP, PP and EP.
- [Hugging Face PEFT](https://huggingface.co/docs/transformers/peft): frozen base weights, trainable adapters and quantized adaptation.
- [TypeSafe AI: Jev](https://docs.typesafe.ai/introduction): typed decision primitives and their outputs.
- [Slurm and Kubernetes](https://slurm.schedmd.com/kubernetes.html) and [Kubernetes workload controllers](https://kubernetes.io/docs/concepts/workloads/controllers/): scheduling and service roles.

These sources define mechanisms and interfaces. The experiments and acceptance criteria above are our proposed learning plan.
