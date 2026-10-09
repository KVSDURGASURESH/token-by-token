 # Token by Token episodes as AgentBench presets — assessment and design

 Status: plan (not implemented). Date: 2026-10-09.
 This document lives in the public repository by design; it references the
 private AgentBench codebase only at the capability/CLI level and contains no
 credentials, internal URLs, or private data.

 ## 1. Purpose

 Assess every Token by Token episode (00–16, `episode-catalog.v2`) against
 what AgentBench can already do, and design a "preset" mechanism in the
 AgentBench codebase so each episode can be invoked as a single command that
 produces the evidence that episode's contract asks for.

 ## 2. AgentBench capability summary (what a preset can use)

 AgentBench answers one question:

 > Model A, served by engine E on GPU G, supports X concurrent users ×
 > Y open sessions each, with 9 in 10 requests decoding at ≥ T tok/s
 > (p10) — TTFT reported alongside.

 Inputs `T` (`--target-tps`, default 20) and `Y` (`--slots-per-user`,
 default 2); output `X` is measured; optional TTFT gate (`--target-ttft-s`).

 Phases (all in one `agentbench bench` run, or individually via
 `agentbench run --run-config ...`):

 1. **Coherence + smoke** — plain recall, needle-in-context, tool-call
    probes; a wrong answer stops the run before any measurement.
 2. **Calibrate** — 500 × 1024-token prompts, 256-token generations, 16
    concurrent; throughput + TTFT baseline; >1% invalid requests fail the
    run; optional SGLang `bench_serving` cross-check (mismatch > 5% fails).
 3. **PP/TG** — prompt-processing curve at 512…131K tokens, token-generation
    at 0…120K context; 1 warmup + 3 measured repeats per point; unique
    prefixes defeat the prefix cache.
 4. **Sweep** — per concurrency level: warmup + measurement; 1024-token
    prompts, 512-token outputs, continuous loops; per-level TTFT p50/p95,
    decode speed, throughput, error rate.
 5. **Agents** — real multi-turn coding sessions (system prompt + 8 tool
    definitions + accumulated history), per-worker process isolation,
    parquet + per-level summaries.
 6. **Sustained/soak** (with `--duration`) — holds the best level for the
    duration, periodic snapshots, STABLE/DEGRADED/UNSTABLE verdict.

 Supporting machinery:

 - **Combos** (`configs/combos/*.yaml`): model + revision + engine +
   launch flags + GPU + endpoints + telemetry block. One file per
   deployment; secrets as `${VARS}`.
 - **Run configs** (`configs/runs/*.yaml`): `run_name`, `mode`, `combo`,
   `workload`, `profile`, `levels`, `warmup_s`, `measure_s`, `workers`,
   `repeats_at_knee`, `bisect_steps`, `tracing`, `seed`.
 - **Workloads** (`configs/workloads/`): mix of coding/chat/tool-agent
    traffic, task mix, effort mix, prompt corpus globs, quality block
    (`task_count`, `max_resolve_drop_pts`, `harness_cmd`).
 - **Profiles** (`agentbench/profiles/`): client behavior models —
    `worst`, `kilo_like`, `theia_like`, `client_like`, `guarantee`.
 - **Corpora**: bundled real-traffic corpora (Nebius, Novita, WildChat,
    Trace Commons) with mix weights (`--corpus nebius:0.5,...`).
 - **Quality gate/grade**: resolve-rate grading of patches; a lever
    configuration is adopted only if resolve rate drops by no more than
    `quality.max_resolve_drop_pts` percentage points.
 - **Telemetry**: OTel (metrics/logs/traces) to a local collector,
    VictoriaMetrics/Loki/Tempo naming, GPU exporter (`/metrics`, `/clock`,
    `/health`), DCGM fallback, Grafana dashboards; per-run metric export.
 - **Report/compare**: `agentbench report <run>`, `agentbench compare
    <run-a> <run-b>`; verdicts include the capacity level.
 - **Deployment**: `tools/deploy_inference.py` (guided or `--answers`
    replay) installs vLLM/SGLang on a GPU host, launches, health-checks,
    and emits the combo file; `deploy/k8s/` runs campaign benchmarks as
    k8s Jobs with guard/hold scripts.

 ## 3. Episode catalog (v2, effective 2026-10-02)

 | # | Episode | Status | The question it answers |
 |---:|---|---|---|
 | 00 | Warm-up | Available (recorded, exploratory) | Can we measure at all? Qwen2.5-32B H100, vLLM 0.29.0 vs SGLang 0.5.20 |
 | 01 | Measure what matters | Available (recorded) | H200, 12/16/24 users, both engines vs the 20 tok/s decode floor |
 | 02 | Equal-work runtime baseline | Planned | Same model/corpus/contract across HF+PyTorch, vLLM, SGLang |
 | 03 | Prefix reuse | Planned | Does shared-prefix traffic change the picture? |
 | 04 | Batching, scheduling, mixed traffic | Planned | How do scheduler knobs interact with mixed workloads? |
 | 05 | Attention kernels and precision | Planned | Backend and KV precision tradeoffs (PP/TG shape) |
 | 06 | Speculative decoding and structured outputs | Planned | MTP/EAGLE speedup at equal quality; tool/JSON behavior |
 | 07 | Parallelism within one node | Planned | TP 1/2/4/8 on one machine |
 | 08 | Parallelism across nodes | Planned | TP×PP across a node boundary |
 | 09 | PD disaggregation and cache-aware routing | Planned | Prefill/decode split + routing |
 | 10 | Slurm and Kubernetes orchestration | Planned | Same workload under different schedulers |
 | 11 | Model internals: weights to optimization | Planned companion | How architecture maps to measured behavior |
 | 12 | LoRA and QLoRA with held-out evaluation | Planned companion | Adapter overhead at held-out quality parity |
 | 13 | SYSTEM 1 and LLMs on labeled decision tasks | Planned companion | Decision quality under load |
 | 14 | Packaging, accelerator preflight and memory containment | Planned | Reproducible images, preflight, OOM behavior |
 | 15 | Saturation, SLO and cost | Planned | Highest SLO-qualified goodput; cost per unit |
 | 16 | Release gates, recovery and capstone synthesis | Planned | Combined config, rollback, release manifest |

 Evidence contract (roadmap §"Evidence contract for every stage"): benchmark
 numbers and quality evaluation must travel together; a faster configuration
 that fails the quality gate is not a winner. Every preset below therefore
 carries both a performance gate and a quality gate where the episode's
 contract demands it.

