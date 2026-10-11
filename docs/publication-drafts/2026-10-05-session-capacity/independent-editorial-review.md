# Independent editorial review — October 5, 2026

Private editorial feedback on `substack.md`, `linkedin.txt`, and `evidence-ledger.md`. This file is not publication copy. No external service was changed and the drafts were not edited by this reviewer.

**Recommendation: retain the central story and headline; revise the interpretation and reader guidance before publication.** I found no wrong headline arithmetic or transcribed main result. The strongest story is the observed throughput/wait tradeoff, followed by the matched deployment comparison and the engineering work that made failures visible. A hardware ranking would weaken the piece.

The opening is materially stronger than the September publication. The remaining risk is that readers see precise performance numbers without equally precise definitions of the measured work, timing population, and experiment lineage. Fix those with short explanations placed beside the numbers; do not add another wall of caveats at the end.

## 1. Priority edits

### P1 — Explain what each metric counts before the matched results

**Location:** `substack.md`, “What we measured” and “The matched 16-user result”; especially original lines 60–71 and 104–116.

The article has throughput, request decode, visible TTFT and end-to-end latency but never fully defines their boundaries. “Visible” matters especially for reasoning and tool responses. The retained implementation starts visible TTFT at the first nonempty content delta; the request decode span can begin with reasoning, text, or a tool fragment. Consequently, decode tok/s is not necessarily the user's visible prose rate and cannot be multiplied by user count to recover service throughput.

Suggested insertion:

> I read three measurements together. Aggregate output is the sum of completion tokens from valid responses divided by the send cohort's duration, including drain. Visible TTFT measures the wait for the first text-content delta; an earlier reasoning or tool event does not satisfy it. Request decode rate is a client-derived rate over the stream's first-to-last output-event span. These describe different parts of the response.

In a short method note, retain the exact decode formula: `(completion_tokens − 1) / first-to-last output-event seconds`. Those events may contain reasoning, text, or tool fragments; this is not a direct GPU decode measurement. Explain p10 as the tenth percentile of request rates, not a promise to each user.

Also specify the 120-second maximum drain and exact cohort membership: requests sent during `[measurement start, measurement end)`, completed during bounded drain. The 64-user sweep rate uses a 204.38-second cohort versus 184.40 seconds at 16 users. The comparison remains valid as a reported cohort comparison, but the article should not imply that every rate uses exactly 180 seconds or represents stationary long-run throughput.

### P1 — Put timing coverage and sample counts beside the tables

**Location:** `substack.md`, matched results table and both sweep tables, original lines 104–116 and 136–158.

The soak table shows valid/measured counts, but those are not the visible-TTFT denominators. Three otherwise valid RTX soak responses and two H200 responses have no visible-text timing. From the handoff's crosscheck, visible TTFT is available for 2,316 of 2,319 valid RTX responses and 3,566 of 3,568 valid H200 responses. Failures do not contribute latency observations to these valid-response percentiles.

Add a table row:

| Metric | RTX PRO 6000 | H200 |
|---|---:|---:|
| Valid responses with visible TTFT | 2,316 / 2,319 | 3,566 / 3,568 |

Add the note:

> Latency percentiles describe valid responses with the applicable timing field. Failures and missing visible-text timings are reported separately; they are not zero-latency responses.

Restore “measured / valid” to the sweep tables, or place those full tables in an appendix and use charts in the narrative. Otherwise the 0.00% RTX error row hides that it means 0 failures in 375 measured requests, and low-load tails appear more precise than their samples justify.

Disclose the exploratory minimum-sample setting: it was reduced to 8 from the normal 100; this does **not** mean each row has only eight observations. Actual valid counts range from 88 upward. Keep the current disclosure of one sweep and one soak per deployment. Replayed turns from reused sessions are not thousands of independent experimental replications.

Method appendix detail: at source commit `0f5cd38a854e6c8c4b728797b9856e81d61db19d`, level percentiles select a sorted observation at index `floor(n × q)`, capped at `n − 1`. Supplemental raw-cohort quantiles in the handoff use pandas linear interpolation. Do not imply a single percentile estimator across all sources or import Episode 0's linear-interpolation contract into these latest results.

