# Token by Token publication contract

Use this contract for episode reports, Substack and LinkedIn copy, publication previews, and the evergreen GitHub learning project.

## Editorial promise

**Token by Token — Inference Lab** is a hands-on series for understanding inference systems by changing one controlled factor at a time, measuring the effect, and combining only the settings that survive individual tests. The final combination must be retested against the original baseline for the declared use case; isolated improvements do not establish the best configuration.

Write in a plain, conventional technical-blog style. Explain the question before implementation detail. Separate observation from interpretation and recommendation. Prefer concrete nouns, measured values, and short paragraphs over launch language. Keep a finding scoped to the actual model, runtime, GPU, workload, concurrency, prompts, output work, and sampling method.

Substack is the source narrative. Its opening establishes the inference problem and the series vision, followed by the concepts a reader needs for the hands-on work. Then cover the question, evidence lineage, controlled setup, results, cost, limitations, and the next controlled test. The LinkedIn adaptation is compact and also begins with the problem or motivation. Preserve enough setup to interpret the numbers, the central results, what they do and do not establish, and the next experiments. Do not open with “I tested.”

Step 0 is a warm-up: it validates questions, methods, and evidence paths. It does not crown a runtime, GPU, or configuration as a winner.

Read the user-provided book material and reference posts when they are available. Use them to inform the hands-on sequence and teaching quality, cite ideas accurately, and write original explanations. Do not invent missing source contents or links.

Keep the closing experiment map structured. Reuse the canonical tables headed **Project 1 maps into the current roadmap as follows** and **What is not a fourth project** in both publication previews; the longer article may include the complete canonical experiment map. Generate these excerpts from their source so future updates do not create competing copies. Native LinkedIn text must remain within the platform's current limit; preserve readable summaries in the text and use genuine figure attachments where its formatting cannot represent tables.

## Evidence ledger

Before drafting, build a claim ledger from primary retained files. Mark every item as one of:

- **Actual experiment:** provider-backed execution with a complete plan, recorded measurements, cost evidence, and cleanup evidence.
- **Local rehearsal:** offline or local workflow exercise; never describe its outputs as provider measurements or attach provider cost.
- **Prior trial:** historical work that may inform context but is outside the current controlled comparison.
- **Setup failure:** an attempted configuration that produced diagnostic evidence but no valid benchmark result.
- **Planned:** a hypothesis, roadmap item, or unexecuted experiment.

Keep these classes distinct in prose, tables, charts, filenames, captions, and metadata. Use only observed Runpod allocation, duration, and charge evidence; do not estimate an invoice as an observed cost. Never invent missing provider screenshots, identifiers, allocation details, image provenance, results, or cleanup. Missing evidence becomes a visible limitation or follow-up.

Include **What this experiment actually cost** with consistent table headings and values in both previews. Separate the current experiment, zero-cost local rehearsal, and prior trials or setup attempts. Distinguish observed debit, estimated measured-window cost, and any unexplained remainder; do not invent per-attempt transactions from a combined balance change. Use authentic Runpod billing or environment screenshots and retained NVIDIA terminal output only when available and inspected for privacy. Do not confuse NVIDIA NIM output with `nvidia-smi` output.

For paid work, require the user's exact approval of the current compiled plan digest and maximum charge before creating a pod, endpoint, volume, or other paid resource. Approval for another plan or digest does not carry over. Do not start a paid run merely to obtain publication screenshots. Every authorized paid workflow permanently deletes every resource it created and verifies absence with a fresh provider-side read before claiming completion.

## Concepts and visuals

Use a small number of exact diagrams only where they reduce reader effort. Prefer vector or code-generated diagrams with source retained beside the export. Do not fill the article with decorative generated images.

When relevant, diagrams must preserve these distinctions:

- **Prefill** processes the input sequence and creates per-layer KV state; **decode** generates autoregressively, one step at a time, while reading the growing cache. Avoid implying that their compute and memory behavior are identical.
- The **KV cache** holds attention key/value activations for prior tokens at each layer; it is not model weights and it does not by itself mean cross-request reuse.
- **PagedAttention** manages KV memory in blocks/pages to reduce fragmentation and support flexible allocation. **RadixAttention** indexes cached prefixes in a radix tree to enable prefix matching and reuse. They address related serving concerns at different layers and are not interchangeable runtime labels.
- **DP** replicates model workers and partitions requests or training examples. **TP** shards tensor computation within layers. **PP** partitions layers or stages. **EP** distributes mixture-of-experts experts and requires explicit load-balance analysis. State topology and communication costs before recommending a combination.

Charts use standard labeled axes, units, sample counts, and honest scales. Identify distribution summaries and percentiles precisely. A screenshot presented as a dashboard must come from the authentic local dashboard loaded with the cited retained data; never manufacture a provider-console view. Crop only for readability, preserve the evidence context, and give every image useful alt text.

## Canonical sources and roadmap discipline

Maintain one canonical capstone catalog covering three distinct outcomes:

