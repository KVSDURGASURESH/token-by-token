# Token by Token — Inference Lab capstone portfolio

**Token by Token** is the working name for this learning series; **Inference Lab** is its tagline. The portfolio asks one connected question: how do we build reliable AI under a fixed budget, from GPU tokens to correct, cited answers?

The three capstones have distinct outcomes: a serving configuration, an evidence-grounded answer system and a release process that can reject and recover from failure. The charters below own those outcomes; the [roadmap](roadmap.md) owns the shared experiment sequence.

## Current RUNPOD mapping

| Project | Current evidence |
|---|---|
| **1 — Serving Reliability Lab** | Episode 0: exploratory vLLM/SGLang measurements on Qwen2.5-32B-Instruct, one H100 80GB HBM3 per run, a local dashboard and an offline fixture workflow. Controlled optimization and distributed experiments remain planned. |
| **2 — Evidence-Grounded RAG Lab** | No measured RAG result in this package. |
| **3 — Release and Recovery Lab** | Provenance, fixture validation and cleanup practices are foundations; no measured release-gate or rollback experiment in this package. |

## Project 1 maps into the current roadmap as follows

| Planned phase | What we will explore |
|---|---|
| **Establish a comparable baseline** | Measurement and quality contracts; compare runtimes performing the same declared work. [Stages 1–2](roadmap.md#1-measurement-and-quality-contracts). |
| **Bound capacity and test optimizations** | Memory limits, saturation, prefix reuse, continuous batching, chunked prefill, attention kernels, precision and speculative decoding. [Stages 6–11](roadmap.md#6-packaging-accelerator-preflight-and-memory-containment). |
| **Scale within and across nodes** | Data (DP), tensor (TP), pipeline (PP) and expert (EP, for MoE) parallelism; split prefill/decode; test cache-aware and request-length-aware routing. [Stages 12–14](roadmap.md#12-parallelism-within-one-node). |
| **Operate and validate** | Slurm/Kubernetes, KServe/Ray Serve, observability, quality gates, autoscaling and recovery; combine and retest settings for the use case. [Stages 15–16](roadmap.md#15-slurm-and-kubernetes-orchestration). |

## Project 1 — Serving Reliability Lab

Project 1 asks four cumulative questions:

1. Can different runtimes perform the same declared work and preserve acceptable output quality?
2. How do long prompts, concurrency and offered load affect interactive requests and SLO-qualified goodput?
3. Where are the KV-cache and memory-pressure boundaries, and which admission or scheduling control contains failure?
4. Which combined configuration meets a declared latency, quality and cost target, including under controlled failure and recovery?

Prefix reuse, attention kernels, precision and speculative decoding are candidate optimizations. Structured outputs add a separate correctness requirement: parseable or schema-valid output is not necessarily semantically correct. Distributed execution follows only after model fit or a measured capacity limit justifies its communication and operational cost.

## Project 2 — Evidence-Grounded RAG Lab

Project 2 proposes an evaluation-first RAG system built from learner-authored or appropriately licensed runbooks and an independently labeled question set. Its controlled comparisons cover:

- BM25 and dense retrieval baselines;
- fixed-token, structure-aware and semantic chunking;
- smaller and stronger embedding candidates;
- BM25, dense retrieval and hybrid reciprocal-rank fusion;
- reranking on identical candidate sets;
- top-k and retrieved-token-budget choices;
- citation support and correct abstention; and
- selected combined configurations followed by ablations.

The evidence contract includes retrieval metrics, answer correctness, citation support and coverage, abstention, component and end-to-end latency, recurring versus indexing cost, and successful answers that meet declared quality and latency gates.

The publishable experiment still needs a real versioned corpus and gold set, selected model adapters, end-to-end timers, generation, independent judgments and a reproducible report. Scaffolding or a synthetic fixture does not establish RAG quality.

## Project 3 — Release and Recovery Lab

Project 3 has four proposed outcomes:

1. immutable model, runtime and configuration manifests with repeatable evaluations;
2. an intentionally bad candidate rejected by quality or latency gates before promotion;
3. measured cold and warm behavior, bounded admission or rejection, and one controlled rollback and recovery; and
4. request traces through retrieval and generation, with retained failure evidence and recovery time.

Local mocks can validate gate logic. They do not validate production availability, autoscaling or provider billing. Live infrastructure work requires a separate approved plan and budget.

## What is not a fourth project

These are shared learning tracks for **Serving Reliability Lab**, **Evidence-Grounded RAG Lab** and **Release and Recovery Lab**. Each supports one of those outcomes; none is a separate fourth product.

| Shared learning track | What it helps us understand |
|---|---|
| **Model internals** | Weights, attention, forward/backward passes, gradients and optimizer state; connect them to memory and compute. [Stage 3](roadmap.md#3-model-internals-weights-to-optimization). |
| **LoRA and QLoRA** | Trainable adapters, frozen base weights, precision and memory; evaluate changes on held-out tasks. [Stage 4](roadmap.md#4-lora-and-qlora-with-held-out-evaluation). |
| **Benchmarking and quality evaluation** | Measure speed, resources and cost alongside correctness and usefulness. Every experiment carries both contracts. |
| **Jev vs LLMs** | Compare TypeSafe AI's Jev with LLMs on matched, labeled classification, routing or scoring tasks. [Stage 5](roadmap.md#5-jev-and-llms-on-labeled-decision-tasks). |
| **Slurm vs Kubernetes** | Choose how to schedule queued jobs, coordinated experiments and continuously operated services; study when a combination fits. [Stage 15](roadmap.md#15-slurm-and-kubernetes-orchestration). |

A concept post, optimization experiment, incident drill or dashboard is a supporting artifact. The roadmap owns its procedure and evidence requirements. **All future work is planned.** Paid experiments require an approved execution plan and budget.
