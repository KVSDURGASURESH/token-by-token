# Token-by-Token design workspace

This directory is the entry point for continuing the public dashboard and
publication design from another checkout.

Start with the [continuation guide](CONTINUATION-GUIDE.md). It records the product
requirements, public-data boundaries, implementation state and resume checklist.

## Page construct (next implementation step)

- [Page construct: the global template for every page](PAGE-CONSTRUCT.md) — the shared
  shell, the fixed episode chapter order, status variants (recorded, fixture, planned), the
  rules every page follows, and how Episode 00, Episode 01, Episode 02 and Methodology map
  onto it. It takes precedence over earlier documents on page structure.

## Benchmark service proposal

- [Benchmark service integration proposal](BENCHMARK-SERVICE-PROPOSAL.md) — the
  approved public-client/private-service boundary, plus the Episode 02 protocol,
  local evidence replay, cost gates and remaining decisions that must be approved
  before production service work or paid execution.
- [Public CLI and offline self-test implementation plan](../docs/superpowers/plans/2026-10-08-public-cli-offline-selftest.md)
  — the approved first slice: an isolated public client, strict contracts,
  deterministic zero-network self-test, hostile-bundle verification and guarded
  candidate executable. Hosted execution and Grafana replay remain separate phases.

## Implemented public-site direction

- [Interactive evidence design brief](../handoffs/2026-10-06-interactive-evidence-design-brief.md)
- [Shared public site and episode implementation](../dashboard/src/PublicSite.tsx)
- [Public design system and responsive behavior](../dashboard/src/public-site.css)
- [Versioned public projections](../dashboard/src/data/site-v2/README.md)
- [Claude v2 source-of-truth reference](reference/claude-site-v2/README.md)

The default experience is a concise Episode Brief with a persistent episode
rail. The deeper evidence lab is opened on demand. Metric changes use semantic
green, red, and orange states. The owner-approved complementary cyan is confined
to chapter navigation so it cannot be confused with evidence meaning. Public
views identify inference engines without exposing private serving profiles or
optimization recipes.

## Publication package

- [Publication draft workspace](../docs/publication-drafts/2026-10-05-session-capacity/README.md)
- [LinkedIn draft](../docs/publication-drafts/2026-10-05-session-capacity/linkedin.txt)
- [Substack draft](../docs/publication-drafts/2026-10-05-session-capacity/substack.md)
- [Evidence ledger](../docs/publication-drafts/2026-10-05-session-capacity/evidence-ledger.md)
- [Visual inventory](../docs/publication-drafts/2026-10-05-session-capacity/visuals.md)

## Verification

From the repository root:

```bash
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 scripts/check_publication_privacy.py --root dashboard/dist --files-only
node tests/dashboard_offline_acceptance.cjs dashboard/dist
node tests/dashboard_site_v2_acceptance.cjs http://127.0.0.1:5173/
```

The final browser acceptance check expects the dashboard development server at
the supplied URL. The offline check starts its own loopback server.
