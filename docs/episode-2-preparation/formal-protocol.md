# Episode 02 formal protocol

Episode 02 is **Equal-work runtime baseline**. It compares vLLM and SGLang only after model revision, tokenizer/template, purpose-written corpus, logical traces, sampling, requested output, quality rules, physical GPU policy and common launch overrides are frozen. Engine-native defaults may differ and are recorded; they are not silently tuned into equivalence.

The public synthetic fixture contains eight equally weighted workflow classes: short, long-prefill, output-heavy, structured JSON, code/reasoning, tool calling, multi-turn conversation and a dependent agent chain. One unit per class is eight workflows and twelve model turns per block. Six blocks are 48 workflows and 72 turns per engine/arm/cell. Fixture tool results are deterministic; model measurements are never synthetic.

The measured contract must freeze 6–8 repetition blocks, supported concurrency cells, cold/warm separation, any separately labeled open-loop stress, arrival/admission rules, work/quality/SLO/cost/resource safeguards and paired uncertainty before baseline collection. Closed- and open-loop observations are never pooled. p99 needs at least 1,000 applicable valid observations in every claimed arm/cell/class; otherwise p95 is the headline and p99 is descriptive/inconclusive.

The committed synthetic protocol is intentionally `execution_ready: false`. Model, images, defaults manifests, exact cells and science thresholds require a later hash-bound owner review and compiled cost/cleanup plan. Offline validation neither authorizes spending nor establishes provider capability.

Schemas: `schemas/episode2-protocol.schema.json` and `schemas/episode2-trace.schema.json`. Fixture: `tests/fixtures/episode2/protocol.synthetic.json`.