## 4. Per-episode assessment

Legend for "AgentBench fit": **direct** = existing commands/configs only;
**extend** = needs a new preset/run-config but no engine work; **gap** =
needs new AgentBench code (listed under §9 phases).

| Ep | Fit | Preset name | AgentBench pieces used | Gate(s) |
|---:|---|---|---|---|
 | 00 | direct | `episode-00-warmup` | calibrate + pptg + small sweep | none (exploratory) |
 | 01 | direct | `episode-01-capacity` | full bench (sweep+agents) + soak | decode p10 ≥ 20 tok/s; TTFT reported, not gated |
 | 02 | extend | `episode-02-equal-work` | paired combos (hf-pt, vllm, sglang), counterbalanced order, same seed/workload | calibrate validity; quality grade parity |
 | 03 | extend | `episode-03-prefix-reuse` | flag matrix: prefix cache on/off + cached-token reporting | cache hit rate + per-level delta vs E02 |
 | 04 | extend | `episode-04-batching` | knob matrix (max seqs, batched tokens, chunked prefill) × profiles (headroom/worst) | per-knob sweep delta; error rate ≤ 1% |
 | 05 | extend | `episode-05-attention` | attention-backend × kv-dtype × quant matrix; PP/TG-focused | PP linearity, TG flatness at large context |
 | 06 | extend | `episode-06-spec-decode` | speculative (MTP/EAGLE) on/off; tool parser; structured-output sessions | quality gate: resolve drop ≤ 2 pts |
 | 07 | extend | `episode-07-tp` | tp-size 1/2/4/8 combos on multi-GPU pod | throughput/TPOT per TP; cost per user-hour |
 | 08 | gap | `episode-08-multi-node` | TP×PP across nodes; k8s Job per node | cross-node TPOT vs single-node |
 | 09 | gap | `episode-09-pd-disagg` | PD-disagg launch flags + router; cache-aware vs not | prefill/decode isolation metrics |
 | 10 | extend | `episode-10-orchestration` | k8s Jobs + runpod campaign scripts; guard/hold | wall-clock, spot resilience, cost |
 | 11 | direct | `episode-11-internals` | coherence + pptg + quality grade | study: correlations, no spend gate |
 | 12 | gap | `episode-12-lora` | base vs adapter combos; held-out quality | resolve parity + per-request overhead |
 | 13 | extend | `episode-13-decisions` | labeled decision-task workload; quality-first | accuracy/abstention thresholds |
 | 14 | extend | `episode-14-preflight` | deploy check + hw probe + coherence + smoke; mem-fraction sweep | preflight pass; OOM recovery |
 | 15 | direct | `episode-15-slo-cost` | sustained soak with `--duration`, TTFT gate, campaign cost tool | SLO-qualified goodput; cost/unit |
 | 16 | gap | `episode-16-release` | combined config + quality gate + reliability drill | gate matrix incl. bad candidate; recovery time |

