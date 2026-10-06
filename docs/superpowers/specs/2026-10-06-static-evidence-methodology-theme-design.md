# Static Evidence, Methodology, and Theme Design

**Date:** 2026-10-06  
**Status:** Approved in conversation; awaiting written-spec review  
**Scope:** Token by Token static dashboard, Episode 01 evidence, methodology route, and site-wide Light/Dark themes

## 1. Objective

Turn the final H200 benchmark evidence into a public, static learning experience that:

- explains how realistic conversational and agentic-serving measurements were produced;
- compares only the public inference-engine identities `vLLM` and `SGLang`;
- embeds enough approved aggregate telemetry to render every public chart offline;
- never requires a public metrics service, Grafana instance, Docker runtime, or benchmark repository;
- does not expose the benchmark tool name, sponsoring organization, internal serving profiles, profile-dependent optimizations, private runtime flags, internal paths, endpoints, prompts, request content, run identifiers, or machine identifiers;
- provides consistent Light and Dark themes across all public routes.

## 2. Evidence position

The source repository is synchronized to commit `042dc4c`. Its final report, per-level tables, per-request evidence, and compressed time-series exports are private build inputs, not public site assets.

The public study will distinguish three claim classes:

1. **Directly measured observation** — an aggregate from a valid measured window.
2. **Threshold result** — a measured point met or missed a declared rule, such as decode p10 ≥ 20 tok/s.
3. **Not established** — capacity, quality, provenance, or statistical certainty was not demonstrated by the underlying evidence.

The final executive report calls a private 14-user profile a capacity result, while its underlying single-level report records skipped coherence, unverified provenance, and capacity not established. The public site will not publish that private profile or its 14-user headline. It may be imported internally to verify the extraction pipeline, but no profile-derived value may be merged into a public `SGLang` series.

The public Episode 01 comparison remains the matched, valid vLLM and SGLang engine evidence at 12, 16, and 24 users. Where configurations differ, the page states that this is a recorded deployment comparison rather than an engine-only causal claim.

## 3. Privacy boundary

### 3.1 Public allowlist

The static bundle may contain only:

- inference-engine labels `vLLM` and `SGLang`;
- public model family and precision;
- hardware class and count;
- measured user and active-session counts;
- public workload descriptors and anonymized workload-shape aggregates;
- warm-up and measurement durations;
- valid/total request counts and public metric aggregates;
- client-visible latency, throughput, completion-validity, engine queue/cache aggregates, and GPU utilization/memory/power aggregates;
- general limitations and evidence-state labels;
- non-sensitive public source licences when legally required.

### 3.2 Forbidden public content

Neither source files nor compiled assets may contain:

- the benchmark tool name or sponsoring organization name;
- internal profile names, profile IDs, runtime recipes, optimization names, launch flags, environment variables, container images, package builds, version-specific tuning, or profile-specific conclusions;
- repository paths, result-directory names, run IDs, commit IDs, endpoints, IP addresses, ports, service instance labels, pod/provider identifiers, or local usernames;
- raw Prometheus/VictoriaMetrics labels unless explicitly allowlisted and rewritten;
- prompts, completions, tool schemas, tool payloads, tool results, source session IDs, request IDs, or machine IDs;
- raw `.gz`, Parquet, JSONL, manifests, logs, or Grafana exports.

Inference-engine versions are omitted from the public UI. The source evidence may record them privately, but the public comparison labels are only `vLLM` and `SGLang`.

### 3.3 Enforcement

A privacy contract scans:

- the generated static evidence JSON;
- dashboard source data;
- the production JavaScript and CSS bundles.

The build fails on forbidden names, absolute paths, endpoint syntax, result/run identifiers, profile/configuration keys, known private optimization terms, or unexpected top-level evidence fields. The generator uses a positive schema allowlist; deletion-based sanitization is insufficient.

## 4. Evidence pipeline

The browser never queries a live time-series service.

VictoriaMetrics and Grafana are **build-time, local-only validation tools**. They are used once when a new private evidence release is accepted—or again only when the source evidence changes. After extraction and verification, the generated static JSON becomes the website's complete data source. Publishing and viewing the site require neither service, their containers, the raw `.gz` exports, nor access to the private evidence repository.

