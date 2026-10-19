# Episode 02: Equal-work runtime baseline

**Status:** Recorded — six paired blocks completed; comparison rejected, no winner.

144 measured requests completed; each engine qualified **66/72 requests** and **42/48 workflows**. See the [recorded results](../../docs/episode-2-results.md) for denominators, uncertainty and exclusions.

- [Live Episode 02 dashboard and evidence lab](https://tokenbytoken.org/episodes/02-equal-work-runtime-baseline/)
- [Published Substack article](https://durgasuresh.substack.com/p/token-by-token-episode-02-can-144)
- [Published LinkedIn post](https://www.linkedin.com/feed/update/urn:li:activity:7517773835983572992/)

Provider-attributed resource-lifetime billing was **$10.02**: **$3.04** for the successful attempt and **$6.98** for earlier attempts. Per-engine/measured-window attribution is unavailable; invoice settlement remains unverified.

Episode 01’s tail-latency cause remains open. Episode 03 plans controlled prefix reuse; it is not a measured result.

## Question

When vLLM and SGLang receive the same validated mixed-work trace on the same physical GPU policy, how do serving latency, workflow latency, qualified throughput, tails, quality, errors, resource pressure and attributable cost differ under their recorded defaults?

## What is fixed

The model/revision, tokenizer/template, public corpus, logical workflow/turn IDs, tool fixtures, requested outputs, sampling, quality gates, repetition blocks and matched order policy. Engine defaults are recorded separately. Startup/cold and warm steady state remain separate.

## Workload

Every measured block contains short, long-prefill, output-heavy, structured, code/reasoning, tool-call, conversation and dependent agent-chain workflows. Dependent turns consume validated semantic state; invalid/divergent trajectories remain failures rather than being replaced with fixtures.

See the [formal protocol](../../docs/episode-2-preparation/formal-protocol.md). The included fixture is an offline rehearsal and cannot produce recorded evidence, costs or a runtime winner.
