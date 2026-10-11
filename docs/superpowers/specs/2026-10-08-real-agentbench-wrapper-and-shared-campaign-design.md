# Real AgentBench Wrapper and Shared Episode Campaign Design

**Status:** Revised written specification for owner review
**Date:** 2026-10-08  
**Repositories:** public `token-by-token`; private AgentBench  
**Supersedes:** the synthetic-first delivery order in `2026-10-08-public-cli-offline-selftest.md`  
**Does not authorize:** deployment, provider spend, benchmark execution, publication, release, or deletion

## Purpose

Token by Token is the public learning and hands-on product. Its normal run path must
invoke the real private AgentBench harness and return actual measurements. The public
client must not reimplement the benchmark, fabricate benchmark measurements, expose
unrestricted harness controls, or contain private profiles, deployment recipes,
corpus implementation, credentials, prompts, raw evidence, or provider identifiers.

The existing deterministic self-test remains useful only as an installation diagnostic:

```text
token-by-token doctor --offline
```

It is not a product result and must not appear as recorded benchmark evidence.

## Curriculum decision: fourteen episodes, with Episode 00 unchanged

The public curriculum uses `episode-catalog.v3` and contains fourteen numbered
episodes, 00 through 13. Episode 00 is not renamed, rewritten, renumbered, or folded
into another episode. Its current title, visual identity, historical study, evidence
IDs, URLs, and limitations remain unchanged.

The remaining episodes use short, question-led names that describe a substantial
experimental subject. Small runtime switches are chapters inside a controlled episode,
not standalone episodes.

| Episode | Public topic name | Scope |
|---|---|---|
| **00** | **Warm-up** | Existing Episode 00, unchanged. |
| **01** | **Where does the serving ceiling begin?** | Matched service-attested baselines, equal-work comparisons, load curves, saturation, SLO-qualified goodput and cost. |
| **02** | **When is a model actually ready?** | Artifact acquisition, process start, model loading, compilation or graph capture, health, first valid generation, warmup and sustained readiness. |
| **03** | **Which serving controls really move the needle?** | Prefix caching, chunked prefill, admission limits, batching and scheduler controls, mixed traffic, selected interactions and a tested combined candidate. |
| **04** | **Can extra compute make decoding faster?** | Target-only versus supported speculative decoding, acceptance, correctness, memory overhead, load sensitivity and cost. |
| **05** | **Does constrained output preserve useful answers?** | Prompt-only structure versus constrained generation, schema validity, semantic quality, retries and latency. |
| **06** | **What fits—and what performs—on this GPU?** | Model and GPU fit, weight and KV precision, verified attention/kernel choices, quality, memory and economics. |
| **07** | **When does one node need more than one GPU?** | Replicas versus TP, with PP or EP only where model fit or architecture justifies them. |
| **08** | **When does scaling cross the network?** | Cross-node replicas and supported TP/PP/EP layouts, topology, communication, efficiency, tails, failures and cost. |
| **09** | **Should prefill and decode live apart?** | Colocated versus disaggregated serving plus queue-, cache- and prompt-length-aware routing. |
| **10** | **Can the service scale without losing control?** | Slurm and Kubernetes roles, autoscaling, overload containment, scaling incidents and operational cost. |
| **11** | **What changes when we adapt the model?** | Inspectable model internals followed by LoRA/QLoRA adaptation, held-out quality, memory, lineage and serving cost. |
| **12** | **Can a typed system make better decisions?** | SYSTEM 1 and selected LLM approaches on the same labeled classification, routing or scoring contracts. |
| **13** | **Would you trust this configuration in production?** | Reproducible packaging, accelerator preflight, memory containment, release gates, rollback, recovery and capstone synthesis. |

This naming is curiosity-led, not clickbait: recorded pages may use a factual measured
question as their hero, while planned pages use the topic question above and never imply
a result that has not been measured.

### Complete `episode-catalog.v2` to `v3` mapping

| Current episode | `v3` destination |
|---|---|
| 00 — Warm-up | 00 unchanged |
| 01 — Measure what matters | 01, retained as a historical study |
| 02 — Equal-work runtime baseline | 01 |
| 03 — Prefix reuse | 03 |
| 04 — Batching, scheduling and mixed traffic | 03 |
| 05 — Attention kernels and precision | 06 |
| 06 — Speculative decoding and structured outputs | 04 and 05 |
| 07 — Parallelism within one node | 07 |
| 08 — Parallelism across nodes | 08 |
| 09 — Prefill/decode disaggregation and cache-aware routing | 09 |
| 10 — Slurm and Kubernetes orchestration | 10 |
| 11 — Model internals: weights to optimization | 11 |
| 12 — LoRA and QLoRA with held-out evaluation | 11 |
| 13 — SYSTEM 1 and LLMs on labeled decision tasks | 12 |
| 14 — Packaging, accelerator preflight and memory containment | 02 and 13 |
| 15 — Saturation, SLO and cost | 01 and 10; cost also appears throughout |
| 16 — Release gates, recovery and capstone synthesis | 13 |

