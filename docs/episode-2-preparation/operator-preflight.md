# Episode 02 operator preflight

The repository compiler has a separate **version 2** campaign contract. It embeds the full validated protocol, logical trace, counterbalanced runtime schedule, material/defaults documents, capability, cleanup policy, file hashes, workload totals, and phase budgets. Version 1 canonical output is retained. Compilation makes no provider calls and never provisions, arms guards, or installs dependencies.

The initial proposed recorded scope is one H200, six repetition blocks, one unit for each of the eight classes, one warm closed-loop cell at concurrency 2, and one defaults arm for each engine. The minimum volume is 96 workflows and 144 model turns across the engines. The counterbalanced block schedule, rather than a fixed winning engine order, is authoritative. Other recorded cells, optimizations, and burst schedules remain blocked until separately represented, costed, reviewed and approved. Synthetic open-loop rehearsal does not establish a numeric recorded arrival/admission contract.

Preparation is non-authorizing whenever material or capability is incomplete. `preflight()` returns explicit blockers and `provider_calls: 0`; `compile_episode2()` sets `planning_only: true` and emits `execution_ready: false`. A valid planning digest never has an approval phrase. Unknown live prices, ancillary components, stock, auto-recharge or affordability cannot be replaced by invented values; the underlying compiler rejects them. Fake test/rehearsal prices must be explicitly classified `synthetic_mock` and cannot authorize a run.

## Private input contract

`schemas/episode2-execution.schema.json` defines the complete closed binding. The public synthetic protocol is not executable material. Operator input files contain:

- `inputs`: classification, owner cap/reserve, exact single-H200 region/datacenter/resource policy, fresh typed live inputs, full capability and trace, request timeout, expected duration, separate phase budgets and fast-start policy.
- `material`: real built operator/engine image digests, exact dependencies/launch arguments, full native defaults with matching hashes, CPU/static Hopper compatibility evidence, immutable model and tokenizer file inventories, actual template file, tokenizer admission evidence, model-cache placement, telemetry configuration, retained provider/build evidence and code-file closure.
- `cleanup`: resolved owner policy to terminate on success, failure, timeout, interruption and export failure; retained policy evidence; permanent deletion resources; supported guard mode and exact guard parameters/hashes.

Artifact inventories are arrays of `{path, sha256, size_bytes}`. Paths are relative to the private `artifact_root`; actual file bytes, size and containment are verified. Model/tokenizer inventories must match protocol digests. Code-file paths are relative to this repository and must match actual bytes, including the final integrated runner/schedule/controller/tokenizer-admission sources. Regenerate the manifest after integration; mutable work-in-progress hashes are not release evidence. Every referenced required artifact must exist; a claimed hexadecimal digest alone cannot pass readiness.

Tokenizer admission is a purpose-written input artifact, never measured inference evidence. Bind the actual template, admission artifacts, and `usage_must_match_admission: true`. Post-create request usage must match frozen admitted token counts. Local CPU image evidence and vendor/static Hopper support are preparation gates. `post_create_gpu_smoke_required: true` binds the mandatory live GPU/model/kernel/endpoint check after approved creation; local work does not establish H200 serving compatibility.

## Fast start, duration and costs

Bind `setup_to_first_smoke_seconds` to at most 900, a smoke phase of 120–300 seconds, `dependency_installation: false`, and immediate `terminate` on failed image, model, endpoint, telemetry, disk or contract gates. No dependency installation belongs on the paid pod. Build, pin and validate reusable Linux/amd64 artifacts before approval. Image/host-cache and GPU availability can prevent fast start; phase overruns trigger cleanup, never extend the approved lifetime.

Separate budgets cover provision, image pull, all model loads, readiness/default rechecks, smoke, all warmups, benchmark dependency waves, declared retry allowance, essential export and verified teardown. The benchmark lower bound uses every request's full timeout across dependency levels and both engines, rather than expected throughput. Warmups cost their full request timeouts separately. Shared startup/cache phases are charged once per declared resource lifecycle, never once per article or duplicate report. Count all starts/default rechecks in their respective phase bounds. The complete phase sum must fit within two hours and the owner's balance-minus-reserve envelope. Cost calculation, rounding, 75%/85% thresholds and local cleanup horizon use the existing repository compiler arithmetic. Underfunded plans fail with no spend phrase; reduce cells or authored units only through a reviewed protocol while retaining six blocks and all classes. Report p95; p99 remains descriptive below 1,000 applicable valid observations per claim.

Model/cache staging on a network volume requires the **same datacenter**, a verified readable provider permanent-deletion deadline, independently guarded volume cleanup, and its complete billed lifetime. Volume creation/upload is billable preparation and is never included in the free local steps. Local-only dual-watchdog mode rejects `network_volume_gb > 0` and network-volume cache placement. Costed persistent storage belonging to a pod remains allowed because permanent pod deletion removes it.

The provider default requires a readable permanent deadline plus an independently bound local watchdog. Without it, require the separate exact `ACCEPT LOCAL-WATCHDOG RISK`, two detached monotonic watchdog roles under `caffeinate`, fresh nonce-bound heartbeats, current script hashes, CLI/arming/poll/deletion-retry limits and the complete teardown horizon. This acknowledgment never approves spend. Failed smoke/export/timeout initiates immediate task-owned termination; no additional cleanup approval is required. Keep provider credentials and deletion authority off the pod. Require permanent delete acknowledgment, inventory absence, direct not-found and final balance evidence.

