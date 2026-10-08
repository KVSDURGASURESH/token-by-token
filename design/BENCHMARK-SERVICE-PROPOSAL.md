# Benchmark service integration proposal

Status: **public-client/private-service boundary approved on 2026-10-08**. This
document is an architecture decision, not an implemented or production-authorized
service. No paid Episode 02 run is authorized by it.

## Decision summary

Publish a small `token-by-token` client and keep the proprietary benchmark engine
behind an authenticated hosted service. The public package may contain the client,
schemas, synthetic examples, an offline self-test and the local evidence viewer. It
must not contain the private engine binary, deployment recipes, corpus payloads,
credentials, raw operational exports or unrestricted engine flags.

| Option | Decision | Reason |
|---|---|---|
| Public client → hosted benchmark service | Recommended first release | Strongest practical boundary for private implementation and centrally enforceable authorization, metering and evidence production |
| Public client → separately licensed local binary | Consider later for enterprise use | Supports offline/customer-controlled infrastructure, but expands licensing, support and reverse-engineering risk |
| Embed the proprietary binary in the public client | Reject | A compiled bundle is still distributable and inspectable; secrets and private recipes cannot be protected this way |

The client may still be distributed as a convenient signed binary. That binary
contains only the public client implementation.

## Product boundary

```text
Public CLI
  → authenticated control plane
  → immutable plan and per-action approvals
  → private benchmark workers
  → private raw evidence
  → qualification and sanitization
  → signed replay bundle
       ↘ local Grafana/VictoriaMetrics replay
       ↘ deterministic static evidence build
          → publication review
          → public Token-by-Token site
```

The hosted boundary protects implementation, recipes and raw data from routine
distribution. It cannot promise that users will never infer behavior from results or
redistribute artifacts they are entitled to download.

## Proposed public CLI

These are proposed interfaces, not commands that exist today:

```text
token-by-token auth login
token-by-token episode 2 describe
token-by-token episode 2 plan --protocol episode-02-v1
token-by-token episode 2 selftest --offline

token-by-token runs submit --plan PLAN_ID
token-by-token runs status RUN_ID
token-by-token runs stop RUN_ID
token-by-token runs collect RUN_ID

token-by-token results download RUN_ID --format replay --out ./run
token-by-token evidence verify ./run
token-by-token observability import ./run/metrics.native.gz --manifest ./run/bundle.json
token-by-token observability up --run ./run --offline
token-by-token observability open --run ./run
token-by-token evidence export ./run --format static --out ./site-bundle
token-by-token observability stop --run ./run
token-by-token observability purge --run ./run
```

- `describe` explains the question, fixed protocol, permitted controls, limitations
  and availability.
- `plan` validates inputs and returns a quote without allocating resources or issuing
  inference requests.
- `submit` requests execution of that exact immutable plan. Any cost-bearing action
  remains blocked until separately approved.
- `stop` stops workload traffic and preserves evidence. It reports whether resources
  may still be billable.
- `collect` verifies retained evidence and never deletes resources.
- `export` creates a local review artifact; it does not publish.
- `observability stop` preserves storage. `purge` is separately destructive and
  requires confirmation.
- `--offline` forbids network access and fails clearly when dependencies are absent.

Episode controls come from signed allowlists. The public adapter never forwards
arbitrary endpoints, configuration files, container images, shell fragments, corpus
paths, plugins, private engine arguments or skip-gate switches.

The suggested command

```text
<private-engine> --client token-by-token --episode 2 --speculative-drafts 4
```

is intentionally not the public contract. Speculative decoding changes deployment
and memory planning; it is not a client workload toggle. Episode 02 excludes it. A
future optimization episode may expose a reviewed named variant through a new signed
manifest, quote and approval, without revealing the underlying private recipe.

## Contracts and trust

Use four contracts with different audiences:

| Contract | Visibility | Purpose |
|---|---|---|
| `episode-manifest.v1` | Public | Protocol revision, scientific controls, allowed parameters, metrics, qualification rules and workload summary |
| `execution-plan.v1` | Private service | Exact artifacts, effective configuration, schedule, infrastructure actions, cost ceiling and approval receipts |
| `run-replay.v1` | Authenticated user | Sanitized metrics, gate outcomes, coverage, timestamps, compatibility, hashes and signatures |
| `public-evidence.v2` | Public static site | Approved aggregates and samples, methodology, limitations, provenance state, cost basis and release identity |

All contracts reject unknown fields and unsupported versions. Sign canonical manifest
bytes and inventories containing each artifact's path, size, media type and SHA-256.
A signature proves issuer and integrity; it does not prove scientific validity,
hardware identity or publication approval. Those states remain separate.