Historical records always retain their original catalog version, episode number, study
and run IDs, evidence hashes, and URL aliases. The website may associate them with a
new teaching view but must not rewrite their identity.

## Evidence review and Episode 01 decision

The retained H200 study is not a clean engine-default comparison. It used
Qwen3.8-27B-FP8 with FP8 KV cache, prefix caching, parser settings, SGLang cookbook
settings, and a separate SGLang MTP/speculative-decoding arm. Relevant manifests also
retain unverified hardware/image provenance states. The public Episode 01 data already
describes the accepted vLLM/SGLang evidence as a recorded deployment comparison rather
than an engine-only causal claim.

Therefore:

1. Preserve the current Episode 01 study as historical deployment evidence.
2. Do not relabel it as defaults or retroactively upgrade its provenance.
3. Exclude the historical MTP arm from a baseline engine comparison.
4. Run one new versioned H200 campaign using vLLM and SGLang **service-attested
   baselines**. This wording is deliberate: exact upstream defaults are not comparable
   when minimum model, API, parser, observability, and compatibility settings differ.
5. Use that one campaign for two predeclared educational analyses:
   - Episode 01 presents the complete paired equal-work comparison and explains how
     TTFT, TPOT, end-to-end latency, throughput, queue/cache, errors, SLO-qualified
     goodput and cost change across selected load cells.
   - Episode 02 presents separately instrumented startup and readiness phases for the
     same pinned deployments. Repeated startup conditions are additional runs, not
     inferred from steady-state measurements.

These are two views of overlapping measurements, not independent experiments or a
replication. Both views retain the same campaign, run, cell, and evidence identities.

## System boundary

```text
Public Token by Token CLI
  -> authenticated episode API
  -> signed public manifest + validated user choices
  -> private immutable plan + per-action approval
  -> signed private AgentBench worker
  -> existing real AgentBench orchestration and HTTP streaming path
  -> private raw results, telemetry, logs, prompts, billing evidence
  -> qualification + positive-allowlist sanitizer
  -> signed sanitized evidence bundle
       -> isolated local VictoriaMetrics/Grafana replay
       -> reviewed static JSON for the Token by Token website
```

The first release keeps the AgentBench worker on controlled infrastructure. Packaging
it as a signed private executable or OCI image creates a reproducible execution unit;
signing does not hide its contents. A customer-installed proprietary binary is a later
commercial option because recipients can inspect Python bytecode and observe requests
sent to their endpoint.

## Public CLI

The intended user flow is:

```text
token-by-token episodes
token-by-token episode 1 describe
token-by-token capabilities --episode 1

token-by-token episode 1 plan \
  --model qwen38-27b-fp8 \
  --gpu h200-141gb \
  --load-profile standard \
  --max-quote-usd 25

token-by-token episode 1 run --plan PLAN_ID
token-by-token runs status RUN_ID
token-by-token runs stop RUN_ID
token-by-token runs collect RUN_ID --output RUN.tbt.zip

token-by-token evidence verify RUN.tbt.zip
token-by-token dashboard up RUN.tbt.zip
token-by-token dashboard open RUN.tbt.zip
token-by-token dashboard stop RUN.tbt.zip

token-by-token doctor --offline
```

The public controls are aliases resolved by signed capability manifests. Model and GPU
are not independent free-form allowlists: the service validates an approved combination
of episode, protocol, immutable model revision, precision, GPU SKU/count, runtime arms,
and load profile. It rejects unavailable combinations without substitution. Changing
model, GPU, runtime, protocol, or load scope invalidates the quote and requires a new
plan.

Initially allowed run controls are:

- episode and supported protocol revision;
- approved model alias;
- approved GPU alias;
- approved load profile or declared users from the manifest;
- optional maximum acceptable quote;
- output/format controls that cannot affect execution.

Do not expose arbitrary endpoints, model IDs, GPU strings, profile/config paths,
images, corpus paths, plugins, engine arguments, environment overrides, shell input,
skip-gate switches, or speculative-token counts. Speculative decoding belongs to its
own versioned episode/variant.

## Public and private contracts