1. **Serving Reliability Lab:** select and validate a serving configuration for a declared use case.
2. **Evidence-Grounded RAG Lab:** build and evaluate a grounded-answer system using appropriately licensed sources and independently labeled evaluation data.
3. **Release and Recovery Lab:** build a release process that can reject a bad candidate, roll back, and demonstrate recovery.

The capstones point to one maintained roadmap. Preserve its full agreed scope, including Jev by TypeSafe AI (not JVM benchmarking), serving engines and platforms, inference optimization, all four parallelism modes, observability/routing, LoRA/QLoRA, and Slurm/Kubernetes. Reuse that source rather than reproducing its topic list in this skill. The roadmap owns future experiment order and status. Articles, LinkedIn posts, episode pages, and capstone documents link to or excerpt that source; they do not introduce competing future-work lists. LoRA, QLoRA, model internals, training, quantization, attention kernels, structured output, orchestration, and other planned topics remain sourced roadmap work until measured. For LoRA/QLoRA, retain the frozen-base/adapter distinction, base precision, trainable parameters, held-out evaluation, memory, timing, and checkpoint lineage.

## GitHub learning project

Treat GitHub as an evergreen learning project rather than a one-episode snapshot. The root README introduces Token by Token — Inference Lab, provides an actually usable zero-cost quickstart, explains evidence classes, links the capstone catalog and the single roadmap, and renders an episode table of contents from the episode registry.

Each registry entry is the episode’s machine-readable metadata and points to its detailed episode page. Each episode includes its question, status, evidence class, exact setup, controlled variables, results, charts, costs, limitations, cleanup status, reproduction route, and next linked roadmap step. New episodes append the registry and copy the reusable episode template; generated navigation must be reproducible from that registry.

The quickstart must work without paid infrastructure. Keep local dashboard instructions distinct from provider execution and explicitly say that local rehearsal generates no provider measurements or provider costs. A live guide may teach GPU choice, the current Runpod Pod/template flow, current official documentation, and pinned model/runtime/container profiles. Rediscover current console/docs and resolve mutable images to immutable digests when preparing a release. Never present historical template IDs or floating image tags as current facts.

Make GPU selection actionable: give the retained tested configuration, explain model precision and weight memory plus KV-cache/context/concurrency headroom, and distinguish tested hardware from suggested alternatives. Include the Runpod link, template/container choice, storage, startup, measurement, shutdown and verified deletion steps. Keep current prices sourced and separate from the experiment's historical cost. Screenshots should support actual setup steps, not decorate the guide.

Do not add a license while ownership and license selection are pending. Rediscover current remote URL, visibility, default branch, publication state, and license files before packaging or publishing; record the observed state without embedding private remote details in public artifacts.

Direct-copy deliverables should include a canonical Markdown article, paste-ready plain text or sanitized HTML for Substack, a self-contained LinkedIn post, and captions/alt text. Keep generated copies traceable to the canonical source and verify that copy/paste does not omit tables, links, or evidence qualifiers.

## Publication and security gates

Run `python3 scripts/check_publication_privacy.py` on the staged/allowlisted
working tree and `python3 scripts/check_publication_privacy.py --history` on the
release checkout when this repository helper is available. CI repeats both.
For a standalone package with no Git access, use `--root <package> --files-only`.
These pattern checks supplement the manual review below; they do not inspect
image pixels or guarantee the absence of every secret format.

Before declaring a package publishable:

1. Verify claims against the evidence ledger and recalculate displayed aggregates from retained source data where possible.
2. Run relevant offline tests, link checks, package verification, and visual QA. Record the exact commands and observed results in private evidence; publish sanitized aggregates only.
3. Build an explicit allowlist of files intended for publication. Package from that allowlist rather than copying a working directory wholesale.
4. Inspect every allowlisted text file, staged file, and patch for credentials, authorization headers, private registry data, internal URLs, provider/resource identifiers, user names, home-directory paths, raw environment/configuration files, and other private material.
5. Inspect repository history reachable from the proposed public branch, including removed files and oversized blobs. A clean current tree does not make contaminated history safe. Prefer a clean allowlist-built publication history when provenance permits; rewrite already-published history only when the user has authorized that rewrite or the privacy cleanup it is necessary to perform. Preserve unrelated work, prepare and verify the cleaned candidate first, and use a lease-protected push against the reviewed remote head.
6. Inspect image pixels and metadata. Remove metadata and reject images that expose tokens, account details, console identifiers, terminal prompts, private paths, tabs, notifications, or unrelated applications. Re-render from sanitized retained data when possible.
7. Confirm that no secret or private identifier appears in generated archives, checksums, manifests, preview HTML, source maps, notebooks, logs, or dashboard data. Never print a discovered secret; report only the file/location category and remediation status.
8. Confirm license state, dependency/data attribution, registry consistency, setup freshness, verified resource deletion for any paid run, and the independent reader-review disposition.

Creating local drafts and previews is allowed. Posting to Substack or LinkedIn, sending messages, publishing or pushing GitHub content, changing repository visibility, and selecting or adding a license each require explicit user instruction for that action.
