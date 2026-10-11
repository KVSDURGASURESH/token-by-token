# Session-capacity publication draft

Reviewable local package for the Token by Token session-replay study.

## Files

- `substack.md`: canonical long-form article and tables.
- `linkedin.txt`: paste-ready LinkedIn adaptation.
- `h200-16-vs-64-share-card.png`: publish-ready 4:5 social card for the lead result.
- `h200-16-vs-64-share-card.svg`: editable source for the card.
- `visuals.md`: publication caption, alt text and export notes for the card.
- `evidence-ledger.md`: private claim calculations, evidence classes and publication boundaries.
- `independent-editorial-review.md`: disposition source from the separate Astra xhigh review.

The interactive companion is available in the local dashboard at `#session-study`.

## Required owner step

Replace `[SUBSTACK LINK]` in `linkedin.txt` and `DASHBOARD LINK` in `substack.md` only after those destinations have verified public URLs. Upload the PNG card to Substack when pasting the article; the relative Markdown image is for the local package preview.

## Publication status

These are local drafts. They have not been posted, pushed or uploaded. The latest handoff does not provide matched provider-cost evidence, resource-cleanup evidence, verified hardware provenance or a public sanitized source bundle. The article states those boundaries. Do not upload the source ZIP wholesale because it contains source links and provenance material not prepared for public release.

## Verification commands

Run from the repository root:

```bash
python3 scripts/check_publication_privacy.py \
  --root docs/publication-drafts/2026-10-05-session-capacity \
  --files-only
```

The privacy helper is heuristic. It does not replace manual claim review, repository-history inspection or image-pixel review.