| Contract | Visibility | Responsibility |
|---|---|---|
| `episode-manifest.v2` | Public | Episode identity, protocol, approved model/GPU/load combinations, metrics, availability, limitations, public digest. |
| `episode-request.v1` | Public request | Manifest digest, episode/protocol, approved aliases, request identity. |
| `public-plan.v1` | Authenticated user | Opaque plan ID, resolved public scope, quote and basis, expiry, required actions, signature. |
| `execution-plan.v1` | Private | Exact profiles, artifacts, runtime settings, phases, provider target, approval receipts, limits and cost guards. |
| `run-events.v1` | Sanitized progress | Opaque run ID, sequence, bounded phase/progress values, typed errors and terminal state. |
| `run-replay.v2` | Authenticated user | Sanitized measurements, telemetry, qualification, coverage, cost, provenance and signed inventory. |
| `public-evidence.v2` | Public site | Publication-reviewed aggregates and chart samples only. |

All schemas reject unknown fields and versions. The service enforces the allowlist;
trusting a modifiable public client is insufficient. Mutations use principal-bound
idempotency keys so retries cannot start duplicate work.

## Private AgentBench worker

AgentBench owns a narrow worker entry point:

```text
agentbench-worker capabilities --json
agentbench-worker validate --request -
agentbench-worker execute --request - --events-jsonl
```

Requests arrive via stdin or a private service queue and reference an immutable private
plan plus an authorized action. Credentials and signing keys never enter argv, public
JSON, or downloadable artifacts. Stdout is reserved for bounded versioned NDJSON;
detailed diagnostics remain private.

The worker calls the real orchestration extracted from the existing `agentbench bench`
pipeline: preflight, coherence, smoke, calibration, recorded-session replay, warmup,
measurement, reporting, and telemetry export. It must add common cancellation,
deadlines, request/token/concurrency limits, partial-evidence preservation, and stable
phase manifests across every stage. A deterministic loopback endpoint proves this real
coordinator/worker/HTTP path without pretending to be a GPU result.

## Shared H200 campaign for Episodes 01 and 02

The proposed initial combination is one H200 141 GB and the pinned
Qwen3.8-27B-FP8 family already represented in the retained report. The exact revision,
runtime versions, images, driver/CUDA compatibility, availability, price, and protocol
must be revalidated and bound into an executable plan before approval.

Campaign requirements:

- vLLM and SGLang only; no MTP/speculative decoding arm;
- sequential arms on the same acquired H200 when operationally valid;
- counterbalanced arm order across repeated pairs;
- fixed model revision, precision, tokenizer/template, workload eligibility, seeds,
  output policy, cache-state policy, warmup, measurement windows and qualification;
- effective settings and every scientifically material override retained privately;
- requested and delivered output distributions, stop reasons, errors and coverage
  checked before comparisons;
- Episode 01 baseline/capacity analysis and Episode 02 startup/readiness analysis frozen
  before execution;
- any Episode 01-only instrumentation intervention recorded as a separate phase with
  incremental cost.

Episode 02 distinguishes three conditions: fully cold artifacts, cached-artifact
process restart, and an already warm service. It records allocation, artifact
availability, process start, model load, compilation or graph capture, health response,
first valid generation and predeclared sustained readiness as separate timestamps.
AgentBench's request-level `cold` cache namespace is not a substitute for any of these
conditions and is not evidence that engine caching was disabled.

The observation that SGLang appeared to become ready sooner is a hypothesis for this
campaign. Publication must not attribute it to Rust or any implementation language
without evidence controlling artifact location, downloads, host caches, loading
strategy, compilation and readiness definitions.

The execution plan must explicitly state that one campaign supplies both episode views.
Opening or collecting either view reuses the campaign; it must not silently submit a
second paid run.

## Serving-control and speculation campaigns

Episode 03 uses each engine's frozen Episode 01 baseline as its reference. Every arm
follows baseline -> one supported control change -> baseline recheck, with
counterbalanced order at approved load levels. Within-engine effects are interpreted
before complete configurations are compared across engines. A final combined candidate
is tested only after individual controls and selected interactions are understood.

Prefix caching, chunked prefill, admission limits and scheduler controls remain chapters
of one campaign. The product never calls a control equivalent across engines merely
because a public alias maps to both. In particular, it does not claim "batching off"
unless the pinned engine exposes a meaningful supported mode.

Episode 04 is a separate target-only versus speculation campaign. Every exact
engine/model/GPU/proposal combination must pass capability and correctness validation;
an unsupported arm is unavailable rather than substituted. Episode 05 keeps structured
generation separate from speculation and applies the common output-quality contract.

## Evidence, replay and static publication

AgentBench retains raw request records, prompts/outputs, profiles, manifests, logs,
original telemetry, provider identifiers and billing evidence. A positive-allowlist
sanitizer emits only approved aggregates, series, coverage and reason codes. It removes
endpoints, account/resource IDs, host labels, private profile names, private settings,
text payloads, traces and internal paths.

