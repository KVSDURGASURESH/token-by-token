# Public site data projection

These JSON files are static, allowlisted projections of the repository's public evidence files:

- `catalog.json` ← `dashboard/src/data/episodes.json`
- `episode-0.json` ← `dashboard/src/data/episode-0-public.json`
- `episode-1.json` ← `dashboard/src/data/episode-1-public.v1.json`
- `field-note.json` ← `dashboard/src/data/session-capacity-study.json`
- `episode-0-telemetry.json` ← the approved v2 handoff prototype's public aggregate telemetry. The Episode 00 source JSON has client results but omits these contextual readings.

Review every projected field before updating. The public browser bundle must not include serving profiles, engine versions, flags, private endpoints, organization names, private tools, recipes, payloads, or configuration matrices. Keep measured values and their recorded identities; never estimate missing points. Run the dashboard build, the publication privacy scanner, and the v2 browser acceptance test after changes.