Missing readings are `null` with reason and coverage, never zero. Interrupted, failed
and invalid cells remain visible with structured reasons. Public evidence uses a
digest of the public protocol; private configuration fingerprints stay private.

## Authentication and isolation

- Use browser-based OAuth with PKCE for the public client, short-lived scoped tokens
  and OS keychain storage. Never embed a client secret in a distributed binary.
- Keep provider credentials server-side and scoped by worker role.
- Do not initially accept arbitrary customer endpoints or uploads.
- Derive tenant identity from authenticated claims, never a caller-supplied label.
- Enforce server-side concurrency, request, resource and plan-expiration limits.
- Require idempotency keys for mutations so retries cannot start duplicate work.
- Authorize artifact access independently of possession of a run identifier.
- Return typed public progress and errors, not raw private logs or exceptions.
- Distribute signed client releases, dependency locks, SBOMs and replay image digests.

## Episode 02 protocol draft

Proposed question:

> What do matched vLLM and SGLang deployments deliver under the same declared
> default-configuration protocol?

“Default” means the effective defaults of frozen upstream releases plus only the
minimum compatibility settings required for the same model and API contract. It does
not mean using a private deployment wizard's tuned defaults. If the material
differences cannot be disclosed safely, replace “default” with “service-attested
baseline.”

| Control | Proposed Episode 02 rule |
|---|---|
| Arms | vLLM and SGLang only |
| Model | Same approved checkpoint, precision, tokenizer and chat template |
| Workload | Same approved corpus revision, eligibility rules, schedule and paired seeds |
| Output | Same generation policy and precomputed output-budget vector |
| Hardware | Same GPU class/count; use the same physical GPU for paired sequential runs when feasible |
| Client/network | Equivalent placement, transport and client capacity |
| Sessions | Two slots per simulated user; slots are not active requests |
| Load levels | Proposed 2, 4, 8, 12, 16 and 24 users |
| Repetitions | Three paired repetitions with counterbalanced arm order |
| Per-cell time | 120-second warmup and 300-second measurement |
| Minimum observations | At least 50 valid requests per cell |
| Qualification | Declared timing/coverage rules, error rate ≤1%, decode-p10 target ≥20 tokens/s |
| TTFT | Reported; not an acceptance gate without a predeclared threshold |
| Speculation | Excluded |
| Sustained capacity | Requires a separate confirmation plan |

These settings require owner approval. The proposed 36-cell sequential matrix contains
4.2 scheduled GPU-hours before startup, gates, downloads, draining, collection and
idle time. That is a duration estimate, not a price quote or permission to run.

Required gates are: offline preflight, deployment verification, coherence, smoke,
accounting validation and measurement. Recall, long-context and structured tool-call
coherence probes must all be present and passed. Diagnostics must use separately
approved inputs; there is no fallback to private repository material.

Equal prompts and caps do not prove equal delivered work. Publish requested versus
delivered token distributions, stop reasons, truncation, context exclusions and
coverage. Unequal delivery qualifies or suppresses a comparison instead of producing
an unqualified winner. Report paired repeat variability and avoid treating correlated
requests as independent experimental repetitions.

## Cost and destructive-action policy

The private benchmark project requires explicit human approval for every cost-bearing
or destructive action. This proposal preserves that policy:

- Approve acquiring, starting, resizing or extending billable infrastructure.
- Separately approve starting a paid benchmark, retry, repetition or soak.
- Separately approve automation capable of spending or deleting.
- Separately approve resource termination, telemetry deletion or evidence removal.

An approval identifies the action, resource, principal, immutable plan digest, maximum
charge or duration, expiration and consequences. Provisioning approval does not imply
permission to resize, rerun, extend storage or delete resources.

Never auto-terminate after a failure. Stop traffic, preserve and collect evidence,
report continuing billing, and present the next action. This means unattended
self-service with a hard spend cap is not valid until an owner resolves how a cap can
be enforced without an unapproved destructive action.

## $0 offline self-test

`token-by-token episode 2 selftest --offline` uses a local fake engine and synthetic
corpus. It has no provider credentials, remote inference, private repository mount or
provisioning adapter. Phase 1 exercises public-contract validation, deterministic fake
execution, progress, interruption, bundle creation and verification. Local replay,
Grafana/VictoriaMetrics import and static export remain Phase 2 work under separate
plans.

Every artifact is labeled `synthetic_mock`, and schema/build gates reject any attempt
to mix mock artifacts with recorded evidence.

## Local observability and static publication

The local replay package is not the private operational stack:

- Create a fresh volume per signed bundle digest.
- Pin Grafana and VictoriaMetrics images by digest.
- Expose only Grafana on loopback; keep ingestion and administrative endpoints inside
  the local network.
