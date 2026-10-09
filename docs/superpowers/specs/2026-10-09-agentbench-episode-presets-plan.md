 # Token by Token episodes as AgentBench presets — assessment and design

 Status: plan (not implemented). Date: 2026-10-09. Revised 2026-10-09:
 orchestration lives in the Token by Token operator wrapper; AgentBench is
 the private measurement engine.
 This document lives in the public repository by design; it references the
 private AgentBench codebase only at the capability/CLI level and contains no
 credentials, internal URLs, or private data.

 ## 1. Purpose

 Assess every Token by Token episode (00–16, `episode-catalog.v2`) against
 what AgentBench can already do, and define how the Token by Token operator
 wrapper drives each episode end-to-end. The wrapper performs exactly two
 jobs:

 1. **Deploy and configure** any GPU-based VM, bare-metal host, or
    container: provision the machine, install and launch vLLM and/or SGLang
    with the episode's specific parameters, and attest that the running
    engine is exactly what the episode declared.
 2. **Benchmark and publish** with AgentBench: point the AgentBench tool at
    the configured engine, run the episode's benchmark contract, and publish
    only the sanitized result through the existing publication pipeline.

 AgentBench is deliberately not the orchestrator: it stays the private
 measurement engine (phases, gates, corpora, telemetry). Everything the
 wrapper does in this plan is public code in the Token by Token repository.

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

 Each preset is a YAML file under the episode's public directory in Token by
 Token (`episodes/NN-<slug>/preset.yaml`), referencing AgentBench
 combos/workloads plus an `episode:` block (schema in §5). The wrapper
 renders it into a concrete AgentBench run config at execution time.
 Sketches show the discriminating fields only.

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

 ## 5. Episode preset schema (public)

 Host: `episodes/NN-<slug>/preset.yaml` in Token by Token — public,
 committed, reviewed in the same PR as the episode content. It is a run
 config (everything `agentbench run --run-config` already understands) plus
 an `episode:` block:

 ```yaml
 # episodes/01-measure-what-matters/preset.yaml
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

 Validation rules (enforced by the wrapper's preset validator — public code,
 run before any resource is created; AgentBench re-validates the rendered
 run config):

- `episode.id` 0–16, `slug` matches the catalog entry.
- `publication: token-by-token` requires `evidence_contract.performance`
  and, when the episode contract demands it, a quality gate.
- `combos:` + `matrix.counterbalance` require `seed` to be set.
- `duration` is required for E15/E16 presets.

 ## 6. The wrapper: the two jobs

 The repository already contains a hardened operator toolchain
 (`src/runpod_benchmark/`, ~30 modules, built for Episode 1). The episode
 series wrapper is a parameterization of that toolchain, not a new one.

 ### 6.1 What the wrapper already has

 | Capability | Module(s) | Status for the series |
 |---|---|---|
 | RunPod provisioning, ownership journal, deletion authority, cleanup observation | `runpod_v2.py`, `episode1_runpod_adapter.py`, `bounded_runpod_transport.py` | reusable; allocation facts generalized per episode |
 | Bounded SSH executor (argv vectors, POSIX quoting, strict file modes, no resource creation) | `episode1_remote.py` | reusable as-is for bare metal and RunPod |
 | Remote runtime control: fixed helper, closed JSON schemas, GPU attestation (uuid/driver/boot_id/CUDA/memory), clock sync, GPU process ownership | `episode1_runtime_control.py`, `gpu_process_ownership.py` | reusable; **launch argv is frozen to two runtimes — parameterize** |
 | Lifecycle orchestration, guard, supervisor, watchdogs | `episode1_orchestrator.py`, `episode1_guard.py`, `pod_supervisor.py`, `scripts/*watchdog*.py` | reusable with per-episode budgets |
 | Private evidence capture (billing, ownership tokens) | `episode1_capture.py`, `episode1_provider_failure_capture.py` | reusable |
 | Promotion gate (pure, fail-closed, recomputes hashes/chain, `seal()`) | `episode1_promotion.py` | Episode-1-schema-specific; **new sibling gate for AgentBench runs** |
 | Publication privacy + acceptance | `scripts/check_publication_privacy.py`, dashboard acceptance tests | reusable unchanged |

 ### 6.2 Job 1 — deploy and configure

 For each episode preset, the wrapper:

 1. **Provisions** the environment through one of three adapters, all
    behind the same allocation interface:
    - **RunPod VM** — existing adapter; today's digest-pinned prebuilt
      image (Episode 1 model) or a base CUDA image with in-place install
      for parameterized episodes.
    - **Bare-metal** — the SSH executor is already host-agnostic; the
      operator preflight (`docs/episode-1-preparation/operator-preflight.md`)
      applies unchanged.
    - **Container / k8s** — new adapter; the deployment plan
      (`2026-10-09-docker-k8s-helm-deployment-plan.md`) defines the chart;
      the wrapper drives `helm`/`kubectl`, or runs inside the pod.
 2. **Installs and configures the engine** with the episode's parameters by
    delegating to AgentBench's `tools/deploy_inference.py` — a
    self-contained stdlib file copied to the host (private tooling; it is
    never committed to this repository). The wrapper renders the preset
    into the deploy tool's non-interactive `answers.json` (model +
    revision, engine + version, GPU class, TP size, KV dtype, memory
    fraction, launch flags) and runs `serve --answers <file> --yes`. The
    deploy tool handles the hard parts: `uv` venvs, torch/CUDA repair with
    a compiled probe, version-agnostic flag resolution against the
    engine's own `--help`, model-aware planning, launch, `/health` wait, a
    real 512-token generation check, the GPU exporter — and writing the
    AgentBench **combo YAML** that Job 2 consumes.
    - Prebuilt-image episodes (e.g. 14, packaging) skip the in-place
      install and launch from the digest-pinned image; the launch argv is
      still rendered from the preset.
 3. **Attests** the running engine: the existing attestation layer, with
    the frozen `_expected_argv` replaced by the preset-rendered argv
    (same closed JSON schemas, same GPU-process-ownership and watchdog
    hardening). A mismatch between preset-declared parameters and the
    observed process fails the run before any benchmarking.

 ### 6.3 Job 2 — benchmark and publish

 1. The wrapper renders the preset into an AgentBench **run config** (mode,
    combo, workload, profile, levels, targets, gates, seed) and invokes the
    private AgentBench CLI from the operator workstation (or the host),
    pointed at the attested endpoint through the existing tunnel code.
 2. AgentBench produces the run directory (raw, private): verdict,
    levels.csv, PP/TG, agent sessions, soak, metrics export.
 3. A new **pure promotion gate** (sibling of `episode1_promotion.py`, same
    style: no I/O, recomputes digests, trusts no producer booleans) consumes
    the run directory and emits the sanitized site-v2 aggregate.
 4. The existing publication pipeline takes over unchanged:
    `check_publication_privacy.py` over the output, dashboard build, v2
    browser acceptance, commit.

 ### 6.4 Invocation

 ```
 python scripts/run_episode.py --preset episodes/01-.../preset.yaml plan
 python scripts/run_episode.py --preset ... --env runpod deploy   # job 1
 python scripts/run_episode.py --preset ... bench                 # job 2
 python scripts/run_episode.py --preset ... all                   # both
 ```

 `plan` (dry-run, the default) prints the exact answers.json, launch argv,
 and AgentBench run config that would be used — the approval artifact
 before any paid resource is created. The entry point follows the existing
 `scripts/` operator convention; library code lands in
 `src/runpod_benchmark/`.

## 7. Mapping results back to Token by Token

 AgentBench run outputs (private, full-fidelity): `calibration.json`,
 `pptg*.csv`, `sweep.csv`, `levels.csv`, `agents/levels.csv`, `soak.csv`,
 `verdict`, per-run `metrics/` export, `coherence.json`, `smoke/`.

 Token by Token publication (public, sanitized) consumes an aggregate
 projection: per (model, engine, GPU, load) cells with p50/p90 metrics,
 declared gates and their outcome, and an explicit "tested loads only"
 boundary — the shape of `dashboard/src/data/site-v2/episode-1*.json` and
 `data/public/episode-1-public.v1.json`.

 The projection is the new pure promotion gate from §6.3 (sibling of
 `episode1_promotion.py`: no I/O, fail-closed, recomputes digests) that:

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

 **Phase 1 — Public presets + validator (Token by Token).**
 Author `episodes/NN-<slug>/preset.yaml` for E00/E01 (E11/E14/E15 next),
 plus the wrapper preset validator and `plan` dry-run renderer
 (answers.json + launch argv + run config). No GPU spend; full pytest
 coverage of the renderers (deterministic, fail-closed).

 **Phase 2 — Parameterized deploy (Job 1, Token by Token).**
 Replace the frozen `_expected_argv` with preset-rendered argv in the
 runtime-control layer (closed schemas unchanged); wire the bare-metal
 adapter (SSH preflight path); delegate engine install to
 `deploy_inference.py` via rendered `answers.json`. Verify on a local GPU
 or one short approved RunPod run for E00.

 **Phase 3 — Benchmark + promotion (Job 2).**
 AgentBench invocation against the attested endpoint through the tunnel;
 the new pure promotion gate for AgentBench run directories; integration
 with `check_publication_privacy.py` + acceptance tests; one full E01
 run-to-publication as the integration test.

 **Phase 4 — Container/k8s adapter + matrix.**
 The third environment adapter behind the deployment plan's chart;
 counterbalanced `combos:` matrix execution with recorded order; campaign
 cost accounting per episode; guard/hold for long soaks (reusing
 AgentBench `deploy/k8s/` scripts where the campaign runs on k8s).

 **Phase 5 — Gap episodes (AgentBench code changes).**
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
 - E13 decision-task set: who labels, and what is the acceptance threshold
  before it is frozen as a workload?