The signed sanitized bundle is the only source for both local replay and public static
projection. Local replay imports sanitized samples into a fresh isolated
VictoriaMetrics instance and exposes loopback Grafana through read-only access. The
static site embeds reviewed JSON and has no runtime dependency on AgentBench,
VictoriaMetrics, Grafana, provider services, or raw `.gz` archives.

## Cost evidence and comparison

Use one campaign cost ledger with unique charge/allocation identities. Attribute
exclusive phases directly and keep shared acquisition, setup, switching, collection,
and overlapping measurement costs in a shared pool. Reusing measurements adds no
second execution charge, but neither episode is described as costing zero.

Keep these states separate:

- quoted maximum and basis;
- accrued provider charge;
- reconciled charge;
- measured versus estimated phase allocation;
- billing lag, coverage and unavailable reasons.

The dashboard supports selecting at most three episode views. It sums distinct ledger
entries, never episode-card totals. Shared evidence is visibly badged and observations
are deduplicated in pooled displays.

Cost views include campaign/phase spend, cost per valid request, cost per one million
delivered output tokens, and cost per qualified concurrent-user-hour. Cost per completed
task remains unavailable until independent task grading exists.

## Three-episode comparison gates

Up to three episode views may be displayed side by side. Ranking, percentage deltas,
and winner colors require compatibility in metric definition, workload, model and
precision, hardware, cache/speculation settings, load, measurement window,
qualification, provenance, billing basis, allocation scope, currency and denominator.

An explicitly controlled experimental variable may differ. Other mismatches render the
view as **Context only** with reasons, without winner colors or causal language. Three
episode views may contain only one independent campaign; the UI must say so.

## Safety and paid execution

Planning, quoting, provisioning, execution, retry/extension, and deletion are distinct
actions. A plan or quote does not authorize spend. Before any real RunPod resource is
created, the workflow must compile a current immutable plan using provider-owned price,
stock, balance, ancillary-cost, region and guard observations and present its digest and
complete maximum cost envelope. Execution requires the exact approval phrase produced
for that still-current plan.

No approval is reusable after a material change. Failure stops new traffic, preserves
evidence, and reports continuing billing. Provider-resource cleanup follows the private
repository guardrail and requires its applicable explicit authorization and verified
absence evidence.

## Delivery phases and exit criteria

1. **Boundary and contracts:** approve this design, update the existing proposal,
   define public/private schemas, classify protected assets, and inventory legacy public
   orchestration. No execution is authorized.
2. **Real harness adapter:** extract shared AgentBench orchestration, build the constrained
   worker, and connect public planning/progress transport. Exit: a public request reaches
   real AgentBench coordinator/worker/HTTP streaming through a loopback target.
3. **Evidence path:** implement scoped sanitization, signatures, v2 verification, local
   replay and static projection. Exit: hostile-artifact and round-trip tests pass.
4. **Controlled integration:** deploy an authenticated operator-mediated development
   service without paid execution. Exit: authorization, idempotency, cancellation,
   recovery and cross-user tests pass.
5. **Compiled H200 campaign plan:** freeze both analysis plans, obtain fresh provider
   observations, compile cost/guard envelope, and stop for exact owner approval.
6. **Real shared campaign:** after exact approvals only, execute the H200 paired campaign,
   collect evidence, reconcile cost, sanitize, and verify both episode views.
7. **Curriculum and product UI:** publish `episode-catalog.v3`, preserve Episode 00 and
   all historical aliases, add model/GPU capabilities, dashboard replay, three-episode
   comparison, cost analysis, and shared-evidence badges.
8. **Release:** complete signing, SBOM, licensing/brand review, public documentation,
   staging/production verification and publication approval.

## Verification requirements

- Actual AgentBench coordinator, worker, and HTTP streaming through a loopback target.
- Closed contract/allowlist tests for model/GPU/protocol combinations.
- Expired/tampered plans, duplicate requests, unauthorized access and cross-user access.
- Cancellation/deadline behavior and partial-evidence preservation in every phase.
- Canary-secret leakage checks across events, errors, archives, metrics and static assets.
- Signature, archive, mixed-run and replay-version hostile tests.
- VictoriaMetrics import/export round trip, duplicate import and old timestamp tests.
- Dashboard arithmetic, cost-state and three-episode compatibility tests.
- Separately approved real-target reconciliation between private records and public bundle.
- Public CI never receives private source, profiles, corpus implementation or credentials.

## Owner decisions still required

Before implementation: approve this written design and the initial public branding text.
Before execution: approve exact model revision, H200 offer/region, runtime versions,
service-attested baseline settings, workload rights, analysis cells, repetitions, cost
envelope, provider actions and cleanup policy. Before release: approve licensing,
commercial entitlement, retention, failed-run charges, support ownership, publication
rights, and any later customer-installed AgentBench binary.
