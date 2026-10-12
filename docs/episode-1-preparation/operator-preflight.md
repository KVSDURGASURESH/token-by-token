# Episode 1 operator preflight and cost ledger

Checked against public official documentation on 2026-09-22. This is a free preparation artifact. No offer, balance, resource creation, runtime startup, charge or cleanup has been observed for Episode 1. `execution_ready` remains false. The [implementation brief](implementation-brief.md) is the protocol and the [capture contract](capture-contract.md) is the evidence checklist.

## Current termination blocker

The current `runpodctl` Pod reference does not expose `--terminate-after`. Upstream removed that flag and `--stop-after` in v2.12.0 after finding that the accepted API deadline did not stop running Pods; the removal PR also says the deadline could not be read back. An older CLI accepting the flag therefore does not prove a guard exists. Do not copy the repository's old command or downgrade to recover it. Sources: [Runpod CLI removal PR](https://github.com/runpod/runpodctl/pull/330), [v2.12.0 release](https://github.com/runpod/runpodctl/releases/tag/v2.12.0), [current Pod CLI reference](https://docs.runpod.io/runpodctl/reference/runpodctl-pod).

Before creation, verify a supported provider-enforced permanent-deletion deadline and fresh readback, plus an independent local watchdog. If this cannot be established, the project benchmark skill requires a separate exact `ACCEPT LOCAL-WATCHDOG RISK` acceptance before its local-only fallback can be considered. That fallback needs both detached monotonic watchdogs, code hashes, recorded deadlines, heartbeat/supervision evidence and workstation sleep prevention. They share workstation/network failure modes; this is not equivalent to a provider guard. Neither that acceptance nor spending approval has been given for Episode 1. Do not start a heartbeat or watchdog that could create or delete resources tonight.

The degraded plan must also bind separate nonce-matched armed checkpoints after each watchdog's initial provider poll, fresh heartbeats from both roles, `caffeinate`, arming/CLI timeouts, polling and delete-retry policy, and a conservative teardown horizon. At 75% of maximum exposure start no new arm; at 85% stop traffic and preserve only essential evidence before deletion. Check these markers and remaining worst-case cost before every block and cell. The compiler advances the delete trigger enough to include the full arming/polling/retry/CLI horizon. This fallback supports Pods only; adding any other billable resource needs a supported guard design and a new plan. Keep provider credentials and deletion authority off the Pod.

## Free checks before asking for a paid approval

1. Validate the complete Episode 1 protocol, schedule, authored quality corpus, evaluator and local fixture outputs. Freeze their hashes and the exact code state. Verify the fixture mode cannot call the provider or produce an execution approval phrase.
2. Resolve official runtime release tags and platform-specific OCI digests. A manifest-list digest differs from the `linux/amd64` child image digest. Bind the derived operator image and its dependencies, rather than treating a base-tag lookup as a built launch environment.
3. Decide and prove the runtime lifecycle. The intended paired pilot needs one allocation with two isolated, reproducible runtime environments and verified sequential process teardown. Two separate official runtime images alone do not supply that launcher. If this is not implemented, the candidate is not ready for the paired pilot. A revised separate-allocation design must explicitly be unpaired, bind each resource and cost, and be reviewed before approval.
4. Download only the small pinned tokenizer/config assets needed for exact input-length preflight, if tools support it. Do not download tens of GB of weights as an incidental check. Freeze exact rendered input token IDs and template hash. A deterministic filler recipe without tokenizer verification is only a fixture.
5. Check the installed CLI version/help and actual API read-only schemas. Obtain a fresh exact offer, stock, GPU variant, cloud/data center, driver/CUDA requirements, storage/access settings and all displayed charges. Quote observations must be no older than 15 minutes at final approval and creation; recompile if expired or changed. Current stock and account facts remain unknown in this preparation.
6. Privately verify starting balance, minimum reserve, auto-pay disabled, unrelated active billable resources and the deletion guard. Read-only checks do not authorize changing billing or deleting unrelated resources. CLI availability and authenticated account preflight remain unverified here.
7. Compile a new execution plan only after the dedicated Episode 1 live path can bind all material inputs and repeated blocks. Read manifest and compiled plan in full, run the plan verifier, then present the compiler-produced digest and maximum charge for exact owner approval. Do not adapt an Episode 0 one-runtime approval to cover this protocol.

These checks distinguish local readiness from GPU verification: public source inspection cannot prove model fit, CUDA execution, kernel compatibility, effective token behavior, native metrics or actual process isolation on the allocated host. Those bounded startup checks must be part of an approved live plan; their failure ends or marks the arm rather than silently changing a flag/model/image.

## Proposed time and spending policy

The following is an unapproved planning ceiling, not a price quote: at most 120 minutes from creation invocation through verified deletion, proposed maximum charge USD 15, and at least USD 5 remaining balance. The compiler must reject any fresh worst-case envelope exceeding the chosen ceiling. The owner may choose a different ceiling only through a revised plan and exact approval. There is no computed maximum charge or approval phrase in this preparation.