### P1 — State the limits of the LinkedIn workload and hardware comparison directly

**Location:** `linkedin.txt`, setup bullets and paragraph introducing the 54.6%/65.6% comparison.

“Two documented deployments” is a useful phrase, but it does not tell a skimming reader that runtime environments differed. “Coding sessions” can also sound like live task completion. Both limitations are explicit in Substack and should survive the standalone adaptation.

Suggested replacement setup sentence:

> I replayed synthetic conversation history and tool messages on two vLLM deployments. Tools were not executed and coding-task correctness was not scored.

Suggested replacement for the hardware-ratio paragraph:

> The H200 deployment produced 54.6% more aggregate output and a 65.6% lower p95 visible-text wait. The software environments differed, so these are deployment results, not an isolated GPU comparison.

Add to the slots bullet, or its caption: “At 16 users: up to 32 client requests in flight; server sequence cap: eight.” The eight-sequence limit is a useful explanation for why client user count cannot be read as GPU decoder count.

### P1 — Restore continuity with the previously promised experiment and the capacity method

**Location:** `substack.md`, original lines 19–31 and 215–227; `linkedin.txt`, final paragraph.

The published Episode 0 ending promised a controlled prefix-cache on/off test and stressed that open-loop arrivals would be needed for a later rate-based capacity claim. This follow-up is a synthetic closed-loop session replay with caching enabled. It does not fulfill the cache experiment or prove those earlier measurement gaps are all resolved. Acknowledge the change of sequence plainly.

Suggested bridge:

> Episode 0 ended with a planned cache on/off experiment. Before that comparison, this session study tested whether the measurement path could preserve conversation order, distinguish text from reasoning and tool output, and reject incomplete streams. Cache benefit and task quality remain separate experiments.

For the ending, choose one concrete next study rather than seven equally weighted promises:

> Next I will reconcile the effective environments and capture cache usage plus matched client/server telemetry, then repeat the 8-, 16- and 32-user points with a declared interaction target. The planned cache on/off study will hold the session and output contracts fixed. A separate open-loop arrival-rate test will examine sustained arrivals, schedule lag and overload behavior before any production sizing claim.

Link the applicable items in the canonical roadmap, especially measurement, prefix reuse, and saturation/SLO/cost, using a verified accessible destination. Do not silently register this as a completed Episode 1: the existing registry still describes planned measurement/quality-contract work and a local fixture. An unnumbered session-study field note is a safe editorial identity until the owner updates the catalog.

### P1 — Provide a safe, usable evidence route and qualify readiness

**Location:** `substack.md` throughout; `evidence-ledger.md`, evidence classes and publication status.

The article currently has no source links or downloadable evidence references. It asks readers to trust exact tables without an inspection route. Link the earlier published article in the comparison introduction. For the new numbers, prepare an explicitly allowlisted, sanitized metrics attachment or accessible evidence page. The source ZIP contains private-source links and configuration/provenance material; it must not become the public download wholesale.

Do not represent the current H100 dashboard as a viewer for these RTX/H200 results. If new plots are generated from the handoff, label them as such. A native-dashboard claim requires an actual dashboard view loaded with the latest data.

The ledger's “Actual experiment” classification should state the incomplete record more explicitly. The publication contract defines that class with complete plan, cost and cleanup evidence; the ZIP does not supply that complete package. Suggested label:

> Recorded provider-run results; raw-cohort summaries retained, but provenance is unverified and cost/cleanup evidence is not supplied in this handoff.

Do not infer that the latest resources were deleted from Episode 0's teardown records. Do not state repository visibility as a currently verified fact from README text alone. If no authenticated visibility check is made, say “README describes the repository as private; current remote visibility was not independently checked.” No license selection, public upload, or external publication is part of this review.

## 2. Narrative improvements

### Keep the numerical hook, tighten its scope

The existing title works. A slightly more precise subtitle would be:

