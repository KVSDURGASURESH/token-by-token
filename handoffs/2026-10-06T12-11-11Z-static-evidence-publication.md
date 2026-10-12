# Static evidence publication handoff

Timestamp: 2026-10-06T12:11:11Z
Branch: `codex/episode-1-local-prep`
Baseline: `77c6906d6a6d`
QA commit: `cb908e5`
Review-fix commit: `774e23c`

## Delivered

- A deterministic, schema-validated Episode 01 static evidence bundle built from approved aggregate evidence and aligned client, engine, and GPU windows.
- A privacy-safe Episode 01 instrument that names only `vLLM` and `SGLang`, compares the matched 12/16/24-user points, and explicitly says capacity and engine-only causality were not established.
- A public Methodology route explaining realistic multi-turn workload shape, accumulated request anatomy, two-session replay, protocol gates, synchronized evidence, and interpretation boundaries.
- Persistent Light/Dark themes on every public route, with system preference before an explicit local choice and no first-paint theme flash.
- Source and compiled privacy gates, a production-offline browser gate, responsive/browser contracts, and twelve inspected visual captures.

## Evidence lifecycle

VictoriaMetrics and Grafana are local build-time validation tools. They are needed only when an approved private evidence release changes. Once the validated aggregate document is generated and committed, ordinary builds and all public viewing use that static JSON alone. Do not publish the private reports, raw metrics export, receipts, dashboards, service endpoints, or import namespaces.

For an unchanged evidence release, the reproducible public verification sequence is:

```bash
python3 -m unittest tests.test_static_evidence_pipeline tests.test_episode1_public_evidence tests.test_publication_privacy
python3 scripts/check_publication_privacy.py --root .
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 scripts/check_publication_privacy.py --root dashboard/dist --files-only
node tests/dashboard_offline_acceptance.cjs dashboard/dist
```

For a changed approved release, run `scripts/build_static_benchmark_evidence.py` locally with the private run directories identified by evidence role, successful validation receipts, the public schema, and the public output path. Re-run every command above. Private inputs and receipts never enter Git.

## Verification state

- Python: 572 passed, 3 skipped. Three production-execution tests fail solely because the immutable execution contract records CPython 3.12.13 while this workstation runs 3.12.15.
- Dashboard contracts, TypeScript, Vite production build, source privacy scan, compiled privacy scan, and production-offline acceptance passed.
- Episode 01 and Methodology passed at 1440, 768, and 390 px. Theme behavior passed across every public route; imported results, Session Field Note, and planner acceptance passed.
- The complete command/result table and captures are in `docs/validation/2026-10-06-static-site-qa.md`.
- External hosting and owner-only publication remain unverified.

## Independent Astra review

A separate GPT-6 Astra xhigh review requested changes and made no edits. Its important findings were resolved in `774e23c`: Episode 00 now renders from a dedicated allowlisted presentation artifact; evidence receipts are hash-bound to source archives and require the expected successful dashboard checks; invalid levels cannot enter comparisons; privacy validation runs before output replacement; Light-mode evidence colors meet the tested contrast floor; the theme control no longer overlaps navigation at 1280 px; and the Episode 01 guide now describes the actual public study. The follow-up verification results are recorded in the QA document.

## Preservation and working-tree boundary

Episode 00, the Session Field Note, canonical and lab hashes, the local fixture, and all separate visualization concepts remain intact. Two pre-existing user-edited test files and `docs/publication-drafts/` are intentionally not part of this implementation commit history and must not be discarded or staged without owner review.

## Next actions

1. Review the final branch for scientific claims, privacy, accessibility, static/offline behavior, theme consistency, and route preservation.
2. If clean, deploy the compiled static site through the owner's chosen host and verify the production URL independently.
3. Privacy-revise the LinkedIn/Substack drafts to remove engine versions, identifiers, serving recipes, and other withheld configuration details; publish only after the owner approves the sanitized wording and screenshots.
4. Reopen the metrics-import pipeline only when a new approved evidence release is accepted.