```text
private reports + compressed native metrics
                 │
                 ▼
      local VictoriaMetrics import
                 │
                 ▼
      local Grafana/query validation
                 │
                 ▼
       allowlisted aggregation script
                 │
                 ▼
   privacy scan + scientific contract tests
                 │
                 ▼
       static versioned evidence JSON
                 │
                 ▼
          Vite production bundle
```

### 4.1 Import isolation

Imports use the existing loopback-only VictoriaMetrics and Grafana services. Each source run is mapped internally to an opaque temporary import namespace. The import process records file checksums, declared start/end windows, series/sample counts, import response, and validation queries in a local evidence receipt that is not shipped.

Duplicate imports are tolerated by VictoriaMetrics, but the extraction step deduplicates by series identity and timestamp. It rejects samples outside the declared window and detects counter resets or incomplete windows.

### 4.2 Validation

For each private run:

- compare imported series count with the export manifest;
- verify client, engine, and GPU families are present when declared;
- validate query results against the per-level aggregate tables;
- inspect locally provisioned dashboards at the exact run window;
- keep missing metrics unavailable with a reason;
- never average published percentiles or compare runtime-native metrics with incompatible definitions.

### 4.3 Static extraction

The static generator emits one versioned JSON document with:

- study identity and public evidence state;
- anonymized workload summary;
- public engine arms;
- measured load points;
- exact approved aggregates;
- precomputed chart series downsampled deterministically where needed;
- metric definitions, units, comparison directions, and limitations;
- public methodology facts.

No runtime fetch is required. The same input produces byte-stable output.

### 4.4 Lifecycle

For each accepted evidence release:

1. start or reuse the loopback-only VictoriaMetrics and Grafana containers;
2. import and validate the private metrics exports;
3. generate and privacy-scan the static evidence JSON;
4. build and test the static website using only that JSON;
5. prove the website works with network access disabled;
6. optionally stop the local containers without affecting the built site.

Steps 1–3 are repeated only when approved source evidence changes. Normal site builds may reuse the already generated, version-controlled static JSON and do not require re-importing metrics.

## 5. Methodology page

The methodology page is a reader-facing visual explanation, not a benchmark-tool manual or deployment runbook.

### 5.1 Information architecture

```text
Top navigation                                      Light | Dark

How do you benchmark a conversation, not just a prompt?
Short introduction and evidence-state statement

01  Request anatomy
02  Workload population
03  Two-session replay
04  Measurement protocol
05  Three synchronized evidence views
06  Reading the metrics
07  Evidence boundary
```

The page uses the existing Episode 00 palette and ruled editorial system. A compact sticky rail becomes horizontal chapter controls on narrow screens.

### 5.2 Request anatomy

An interactive layered diagram reveals:

1. system instructions;
2. tool definitions;
3. accumulated conversation history;
4. tool calls and returned results;
5. the current user instruction;
6. the expected output length.

It shows anonymized token distributions, never content. Copy explains why long accumulated context makes agentic traffic materially different from repeated short prompts.

### 5.3 Workload population

The public population is described by behavior category rather than vendor or dataset identity:

- 50% repository-based agentic coding sessions;
- 30% coding-assistant API sessions;
- 20% general multi-turn chat.

The page states that source revisions and licences were pinned privately. It may show session/request counts and prompt-length distributions only when those values pass the allowlist.

### 5.4 Two-session replay

The memorable interaction is a scrub-controlled session timeline. It shows two ordered session slots per simulated user and alternates:

```text
instruction → generation → tool call → tool gap → tool result
→ accumulated context → next generation → human gap
```

The animation responds only to user input, preserves a textual equivalent, and is disabled under reduced motion. It explains that open sessions are not continuously decoding requests.

### 5.5 Measurement protocol

A linear gate diagram shows:

```text
coherence → smoke test → warm-up → measured window
→ validity gate → threshold comparison → report
```

It defines the public rules:

