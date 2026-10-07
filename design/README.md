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

## Current Episode 01 direction

- [Interactive evidence design brief](../handoffs/2026-10-06-interactive-evidence-design-brief.md)
- [Episode 01 dashboard implementation](../dashboard/src/Episode1Instrument.tsx)
- [Shared episode shell](../dashboard/src/instrument/EpisodeShell.tsx)
- [Interactive metric instrument](../dashboard/src/instrument/LinkedMetricInstrument.tsx)
- [Design system and responsive behavior](../dashboard/src/styles.css)
- [Public embedded evidence](../dashboard/src/data/episode-1-public.v1.json)

The default experience is a concise Episode Brief with a persistent episode
rail. The deeper evidence lab is opened on demand. Metric changes use semantic
green, red, and orange states, and public views identify inference engines
without exposing private serving profiles or optimization recipes.

## Publication package

- [Publication draft workspace](../docs/publication-drafts/2026-10-05-session-capacity/README.md)
- [LinkedIn draft](../docs/publication-drafts/2026-10-05-session-capacity/linkedin.txt)
- [Substack draft](../docs/publication-drafts/2026-10-05-session-capacity/substack.md)
- [Evidence ledger](../docs/publication-drafts/2026-10-05-session-capacity/evidence-ledger.md)
- [Visual inventory](../docs/publication-drafts/2026-10-05-session-capacity/visuals.md)

## Verification

From the repository root:

```bash
cd dashboard
npm run check
npm run build
cd ..
node tests/dashboard_instrument_acceptance.cjs http://127.0.0.1:5173/
node tests/dashboard_interactive_evidence_contract.cjs
```

The browser acceptance check expects the dashboard development server to be
running at the supplied URL.
