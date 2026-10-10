# Public site data projection

These JSON files are static, allowlisted projections of the repository's public evidence files:

- `catalog.json` ← `dashboard/src/data/episodes.json`
- `episode-0.json` ← `dashboard/src/data/episode-0-public.json`
- `episode-1.json` ← `dashboard/src/data/episode-1-public.v1.json`
- `field-note.json` ← `dashboard/src/data/session-capacity-study.json`
- `episode-0-telemetry.json` ← rounded projections of the checked-in
  `data/public/telemetry-summary.csv` workload records and
  `data/public/gpu-summary.json` run-level GPU records. The Episode 00 client
  results JSON omits these contextual readings.

`episode-1.json` declares `token-by-token.public-site-projection.v1`. It is a deliberately smaller public-site projection, not an instance of the source `public-inference-evidence.v1` schema. It retains measured values, engine identity, `valid_requests`, `total_requests`, and `level_valid` for each load; it omits private configuration and detailed evidence fields unused by this site. The Episode 00 telemetry file is a separate download because those retained runtime and GPU records are separate from the client-results JSON. Its workload values are keyed by engine to prevent positional reversal; native prefill and decode durations belong to vLLM, while unavailable SGLang phases remain null.

Review every projected field before updating. The public browser bundle may include a reviewed, non-runnable extract of recorded optimization states when those states are already supported by the public reproduction contract; it must not include private endpoints, credentials, profile names, internal tools, raw payloads, private recipes, or an executable deployment profile. Keep measured values and their recorded identities; label engine defaults as not isolated, distinguish observed cost from estimated cost, and never estimate missing points. Run the dashboard build, the publication privacy scanner, and the v2 browser acceptance test after changes.