> In one H200 session sweep, moving from 16 to 64 simulated users barely raised output while median visible-text wait grew from 1.17 to 22.23 seconds.

Replace the first sentence with “In one H200 sweep, I increased simulated users from 16 to 64.” That establishes both endpoints and the single-run scope before the ratios.

Use “19× as long” rather than “19× longer” to remove the minor multiplier ambiguity. Keep “median” and “visible” in the opening or graphic; never reduce the result to “all users waited 19× longer.”

### Move the measured payoff ahead of the full configuration matrix

The new opening is excellent, but the article still postpones the matched-soak numbers behind the historical comparison, workload details, and a 16-row configuration matrix. The reader has been promised a result, then asked to read a long setup section.

Recommended order:

1. Numerical hook and practical question.
2. Compact matched-soak table, preceded by model, two-slot definition, server cap, and deployment-comparison qualifier.
3. Two short paragraphs defining the metrics and their populations.
4. Previous-study comparison: what changed and what remains unmeasured.
5. Workload and configuration matrix.
6. Sweep tradeoff and failure analysis.
7. Measurement changes, remaining qualification gaps, cost and next test.

Keep both requested comparison tables. Their purposes differ: the previous-study table establishes lineage, while the configuration matrix establishes comparability. Avoid a cross-episode speedup column because model, precision, runtimes, prompts, load process and metric handling changed.

In the configuration matrix, add a compact “client placement” row: runbook describes a Mac client; run configurations label `remote_pod`; placement is not reconciled. This is relevant to client-observed latency. If the matrix is presented as a reproduction recipe, it also needs prompt/session hashes, image digest, parser flags, `preserve_thinking=false`, exact seed and output policy. Otherwise label it “comparison summary” and put exact provenance in the sanitized evidence attachment.

### Remove sentences that announce the prose's seriousness

Cut “That is the real subject of this experiment,” “The result is useful. It is also deliberately incomplete,” “That boundary is not an apology…,” and “The core lesson is simple, but not simplistic.” They consume attention without supplying evidence.

Consolidate capacity limitations into one compact explanatory section; retain the immediate 128K correction and hardware qualifier where readers first need them. The current article repeats the absence of a capacity claim in the subtitle, introduction, sweep interpretation, qualification section and conclusion. The same boundary can remain clear with fewer repetitions.

Use “a candidate point for repeat testing” instead of suggesting “16 users” is a generally useful production operating point. Whether an 8.22-second p95 wait is acceptable depends on the application. The hypothetical 10-second review line is explicitly hypothetical already; retain that wording and do not describe it as a predeclared passed SLO.

### Make LinkedIn end in the next experiment

The current post is 2,192 characters and 330 words, leaving room to clarify scope without turning it into the article. The opening finding is repeated later almost in full. Remove one occurrence and use the space for the workload/hardware qualifiers above and a concrete next step.

Suggested closing before the article link:

> Next: capture cache usage and matched server telemetry, then repeat the 8/16/32-user neighborhood against a declared response-start target. What visible-response budget would you set for an interactive coding assistant?

Keep the cost note as a brief evidence statement, not a pitch for cheap service. Replace `[SUBSTACK LINK]` only when a usable article URL is verified; retain it visibly as a draft placeholder until then.

## 3. What the earlier communication got right and what to change

