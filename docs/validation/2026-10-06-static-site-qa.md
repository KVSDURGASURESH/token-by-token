# Static evidence site QA — 2026-10-06

## Scope

This record covers the privacy-safe Episode 01 evidence page, the public methodology page, the site-wide Light/Dark themes, preserved legacy views, and the compiled static bundle. The benchmark evidence pipeline is a build-time activity only; no VictoriaMetrics, Grafana, raw dump, or private receipt is required by the published site.

## Automated verification

| Check | Command | Result |
|---|---|---|
| Python suite | `PYTHONPATH=src .venv/bin/python -m pytest -q` | **572 passed, 3 skipped, 3 failed.** The three failures are confined to the production-execution environment lock: the captured contract requires CPython 3.12.13 and this workstation is running 3.12.15. No dashboard, evidence, privacy, or publication test failed. |
| Focused publication tests | `.venv/bin/python -m pytest tests/test_publication_privacy.py tests/test_offline_workflow.py tests/test_static_evidence_pipeline.py -q` | **27 passed.** |
| TypeScript | `npm run check --prefix dashboard` | Passed. |
| Production build | `npm run build --prefix dashboard` | Passed; 49 modules transformed. |
| Dashboard contracts | `for test in tests/dashboard_*_contract.cjs; do node "$test"; done` | Passed: Episode 01 evidence, methodology, Session Field Note data, and theme contracts. |
| Imported results | `node tests/dashboard_import_acceptance.cjs http://127.0.0.1:5196/` | Passed at 1440 and 390 px, including malformed input rejection and Episode 00 preservation. |
| Session Field Note | `node tests/dashboard_session_study_acceptance.cjs http://127.0.0.1:5196/` | Passed at 1440, 768, and 390 px. |
| Episode 01 | `node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5196/` | Passed at 1440, 768, and 390 px. |
| Methodology | `node tests/dashboard_methodology_acceptance.cjs http://127.0.0.1:5196/` | Passed at 1440, 768, and 390 px. |
| Themes | `node tests/dashboard_theme_acceptance.cjs http://127.0.0.1:5196/` | Passed across every public route at 1440, 1280, 768, and 390 px. |
| Experiment planner | `node tests/dashboard_planner_acceptance.cjs` | Passed at 390 and 1440 px. The user-owned test file was not modified or staged by this work. |
| Compiled offline site | `node tests/dashboard_offline_acceptance.cjs dashboard/dist` | Passed: every public hash rendered while non-local requests were blocked. |
| Source privacy | `.venv/bin/python scripts/check_publication_privacy.py --root .` | Passed with the scanner's documented heuristic limitation. |
| Compiled privacy | `.venv/bin/python scripts/check_publication_privacy.py --root dashboard/dist --files-only` | Passed with the scanner's documented heuristic limitation. |

One user-owned work-in-progress script, `tests/dashboard_series_acceptance.cjs`, was intentionally left untouched. It currently stops on a strict selector that expects only one `Explore recorded results` link; the site now correctly exposes one link for each of the two recorded episodes. The same Episode index, Episode 00, Episode 01, navigation, overflow, and local-request behavior is covered by the passing tests above. This is a test-maintenance limitation, not a rendered-site defect.

## Interaction and accessibility checks

- Navigation, theme switching, episode choice, measured-load controls, request anatomy, and two-session replay are native links, buttons, or range controls with accessible names.
- The Episode chooser closes with `Escape` and restores focus to its trigger.
- Reduced-motion emulation reports a `0s` transition duration for the selection ruler.
- Theme choice persists in local storage; with no explicit choice, the initial theme follows the operating-system preference without a first-paint flash.
- Document-level horizontal overflow was absent at 1440, 768, and 390 px. A Chrome page-scale check at 200% on the 720 px layout also reported no document overflow.
- Interactive plots and wide evidence regions use intentional local scrolling where needed; the page itself remains bounded.

## Visual inspection

Episode 01 and Methodology were captured in Light and Dark at 1440, 768, and 390 px. The captures were inspected for hierarchy, typography, clipping, chart labels, evidence-status language, sticky controls, and semantic colors. Green remains improvement/active, orange-red remains regression/not-established, and amber remains contextual in both themes.

Captures:

- `docs/dashboard-captures/static-evidence/episode-1-light-1440.png`
- `docs/dashboard-captures/static-evidence/episode-1-light-768.png`
- `docs/dashboard-captures/static-evidence/episode-1-light-390.png`
- `docs/dashboard-captures/static-evidence/episode-1-dark-1440.png`
- `docs/dashboard-captures/static-evidence/episode-1-dark-768.png`
- `docs/dashboard-captures/static-evidence/episode-1-dark-390.png`
- `docs/dashboard-captures/static-evidence/methodology-light-1440.png`
- `docs/dashboard-captures/static-evidence/methodology-light-768.png`
- `docs/dashboard-captures/static-evidence/methodology-light-390.png`
- `docs/dashboard-captures/static-evidence/methodology-dark-1440.png`
- `docs/dashboard-captures/static-evidence/methodology-dark-768.png`
- `docs/dashboard-captures/static-evidence/methodology-dark-390.png`

## Independent review resolution

A separate GPT-6 Astra xhigh session reviewed scientific claims, privacy, accessibility, static/offline behavior, theme consistency, and route preservation without editing the branch. Its important findings were closed before this final run: the public Episode 00 renderer now imports a separate allowlisted presentation document while the immutable archival snapshot stays unchanged; validation receipts are checksum-bound to source archives and require the exact successful client/engine/GPU checks; invalid measurement levels are rejected; generated output receives value-level privacy validation before atomic replacement; Light-mode retained-study colors were tokenized and contrast-tested; the 1280 px navigation overlap was removed; and the Episode 01 guide was corrected to the real H200 inference-engine study. The reviewer also identified draft-publication privacy work; those user-owned drafts remain unstaged and are explicitly a prerequisite for later owner publication.

## Preservation

- Episode 00 remains available at `#episode-0`; the historical `#recorded-study` alias still resolves to it.
- Episode 01 remains available at `#episode-1`; the fixture remains at `#episode-1-fixture`.
- Session Field Note remains available at `#session-study`.
- Lab routes remain available: `#local-results`, `#quick-test`, `#experiment-planner`, `#episode-runner`, and `#canonical-launch`.
- The four archived concept pages (`index.html`, `lesson.html`, `observatory.html`, and `play.html`) and the supporting `evidence.html` remain present in their separate visualization workspace and were not modified.
- No preserved route silently redirects to Episode 01.

## Publication status

Local static-build readiness is verified. External hosting, CDN behavior, production-domain accessibility, and any owner-only publishing action remain unverified until deployment occurs.