### 4.1 Preset sketches (one per episode)

Each preset is a YAML run config under a new `configs/episodes/` directory in
AgentBench, referencing existing combos/workloads plus an `episode:` block
(schema in §5). Sketches show the discriminating fields only.

**episode-00-warmup** — replay/verify the warm-up.
 `mode: sweep`, small level set (1, 2, 4, 8), short warmup/measure,
 `--skip-calibrate` optional. Purpose: endpoint sanity + baseline shape, not
 capacity. Output: `levels.csv` + report.

**episode-01-capacity** — the flagship study (already run on H200/B200/B300/
 H100/RTX PRO 6000 for Qwen3.8-27B-FP8; the preset just standardizes it).
 Full bench: calibrate → pptg → sweep (1…256) → agents (real corpus,
 `--corpus nebius:0.5,novita:0.3,wildchat:0.2`, `--target-tps 20`,
 `--slots-per-user 2`) → soak at the sweet spot (`--duration 1h`).
 Output: capacity verdict + time series + metrics export. This is the
 closest thing to a finished preset today — only the `episode:` metadata
 block is new.

**episode-02-equal-work** — paired runs, one per engine + a HF/PyTorch
 control combo where compatible. Same workload config, same seed, same
 levels, counterbalanced execution order (randomized per campaign, order
 recorded in the run manifest). `agentbench compare` across the trio.
 Quality: `quality grade` on a fixed task set run identically per engine.

**episode-03-prefix-reuse** — flag matrix over the E02 combos:
 vLLM `--enable-prefix-caching` vs `--no-enable-prefix-caching` (plus
 `--enable-prompt-tokens-details` so cached-token counts land in
 `usage.prompt_tokens_details`); SGLang radix cache on/off. Workload:
 sessions with a shared system prompt + tools (the prompt pack guarantees
 shared prefixes) vs the unique-prefix PP/TG prompts. Evidence: cache hit
 rate + per-level TTFT/decode delta.

**episode-04-batching** — knob matrix: admission cap (max running
 requests / max num seqs), prefill chunk (max num batched tokens /
 chunked-prefill-size) × traffic profile (`headroom` vs `worst`). Output:
 per-knob sweep curves; interaction with mixed traffic.

**episode-05-attention** — matrix: attention backend (engine-default, fa3
 on Hopper, flashinfer/TRTLLM per GPU class), `kv-cache-dtype` bf16 vs fp8,
 model quant bf16 vs fp8. PP/TG is the primary output (backend choice shows
 up in the PP curve and in TG at large context); sweep secondarily.

**episode-06-spec-decode** — SGLang MTP/EAGLE (steps 3, top-k 1, 4 draft
 tokens, per the Qwen3.5–3.8 cookbook) vs none; vLLM
 `--speculative-config` where supported. Two sub-studies: (a) decode speed
 at fixed quality (quality gate: resolve drop ≤ `max_resolve_drop_pts`),
 (b) structured outputs: tool-call parser on/off with the agent workload
 and a JSON-schema session set.

