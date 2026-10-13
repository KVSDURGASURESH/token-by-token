# Episode 02: Equal-work runtime baseline

**Status:** Planned — formal draft implemented; no provider measurements.

## Question

When vLLM and SGLang receive the same validated mixed-work trace on the same physical GPU policy, how do serving latency, workflow latency, qualified throughput, tails, quality, errors, resource pressure and attributable cost differ under their recorded defaults?

## What is fixed

The model/revision, tokenizer/template, public corpus, logical workflow/turn IDs, tool fixtures, requested outputs, sampling, quality gates, repetition blocks and matched order policy. Engine defaults are recorded separately. Startup/cold and warm steady state remain separate.

## Workload

Every measured block contains short, long-prefill, output-heavy, structured, code/reasoning, tool-call, conversation and dependent agent-chain workflows. Dependent turns consume validated semantic state; invalid/divergent trajectories remain failures rather than being replaced with fixtures.

See the [formal protocol](../../docs/episode-2-preparation/formal-protocol.md). The included fixture is an offline rehearsal and cannot produce recorded evidence, costs or a runtime winner.
