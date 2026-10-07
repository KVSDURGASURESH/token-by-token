# Continuation guide

## Mission

Build a public, static, evidence-led benchmark story that is visually distinctive,
interactive and easy to understand before it becomes analytically dense. The site
supports LinkedIn and Substack publication, but must also stand alone as the place
where readers inspect the recorded evidence.

Current working branch: `codex/episode-1-local-prep`.

## Product direction agreed with the owner

1. Use Episode 00 as the visual-system baseline. Keep the same core palette across
   episodes rather than inventing a new color combination for every study.
2. Fuse the useful depth of Episode 00 with the minimalism and strong presentation
   of Episode 01.
3. Avoid the generic “AI dashboard” look. The intended character is editorial,
   futuristic, fluid and interactive, inspired by guided explainers rather than a
   wall of admin cards.
4. Start with a landing/series view and a persistent left episode rail. Readers
   should be able to browse current and upcoming episodes through a modern scroller.
5. Each episode opens to a concise brief: what was tested, why it matters, how it
   was measured, the main finding, measured loads and the few metrics needed to
   understand the conclusion.
6. Put the dense material behind an explicit “Open evidence lab” action. The deeper
   view can contain linked charts, detailed comparisons, methodology and boundaries.
7. Preserve all earlier concepts and samples; do not delete them merely because a
   newer direction is selected.
8. Support light and dark themes from the top-right control.

## Metric semantics

- Use green when a change is favorable for the metric being discussed.
- Use red when it is unfavorable.
- Use orange when it is effectively unchanged, neutral or requires caution.
- Direction is metric-aware: higher throughput/output can be favorable, while lower
  TTFT and TPOT are favorable. Do not color raw numbers without a stated comparison.
- Use the real public metric names, including TTFT, TPOT, throughput/output rate,
  waiting requests, running requests, GPU utilization and power where evidence exists.
- Every chart needs a one-line explanation of what the reader should notice.
- Prefer memorable evidence summaries such as “more output, less waiting” only when
  the recorded data directly supports the wording.

## Episode 01 evidence boundary

- Publicly identify the two inference engines as vLLM and SGLang.
- Do **not** expose serving profile names, profile identifiers, versions, flags,
  endpoints, internal optimization recipes, private configuration matrices,
  organization-specific settings, credentials or private corpus payloads.
- Do not name the internal benchmark tool or sponsoring organization in public copy.
- Describe methodology generically: realistic synthetic conversations, agentic coding
  and tool-call-like payloads, recorded user levels, matched study conditions and
  static evidence derived from benchmark results plus telemetry.
- Avoid causal claims that the experiment did not isolate. Distinguish observations,
  interpretations, limitations and withheld details.

## Data and publishing architecture

- VictoriaMetrics and Grafana are evidence-construction inputs only. Import/query them
  locally when rebuilding the evidence package; the published site must not depend on
  a live metrics service.
- Embed the approved aggregates and downsampled series into versioned static JSON.
- The browser must never contact private endpoints or require VictoriaMetrics, Grafana
  or a benchmark pod after publication.
- The public companion can expose only a safe binary and a small set of parameterized
  controls. Do not publish internal profiles or deployment recipes.
- Update episode data only from traceable repository reports and metric exports. Keep
  provenance, methodology, limitations and the evidence ledger synchronized.

## Current implementation

- Episode 01 defaults to the concise Episode Brief.
- “Open evidence lab” reveals the full interactive chart experience.
- The episode rail remains visible at the narrow in-app browser width.
- URL state preserves selected load, comparison mode and view depth.
- Public Episode 01 evidence and session-capacity copy remove serving-profile details.
- Responsive and evidence-contract tests cover the new hierarchy and navigation.
- Publication drafts, evidence ledger, editorial review and share-card assets are under
  `docs/publication-drafts/2026-10-05-session-capacity/`.
- The detailed design rationale is in
  `handoffs/2026-10-06-interactive-evidence-design-brief.md`.

## Verification state at handoff

- `npm run check`: passed.
- `npm run build`: passed; 49 modules transformed.
- Focused public-evidence/static-pipeline tests: 22 passed.
- Episode instrument acceptance passed at 1440, 768, 542 and 390 pixels.
- Interactive evidence design contract passed.
- Dashboard planner acceptance passed.
- The final series-navigation test was updated to select the first of two identical
  episode CTAs. Its rerun was intentionally stopped at the owner's request to push
  immediately; rerun it first when work resumes.
- A broader Python suite was previously non-green because this environment blocks
  loopback/socket tests and uses Python 3.12.15 where some tests expect 3.12.13. Do not
  treat those environment failures as a production-readiness pass.

## Resume checklist

1. Pull `codex/episode-1-local-prep` and read this guide plus the detailed design brief.
2. Run `node tests/dashboard_series_acceptance.cjs http://127.0.0.1:5173/` with the
   dashboard dev server running.
3. Review Episode 01 as a first-time reader at desktop, tablet and narrow in-app sizes.
4. Keep the brief sparse; move any new chart or table into the evidence lab unless it
   materially changes the main conclusion.
5. Rebuild static evidence if new benchmark or VictoriaMetrics exports arrive, then
   update provenance and publication copy together.
6. Seek a final design review only after the data and interaction contract are stable.
7. Do not merge or publish externally without owner approval.
