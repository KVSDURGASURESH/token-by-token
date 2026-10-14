# Episode 02 formal protocol

Episode 02 is **Equal-work runtime baseline**. It compares vLLM and SGLang only after model revision, tokenizer/template, purpose-written corpus, logical traces, sampling, requested output, quality rules, physical GPU policy and common launch overrides are frozen. Engine-native defaults may differ and are recorded; they are not silently tuned into equivalence.

The public synthetic fixture contains eight equally weighted workflow classes: short, long-prefill, output-heavy, structured JSON, code/reasoning, tool calling, multi-turn conversation and a dependent agent chain. One unit per class is eight workflows and twelve model turns per block. Six blocks are 48 workflows and 72 turns per engine/arm/cell. Fixture tool results are deterministic; model measurements are never synthetic.

The measured contract must freeze 6–8 repetition blocks, supported concurrency cells, cold/warm separation, any separately labeled open-loop stress, arrival/admission rules, work/quality/SLO/cost/resource safeguards and paired uncertainty before baseline collection. Closed- and open-loop observations are never pooled. p99 needs at least 1,000 applicable valid observations in every claimed arm/cell/class; otherwise p95 is the headline and p99 is descriptive/inconclusive.

The committed synthetic protocol is intentionally `execution_ready: false`. Model, images, defaults manifests, exact cells and science thresholds require a later hash-bound owner review and compiled cost/cleanup plan. Offline validation neither authorizes spending nor establishes provider capability.

Schemas: `schemas/episode2-protocol.schema.json` and `schemas/episode2-trace.schema.json`. Fixture: `tests/fixtures/episode2/protocol.synthetic.json`.


## Offline implementation and admission

Concrete initial prompts and canonical successors share one message-building implementation. Trace hashes bind actual message arrays; logical IDs replay across blocks. `scripts/build_episode2_inputs.py` verifies the pinned public tokenizer assets/template offline, renders tool schemas and all twelve initial/dependent turns, and refuses any token-band/context mismatch. Admission manifests describe purpose-written inputs and contain no model measurements. The Qwen2.5-32B candidate's current long-prefill input is 3,279 tokens; this is a local input receipt, not execution approval.

`PYTHONPATH=src:scripts .venv/bin/python scripts/run_episode2_loopback_rehearsal.py --output /private/tmp/NEW-EPISODE2-REHEARSAL --blocks 6 --mode closed-loop` exercises actual localhost SSE. Use a separate new directory for `--mode open-loop`. Both are classified `synthetic_mock`. Warmup is excluded; all scheduled, attempted, dropped and dependency-blocked identities remain. `run_campaign` executes the counterbalanced block order. An unequal overloaded replay can complete its scheduler rehearsal while remaining explicitly non-equivalent and ineligible for comparison.

Measured contracts additionally require predeclared end-to-end/TTFT/TPOT SLOs, median and goodput floors, error/quality/admission bounds, delivered-output tolerance, cost ceiling and explicit resource limits. Missing thresholds/evidence leave comparison inconclusive; they never become an accepted winner. Synthetic fixtures retain their non-authorizing draft thresholds.

## Optimization handoff

`episode2_arms.select_arms` accepts only a supported recorded mechanism with controlled intervention lineage plus exact pinned-runtime capability/default/help proof. Unsupported flags, speculative decoding, unrelated groups and changed defaults supply no optimization proposal. `build_rerun` preserves workload, seed, mixture, logical trace, quality and reset rules; the selected treatment configuration belongs to a new fully bound compiler unit. Every proposal remains `execution_ready: false` and requires a new exact paid approval. Hypotheses and narrower unqualified gaps do not establish a winner.

An optimization proposal requires the complete evaluated hypothesis and its recorded baseline/intervention evidence. Selection recomputes the disposition and evidence digests. Retained help text and effective default bytes must match their digests, pinned engine version, image and declared native flag; before values must equal those defaults and scalar support must match the bounded pinned control registry. A partial supported label, duplicate lineage or an invented support rule supplies no arm. These checks bind identity and computation; independent review establishes source authority. The initial compiler remains defaults-only, so a matched optimization plan requires a separate validated extension and paid approval after actual RCA.