| Exclusive phase budget | Maximum minutes | Scope |
|---|---:|---|
| Provision, image pull and shared model staging | 20 | Includes initial readiness prerequisites; retain actual subphase boundaries |
| Six fresh runtime startups | 24 | Up to 4 minutes each, including readiness and first valid probe |
| Six warmup sets | 18 | Up to 3 minutes per block, all declared shapes |
| Six measured blocks and drains | 42 | 180 + 120 + 120 seconds per block; drain stays inside cell deadline |
| Evidence transfer and permanent deletion verification | 8 | Start teardown with time to observe absence; preserve essential evidence first |
| One bounded startup retry / contingency | 8 | No performance-result retry; cannot extend the overall deadline |
| **Total lifecycle ceiling** | **120** | A phase overrun consumes reserve or ends the run; never extends approval |

Shorter actual phases save money; unused time is not permission for more cells. Before each new block, check that its worst-case remaining work plus evidence transfer/deletion fits the remaining time and charge. Missing heartbeat, unavailable termination control, unexpected resource creation, wrong image/GPU, token mismatch, corrupted corpus or runaway cost stops new traffic and initiates cleanup. A slow provider deletion leaves cleanup unresolved; never claim an absolute cost guarantee while a resource is still billable.

Compute the conservative envelope using every applicable charge from the fresh offer: GPU, container/volume storage, separately billed network/global volumes, endpoint/public-IP, startup/image-pull, egress, rounding, taxes or other displayed components. Every component has an amount/rate, unit, duration rule, source, observed-at and expiry, or a verified not-applicable status. Unknown is not zero. Do not double-count a charge included in a quoted total. No network/global volume or public inference endpoint is planned. Model/cache disk sizing and its charge still need verification.

Runpod's current billing guide describes prepaid balance deductions and a Billing Explorer, and notes that billing updates can lag usage. Its account-wide balance is not an experiment invoice. Capture the selected resource/time range and reconciliation evidence. Source: [Runpod billing overview](https://docs.runpod.io/accounts-billing/billing).

## Phase ledger and reconciliation

Append one immutable event for each create/start/ready/warmup/cell/drain/runtime-exit/export/delete/verification boundary. Record sequence, previous-event hash, event hash, run/block/cell/attempt keys, UTC and monotonic time/domain, evidence-class enum, lifecycle state, source artifact hash and sanitized reason. Private event payloads retain exact provider handles; public events omit them. Hash chaining detects edits only when an externally retained final hash is trusted; it does not prove the event happened.

Derive exclusive resource occupancy intervals from the ledger. An allocation-level staging interval cannot also be charged to every runtime. For each phase keep:

| Field | Meaning |
|---|---|
| observed duration | Measured from compatible clock boundaries, including failure/cleanup time |
| modelled phase USD | Fresh declared rate × observed billable duration plus attributable fees; explicitly an estimate |
| provider-reported USD | A provider line item only when independently available for that phase/resource |
| evidence state | Observed, local fixture, unavailable or unresolved; no fabricated bill |

Reconcile the provider resource total against the sum of modelled phases and separately report the residual. If using balance change, adjust for top-ups, refunds, unrelated resource usage and pending settlement only where supported by evidence; otherwise report unallocated change. Never split residual equally between arms or infer per-runtime cost from request counts. Shared staging can stay shared. Publish total observed charge and estimated serving-window cost as different quantities. Cost per qualifying task is unavailable when goodput evidence is incomplete or there are zero qualifying tasks.

## Authorized execution and final cleanup checkpoints

After exact digest-bound approval, create only resources named in that plan. Record every created resource immediately in a private ownership ledger. Read back the resource, image, effective configuration and guard before starting traffic. Bind the API and metrics service to loopback and use the reviewed SSH tunnel; no unauthenticated public inference port. Launch only the frozen schedule and record failed startup attempts.

At completion or any abort: stop new traffic, cancel/drain within the approved deadline, export the bounded essential evidence, terminate every resource this run created, then query provider inventory again and perform direct lookups. Cleanup passes only when every owned Pod/endpoint/temporary volume is absent and its direct lookup returns not found. A delete response, stopped state or screenshot alone is insufficient. Preserve retries and failed verification privately. Do not delete resources absent from the ownership ledger.

Runpod distinguishes stopping, which can retain billed storage, from termination. Network/global storage has a separate lifetime and must be handled explicitly if ever added to a new plan. Sources: [manage Pods](https://docs.runpod.io/pods/manage-pods), [storage types](https://docs.runpod.io/pods/storage/types).

Observe billing settlement with bounded read-only follow-up after deletion; do not retain a paid resource waiting for its bill. Report unsettled charges as provisional. Build the public aggregate bundle only after privacy checks, denominator reconciliation and cleanup verification. The future report must separate actual results, setup failures, prior trials, planned work and local rehearsal. No paid experiment or result article has been produced by this preparation.