- two-minute warm-up and five-minute measured window for this study;
- minimum valid-request requirement;
- error rate above 1% invalidates a level;
- decode p10 means 90% of valid requests were at least that fast;
- the declared study threshold is decode p10 ≥ 20 tok/s;
- TTFT is reported, not gated, for this study;
- skipped or missing checks remain visibly skipped or unavailable.

### 5.6 Synchronized evidence

An architecture strip aligns three views over the same measured window:

| View | Public measures |
|---|---|
| Client-visible | TTFT, TPOT, decode speed, completion validity, successful output |
| Engine-native | running/waiting requests and cache behavior, with runtime-definition caveats |
| GPU | utilization, memory, power, and derived energy only when valid |

The strip ends at a privacy boundary labeled “static approved aggregates.” It does not name private services or operational endpoints.

### 5.7 Reading the metrics

Plain-language definitions distinguish:

- TTFT from server queue time;
- TPOT from decode tokens per second;
- p10/p50/p95 directions;
- whole-server throughput from per-request experience;
- completion validity from task-solving correctness;
- contextual telemetry from comparable outcome metrics.

### 5.8 Evidence boundary

The final split section lists “Observed” and “Not established.” It forbids extrapolation, engine-wide causal claims, production certification, unmeasured profile conclusions, and statistical-significance claims.

## 6. Episode 01 changes

- Remove the public configuration matrix and every profile/configuration string.
- Replace versioned arm labels with `vLLM` and `SGLang`.
- Replace private provenance with a general statement: “Aggregated from aligned client, engine, and GPU measurements; static publication bundle.”
- Update evidence values only from valid, matched public engine runs.
- Add decode p10 and the declared 20 tok/s threshold as first-class charts/readouts.
- Preserve TTFT, TPOT, throughput, completion validity, queue trends, and GPU telemetry.
- Make every threshold statement identify its basis and keep “capacity not established” where the source evidence does not qualify it.
- Remove profile-dependent 14-user evidence from all public pages and bundles.

Episode 00 and the Session Field Note retain their existing evidence but use the shared privacy contract and theme system.

## 7. Theme system

The top-right site navigation contains a two-button `Light | Dark` switch on every route.

- A stored explicit choice wins.
- Without a stored choice, the initial theme follows the system preference.
- A small inline bootstrap script applies the theme before React and CSS paint to prevent a flash.
- The choice is stored only in local browser storage and transmits nothing.
- Both modes retain the same semantic mapping: green improvement, orange/red regression, amber contextual/display-band state.
- Light mode uses a warm engineering-paper base, dark ink, and derived versions of the existing Episode 00 semantic colors.
- All text, controls, chart lines, focus states, and non-color cues meet WCAG AA contrast and remain usable with reduced motion.

## 8. Failure handling

- Missing final evidence stops generation; the previous approved bundle remains unchanged.
- Privacy-scan failure stops the build and prints only the field/path category, not sensitive values.
- Import or query mismatch marks the evidence receipt failed and prevents publication.
- Missing telemetry renders `Unavailable` with a public reason; it is never converted to zero.
- Invalid or interrupted levels remain excluded from comparative claims.
- If a public aggregate cannot be traced to a valid private source window, it is not emitted.

## 9. Verification

Completion requires:

1. unit/contract tests for allowlisted generation, validity rules, comparison calculations, and deterministic output;
2. a private-source-to-static-aggregate reconciliation test;
3. successful VictoriaMetrics import and exact-window query evidence;
4. local Grafana inspection for every imported public run;
5. production-build privacy scanning of source JSON and compiled assets;
6. browser acceptance at 1440, 768, and 390 pixels for both themes;
7. keyboard, focus restoration, reduced-motion, contrast, and no-overflow checks;
8. an offline test proving every public study and chart works with network access disabled;
9. preservation tests for Episode 00, the Session Field Note, and all archived design concepts.

## 10. Out of scope

- Publishing VictoriaMetrics, Grafana, raw telemetry, or the private benchmark repository.
- Exposing private profiles or teaching readers how they were configured.
- Re-running paid benchmarks or changing provider resources.
- Treating a private single-level profile run as public engine capacity.
- Publishing raw prompts, requests, tool payloads, or session content.