**episode-07-tp** — one multi-GPU pod (2/4/8), four combos differing only in
 `--tp-size` (deploy_inference's `tp` answer), same model/revision/flags.
 Evidence: throughput and TPOT per TP degree + cost per user-hour; the
 knee moves as TP grows.

**episode-08-multi-node** — TP×PP across two+ nodes. Needs a multi-node
 launch helper (AgentBench today deploys per host). Pattern: k8s Jobs per
 node with a rendezvous, or runpod paired pods + SSH tunnel. Evidence:
 cross-node TPOT penalty vs E07 at equal TP total.

**episode-09-pd-disagg** — SGLang prefill/decode disaggregation + router
 (cache-aware vs random). New launch flags + a router endpoint in the combo
 (`base_url` points at the router). Evidence: prefill/decode isolation,
 TTFT under mixed short/long traffic, KV-transfer overhead.

**episode-10-orchestration** — run the identical E01 campaign under (a)
 k8s Jobs (AgentBench `deploy/k8s/` pattern: guard caps runtime, hold_pods
 pins workers), (b) Slurm (script-level; no AgentBench code, recorded as a
 companion), (c) RunPod campaign scripts. Evidence: wall-clock, preemption
 behavior, cost per campaign.

**episode-11-internals** — study preset, minimal spend: coherence probes +
 full PP/TG + `quality grade` on a fixed set, per architecture family
 (dense vs hybrid/linear-attention vs MoE if available). Output feeds the
 "weights to optimization" writeup; no capacity claim.

**episode-12-lora** — combos: base model, base + full-finetune checkpoint,
 base + LoRA adapter (`--enable-lora`/`--lora-modules` on vLLM; SGLang
 adapter flags). Held-out evaluation: `quality grade` baseline.json from
 the base, then gate on the adapters. Evidence: per-request overhead
 (TTFT/decode) at held-out quality parity.

**episode-13-decisions** — quality-first. Workload: a labeled decision-task
 set (built with `agentbench generate` + manual labeling; think SYSTEM-1
 quick decisions: classify/route/abstain). Gate: per-task accuracy and
 abstention against predeclared thresholds; benchmarking (TTFT at decision
 latency) secondary.

**episode-14-preflight** — packaging episode. Preset = the preflight
 sequence: `deploy_inference.py check` (host report) → `agentbench hw
 probe` → coherence → smoke (1 user, 60 s, full measurement path) →
 memory-fraction sweep (0.80/0.85/0.90) to map the OOM boundary and
 recovery. Evidence: preflight report + OOM/containment behavior.

**episode-15-slo-cost** — the money study. Sustained soak (`--duration` 1h+
 at the sweet spot) with a real SLO: `--target-tps 20` **and**
 `--target-ttft-s <declared>` (both gates active). Campaign cost via
 AgentBench's campaign cost tooling (quoted/accrued/reconciled). Output:
 SLO-qualified goodput, stability verdict, cost per user-hour / per M
 output tokens.

**episode-16-release** — capstone. Combines the winning knobs from E03–E07
 into one combo; reruns the E01/E15 gates; includes an intentionally bad
 candidate (expected to fail a gate — evidence the gate works), a rollback
 drill, and an immutable release manifest (model revision + engine version
 + image digest + harness commit + flags). Quality gate throughout.

## 5. Preset schema

New directory in AgentBench: `configs/episodes/episode-NN-<slug>.yaml`.
 It is a run config (everything `agentbench run --run-config` already
 understands) plus an `episode:` block:

 ```yaml
 # configs/episodes/episode-01-capacity.yaml
 episode:
   id: 01
   slug: measure-what-matters
   catalog: episode-catalog.v2        # provenance: which numbering this follows
   question: >
     How many concurrent agent users can this deployment serve while
     decoding at at least the target rate?
   evidence_contract:
     performance:
       gate: {metric: decode_p10_tps, op: ">=", value: 20}
       reported_not_gated: [client_ttft_ms_p50, client_ttft_ms_p95]
     quality: null                    # or {max_resolve_drop_pts: 2.0}
   outputs: [verdict, levels, soak, metrics]   # what must land in the run dir
   publication: token-by-token        # downstream consumer (sanitization pipeline)

 # ---- standard run-config fields below ----
 run_name: episode-01-capacity
 mode: sweep
 combo: configs/combos/<combo>.yaml   # or combos: [...] for a matrix
 workload: configs/workloads/<workload>.yaml
 profile: null
 levels: [1, 2, 4, 8, 16, 32, 48, 64, 96, 128]
 warmup_s: 30
 measure_s: 120
 workers: 16
 repeats_at_knee: 2
 bisect_steps: 2
 target_tps: 20
 slots_per_user: 2
 duration: 1h                         # enables the sustained/soak phase
 seed: 42
 ```

 Matrix episodes (E03–E05, E07, E12) use a `combos:` list plus a
 `matrix:` block:

 ```yaml
 combos:
   - configs/combos/model-gpu-vllm.yaml
   - configs/combos/model-gpu-sglang.yaml
 matrix:
   counterbalance: true               # order randomized per campaign, recorded
   run_per_combo: full                # or: calibrate-only, pptg-only
 ```

 Validation rules (enforced by a small schema check in `agentbench/config.py`
 or a dedicated `episodes.py`):

- `episode.id` 0–16, `slug` matches the catalog entry.
- `publication: token-by-token` requires `evidence_contract.performance`
  and, when the episode contract demands it, a quality gate.
- `combos:` + `matrix.counterbalance` require `seed` to be set.
- `duration` is required for E15/E16 presets.

## 6. CLI design

```
agentbench episode list                          # presets in configs/episodes/
agentbench episode show episode-01               # rendered plan: combos, levels, gates, est. time
agentbench episode run episode-01 --combo ...    # resolve preset -> run config -> bench
agentbench episode run episode-02                # matrix: runs each combo, counterbalanced
agentbench episode report episode-01 <run-a> <run-b>   # compare + publication projection
```

 `episode run` is a thin resolver: preset -> concrete run config(s) -> the
 existing `bench`/`run` code paths. No benchmarking logic is duplicated;
 the preset only *declares* the run. `episode show` prints the exact
 commands that would run (dry-run by default), which doubles as the
 approval artifact before any paid resource is created.

## 7. Mapping results back to Token by Token

 AgentBench run outputs (private, full-fidelity): `calibration.json`,
 `pptg*.csv`, `sweep.csv`, `levels.csv`, `agents/levels.csv`, `soak.csv`,
 `verdict`, per-run `metrics/` export, `coherence.json`, `smoke/`.

 Token by Token publication (public, sanitized) consumes an aggregate
 projection: per (model, engine, GPU, load) cells with p50/p90 metrics,
 declared gates and their outcome, and an explicit "tested loads only"
 boundary — the shape of `dashboard/src/data/site-v2/episode-1*.json` and
 `data/public/episode-1-public.v1.json`.

 The projection is a new small script in the Token by Token repo
 (`scripts/project_agentbench_results.py`, planned) that:

 1. Takes one or more AgentBench run directories as input (private machine).
 2. Selects only allowlisted aggregate fields (no request payloads, no
    client identities, no endpoints, no flags beyond the declared
    comparison variables, no image digests of private images).
 3. Writes the site-v2 JSON shape + the public manifest entry.
 4. Then the existing publication pipeline runs unchanged:
    `check_publication_privacy.py` over the output, acceptance tests,
    commit.

 Boundary: AgentBench results are raw evidence, never directly published.
 Only the sanitized projection enters the public repository, and only
 through the existing privacy check.

## 8. Repository and privacy boundary

- AgentBench is **private** and intentionally commits credentials; nothing
  from it (config values, results, dashboards, code) may be copied into the
  public Token by Token repository.
- This plan document is the only artifact that crosses; it stays at the
  capability/CLI level.
- Combo files referencing `${VLLM_API_KEY}` stay in AgentBench.
- Episode presets that encode *publicly described* launch variables
  (TP size, KV dtype, speculative on/off) may be mirrored as documentation
  in Token by Token episode READMEs after the run is published.

## 9. Implementation phases

 **Phase 1 — Presets without new code (week-scale).**
 Author `configs/episodes/episode-00..01,11,14,15.yaml` as plain run
 configs with the `episode:` block (ignored by the current loader, enforced
 later). Verify each with `agentbench episode show`-equivalent dry runs
 (manually: `agentbench run --run-config ... --dry-run` if available, else
 `agentbench bench ... --help` cross-check). No GPU spend beyond
 re-verification runs the owner approves.

 **Phase 2 — Resolver + schema (AgentBench code change).**
 Add `agentbench/episodes.py` (load/validate/render presets), wire
 `agentbench episode list|show|run|report` in `cli.py`, add the
 `episode:` schema to `schemas.py`, extend `config.py` loading. Cover with
 pytest (preset validation, counterbalanced order determinism, gate
 rendering) — the repo's 370+ test suite is the bar.

 **Phase 3 — Matrix + campaign.**
 `combos:` matrix execution with recorded counterbalance order; campaign
 cost accounting per episode; guard/hold for long soaks (reusing
 `deploy/k8s/` scripts where the campaign runs on k8s).

 **Phase 4 — Publication projection (Token by Token code change).**
 `scripts/project_agentbench_results.py` + privacy-check integration +
 acceptance test that a projected bundle passes
 `check_publication_privacy.py`.

 **Phase 5 — Gap episodes.**
 E08 (multi-node launch helper), E09 (PD-disagg flags + router in combo),
 E12 (adapter/LoRA combos), E16 (release manifest + reliability drill
 automation). Each is a standalone PR in AgentBench with its own tests.

## 10. Open questions

- Which model/GPU is the Episode 01–15 anchor for the first paid
  re-verification? (Qwen3.8-27B-FP8 on H200 matches the recorded study and
  the existing combos; a different anchor changes the combo set.)
- Do matrix episodes re-run the full pipeline per combo, or share
  calibrate/PP-TG across combos of the same engine? (Cheaper, but the
  calibrate cross-check is engine-specific.)
- Where do episode result directories live long-term (AgentBench `results/`
  per today, or object storage with lifecycle rules)?
- Should the `episode:` block instead live in the Token by Token repo as
  the source of truth, with AgentBench only consuming run configs? (Keeps
  the public catalog authoritative; costs a sync step.)
- E13 decision-task set: who labels, and what is the acceptance threshold
  before it is frozen as a workload?