- Put the datasource behind a read-only query gateway.
- Disable anonymous access, editing, external snapshots, plugin installation and
  unnecessary outbound traffic.
- Include no collectors, inference endpoints, cloud credentials, logs or traces.
- Use absolute run timestamps, disabled refresh and idempotent imports.

Sanitize privately by importing into a quarantined pinned VictoriaMetrics instance,
exporting inspectable JSON, applying strict metric/label/value/window allowlists,
re-encoding into a fresh pinned instance, verifying with a second fresh instance and
signing the resulting user bundle. Never sanitize native binary data with string
replacement.

The public website embeds approved static JSON and chart samples. It does not depend
on Grafana, VictoriaMetrics, the hosted service or private endpoints after build time.
The design's “Live dashboard” link stays hidden until a deliberately public sanitized
dashboard is separately approved; it must never target private operational Grafana.

## Workload and metric language

Public methodology must distinguish:

- corpus composition from eligible requests and executed traffic;
- selected sessions from distinct sessions, requests and completed tasks;
- coding/chat domains from the overlapping presence of tool calls;
- recorded gaps from modeled or unknown timing;
- protocol-valid calls from schema-valid or semantically correct calls;
- attempted, valid measured and qualified populations.

Every rate includes its numerator and denominator. Request counts are not described as
human turns or successfully completed tasks. Tool-calling is a cross-cutting property,
not a mutually exclusive workload category. Only publication-reviewed aggregates may
enter public evidence.

## Economics presentation

Artificial Analysis is a presentation reference only; its values and definitions are
not evidence for this project. Use comparable tables, visible assumptions and
performance-versus-cost views while keeping these bases separate:

- reconciled campaign spend;
- attributable run cost;
- dated provider/list-price estimate;
- cost per valid request;
- cost per 1M delivered output tokens;
- cost per qualified concurrent-user-hour;
- energy per 1M output tokens with matching time-window coverage.

“Cost per task” remains unavailable until task completion is independently graded.
Missing cost or telemetry is unavailable, not zero. Qualified-user-hour cost is
unavailable for unqualified runs. Campaign totals keep failed runs, setup, idle and
collection visible even when a narrower ratio excludes them.

## Branding and publication conflict

The current public policy says not to name the private benchmark tool or sponsor. The
new product direction proposes promoting that benchmark service. This is a deliberate policy
change, not a copy edit. Before using the name, logo, “powered by,” contact destination
or affiliation language, obtain approval from the IP/brand owner and update the public
privacy scanner and methodology policy together.

Until then, use neutral wording such as “benchmark service available separately” and
make no affiliation claim.

Legal/commercial approval is also required for public client and evidence licenses,
service terms, corpus derivatives, model/weights/output rights, user-data retention and
regions, local binary licensing, packaged dependencies and comparative claims.

## Phased delivery

| Phase | Deliverable | Exit criterion |
|---|---|---|
| 1 | Public contracts and offline client | Synthetic end-to-end flow passes with no cloud access |
| 2 | Sanitizer and replay package | Real pinned VM round-trip plus isolation and hostile-artifact tests |
| 3 | Private adapter and control plane | Authentication, approval, recovery and audit tests pass |
| 4 | Staging integration | Explicitly approved environment; cost reconciliation and recovery demonstrated |
| 5 | Episode 02 | Frozen protocol, rights clearance and individual action approvals |
| 6 | Publication/release | Evidence, artifact, license and brand reviews complete |

Implementation tests cover authorization bypass, cross-tenant access, unknown
parameters, expired or replayed approvals, duplicate submission, cancellation,
collection failure, stale manifests, tampered signatures and key rotation. Replay
tests cover actual import/export, label collisions, timestamps, archive truncation,
decompression limits, path traversal, mixed-run bundles and blocked write/admin routes.
Static tests cover arithmetic, nulls, cost reconciliation, unequal-work states and
privacy scanning. Existing responsive, theme, keyboard, reduced-motion, enlarged-text
and offline UI checks remain mandatory.

## Decisions required before implementation

1. **Approved 2026-10-08:** hosted service is the first-release boundary.
2. Approve or revise the Episode 02 model, GPU and protocol matrix.
3. Decide whether the private benchmark service may be named publicly and approve exact attribution.
4. Approve corpus-derivative and comparative-publication rights.
5. Define service entitlement, pricing, failed-run charges, refunds and support.
6. Define retention, deletion, data region and access policy.
7. Resolve unattended spending limits versus per-action destructive approval.
8. Assign owners for service security, evidence publication, incidents and escalation.

Until these decisions are recorded, implementation is limited to UI work, schemas,
documentation and the synthetic offline path. Paid Episode 02 execution, production
service work and public benchmark-service attribution remain unapproved.