I read the actual [September LinkedIn post](https://www.linkedin.com/posts/durgasuresh-kagitha_llminference-llmops-vllm-ugcPost-7508307414425714688-MXnQ/) and its [linked Substack article](https://durgasuresh.substack.com/p/token-by-token-episode-0-warm-up), not just `data/public/linkedin-post.md`.

The published post already led with use cases and preserved the unequal-output caveat. The article correctly distinguished client TTFT from server phase timing, cache management from prefix reuse, and GPU peaks from sustained behavior. Keep those habits. It would be inaccurate to criticize the published post for beginning “I tested”; that wording belongs to an older retained draft.

The weakness was information priority. Setup, concepts, result, costs, roadmap, GitHub exploration and subscriptions all competed for attention. The article's important reversal—higher aggregate output alongside worse request-tail decode behavior—arrived well after the teaching material. The new numerical opening improves this substantially.

The published LinkedIn phrase that the framework and dashboard let readers “reproduce the work” was broader than the retained provenance supports. The public bundle supports inspection, validation and local rehearsal; it cannot recreate the exact historical environment. Future copy should say that explicitly.

The prior Substack uses many image tables and dashboard captures. Detailed alt text helps, but the new article should prefer selectable text tables where the publication surface supports them; otherwise accompany image tables with an accessible text or CSV version. Avoid filling the feed with eight attachments again. One clearly labeled comparison graphic is enough for LinkedIn; use a separate sweep graphic in the article.

Do not infer reach, algorithmic suppression or editorial causality from the small, mutable analytics snapshot. The ledger records 233 impressions; this independent inspection saw 234. Both can be time-specific observations, but neither establishes why the post performed as it did. Analytics are unnecessary to the editorial case and should stay out of publication copy.

## 4. Recommended figures

**LinkedIn:** two clearly separated panels for the 16-user soaks: aggregate valid output (245.72 / 379.94 tok/s) and visible TTFT p95 (8.22 / 2.83 seconds). Label devices as deployments, show the measured/valid counts, synthetic two-slot workload, actual prompt maximum of 6,569, and “capacity unqualified.” Do not share an axis between rate and latency.

**Article:** aligned sweep panels for aggregate output, visible TTFT, and failures, with 16 and 64 highlighted. Display every tested point; the H200 32-user failure spike must remain visible. Avoid a fitted saturation curve, confidence ribbon or marked optimum because there is one sweep per deployment and no replicated uncertainty estimate. If connected points are used, identify them as guides between discrete tested levels.

**Optional explanation:** a small diagram showing 16 simulated users → two conversation slots each → at most 32 outstanding client requests → serving queue → at most eight scheduled sequences. It explains more than another decorative GPU image. It is a configured workload diagram, not a measured concurrency trace.

## 5. Verification and unresolved evidence

- Read all three ZIP members; compared the CSV and JSON numeric rows. All 16 rows agree, with no numeric mismatches.
- Recomputed valid completion-token sums from the JSON's retained raw-cohort summaries divided by cohort duration; maximum discrepancy from reported rates was approximately `6.99e-11` tok/s. This independently checks the handoff's arithmetic, not a fresh reprocessing of the Parquet streams.
- Checked measured/valid/error totals for all 16 rows; they agree with the summarized failure counts.
- Confirmed headline ratios from full precision: H200 16→64 output `+3.19946%`; median visible wait `19.03635×`; matched soak aggregate output `1.54625×`; p95 visible wait reduction `65.57761%`.
- Ran `python3 scripts/verify_bundle.py data/public`: passed, no errors or warnings.
- Ran `python3 scripts/check_publication_privacy.py --root docs/publication-drafts/2026-10-05-session-capacity --files-only`: passed with no high-confidence findings. This is a heuristic text/package scan, not clearance of repository history, source ZIP contents, or image pixels.
- Inspected the retained dashboard performance and delivered-work images, their source data, capture documentation, and dashboard rendering code. These are Episode 0 evidence, not latest-study screenshots.
- Inspected metric implementation from the exact source commit using `git show`, because the source worktree itself is on an earlier commit. This supports the metric-boundary and percentile notes above.
- Read the repository publication contract, Episode 0 manifest/plan, reproduction contract, results, cost ledger and canonical roadmap.
- The ZIP records `max_users_knee=2` for the H200 sweep even though every SLO table capacity is unavailable and all level capacity flags are false. The drafts correctly avoid repeating that heuristic value. Add the discrepancy to the private ledger so later copy cannot accidentally promote it into a result.
- No new provider experiment, live hardware verification, billing reconciliation, teardown verification, task-quality evaluation, public-link accessibility audit, history publication scan or visual preview of a finished new package was performed by this review.

The draft is suitable to develop into an exploratory publication after these edits. The evidence supports the reported client-side observations and a plan for better measurement; it does not support production capacity, a cache-speedup factor, task success, hardware causality, or unit economics.