## Compile and verify

The current backend cannot prove a permanent readable deadline for both pod and network volume. Consequently every network-cache candidate remains blocked (`cache_lifetime`) even if metadata claims compatibility; the initial route requires baked model assets. Future network support needs a reviewed complete prestage/existence/deletion timeline and cost envelope. No multi-resource control is implemented here.

Precreation capability has the explicit scope `static_readonly`. A retained `episode2.static-attestation.v1` document must say `scope: precreation_static` and bind GPU SKU, model revision, both engine image digests and seven closed checks. Each check has `method`, `artifact_sha256` and `result: pass`, with the source artifact retained and verified. Methods are `runpod_readonly_catalog` (GPU/driver), `engine_cli_contract` (endpoint dialect), `cpu_collector_selftest` (telemetry), `allocation_disk_contract` (requested disk), `engine_cli_defaults` (native defaults), `model_file_integrity` and `tokenizer_admission`. These are candidate checks before creation; actual GPU and serving verification occurs only in the approved fail-fast smoke.

Integrity verification walks all directory components with no-follow descriptors, bounds file count/size/total bytes and hashing time, and compares file identity/size/mtime/ctime before and after hashing. In-process digest reuse requires the same freshly opened descriptor identity and unchanged stat values; replacement or mutation invalidates it. This avoids repeatedly reading the same 65 GB immutable model during one approval operation. Source closure includes all public execution modules, Episode 02 schemas, tokenizer-admission code and project/client dependency locks; compiler dependency versions include jsonschema and its required validation stack. No integrity check is deferred onto a paid pod.

Use the existing pinned Python environment with `jsonschema` available. Each JSON input must be a bounded regular file with mode 0600 beneath the same private input directory (mode 0700); retained artifacts and output remain inside that root. The dedicated CLI rejects duplicate keys, nonfinite numbers, symlinks, root escapes and overwrites, and fsyncs the exclusive private checkpoint. It exposes exactly:

```text
compile_episode2_execution.py --protocol FILE --inputs FILE --material FILE --cleanup FILE --output NEW_FILE [--planning-only]
```

From the repository root:

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/compile_episode2_execution.py \
  --protocol PRIVATE_ROOT/protocol.json --inputs PRIVATE_ROOT/inputs.json \
  --material PRIVATE_ROOT/material.json --cleanup PRIVATE_ROOT/cleanup.json \
  --output PRIVATE_ROOT/compiled-planning.json --planning-only
```

Use absolute private paths in an operator session. The generic version 1 CLI refuses version 2 checkpoints so the dedicated privacy boundary cannot be bypassed. `compile_plan()`, `plan_digest()`, `approval_phrase()` and `validate_approval()` remain the same repository API; version 2 approval revalidates complete contracts, actual referenced files, fresh observations, pricing and cleanup settings. A file/price/model/runtime/guard/schedule/material change requires recompilation and a new approval unit.

Rehearse without provider access:

```bash
PYTHONPATH=src:client/src:scripts .venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_episode2_preflight.py tests/test_compile_episode2.py \
  tests/test_episode2_guard_boundaries.py tests/test_live_scaffolding.py \
  tests/test_local_watchdog.py
```

The installed global `runpod-inference-benchmark` compiler remains unchanged and authoritative under its skill. Its version 1 contract cannot authorize this version 2 extension. Until an independent compatibility/security review and the private operator lifecycle integration pass, **live Episode 02 is blocked** even when local preparation tests pass. Current source, artifacts and offline checks establish only local preparation; provider execution and hosted behavior remain unverified.

## Free build candidates

The compatibility review is itself a retained private artifact. Its `episode2.compiler-review.v1` record must have `status: compatible`, exact `compiler_sha256`, `schema_sha256`, `installed_skill_compiler_sha256` and `source_inventory_sha256` (digest of the complete code-file inventory). Missing or changed review/source bytes keep the plan blocked. This binds independent review to the final integrated source rather than an earlier mutable branch.

The existing guarded build tooling accepts real previously collected system/wheel/builder inputs; it does not download them or create a builder. Run only on an authorized existing local builder and keep artifacts private:

```text
python scripts/episode1_build.py validate --manifest PRIVATE_MANIFEST --root PRIVATE_INPUT_ROOT
python scripts/episode1_build.py prepare --manifest PRIVATE_MANIFEST --root PRIVATE_INPUT_ROOT --output NEW_PRIVATE_CONTEXT
python scripts/episode1_build.py build --context NEW_PRIVATE_CONTEXT --output NEW_PRIVATE_BUILD --timeout-seconds 7200
```

Its generated Docker invocation uses `linux/amd64`, `--network none`, full provenance and the pinned SBOM generator, with OCI archive and build receipt inspection. Extend and review its Episode 02 payload/attestation before reuse; an Episode 1 build alone does not contain this campaign's complete code/material closure. No image build or registry publication is claimed by this preflight implementation.
