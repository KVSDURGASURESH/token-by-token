# Publication evidence ledger

This private editorial ledger supports `substack.md` and `linkedin.txt`. It is not itself publication copy.

## Evidence classes

| Material | Classification | Publication use |
|---|---|---|
| Four October 4–5 RTX/H200 sweep and soak result bundles in the handoff ZIP | Recorded provider-run results; raw-cohort summaries retained, but provenance is unverified and cost/cleanup evidence is not supplied in this handoff | Current measurements, configuration and limitations |
| `data/public/report.md` and the Episode 0 dashboard view | Prior actual exploratory experiment | Earlier-study comparison only |
| `dashboard/src/data/session-capacity-study.json` and `#session-study` | Sanitized local presentation of the supplied handoff | Interactive presentation of current measurements and limitations |
| `docs/prior-study/report.md` | Prior trial / historical study | Historical cost and methodology context only |
| Local review and drafting in this branch | Local work | $0 provider-charge statement only |
| Proposed cache, telemetry and repeated-neighborhood runs | Planned | Future work only |

## Primary retained sources

- External handoff ZIP supplied by the user: `2026-10-05-token-by-token-handoff.zip`
  - `2026-10-05-token-by-token-benchmark-handoff.md`
  - `2026-10-05-token-by-token-all-level-metrics.csv`
  - `2026-10-05-token-by-token-evidence.json`
- Earlier Episode 0 aggregate report: `data/public/report.md`
- Earlier Episode 0 reproduction contract: `data/public/reproduction.md`
- Earlier RTX study: `docs/prior-study/report.md`
- Current dashboard aggregate data: `data/public/dashboard/latest.json`
- Sanitized session-study dashboard data: `dashboard/src/data/session-capacity-study.json`

Absolute paths stay in this private ledger and must not be copied into publication artifacts.

## Headline calculations

Calculations use full-precision values from the handoff CSV.

| Claim | Calculation |
|---|---|
| H200 soak output was 54.6% higher | `(379.9426568493 / 245.7181547412 - 1) × 100 = 54.62%` |
| H200 median request decode was 84.9% higher | `(63.8929732802 / 34.5508629856 - 1) × 100 = 84.92%` |
| H200 p95 visible TTFT was 65.6% lower | `(1 - 2828.482458 / 8216.985583) × 100 = 65.58%` |
| H200 16→64 sweep output increased 3.2% | `(371.3219049334 / 359.8099363824 - 1) × 100 = 3.20%` |
| H200 16→64 median visible TTFT increased about 19× | `22234.826458 / 1168.019291 = 19.04×` |
| H200 16-user output was 96.9% of sweep maximum | `359.8099363824 / 371.3219049334 × 100 = 96.90%` |
| RTX 16→32 output decreased 2.2% | `(228.4629213981 / 233.5016071330 - 1) × 100 = -2.16%` |
| RTX 16→32 p95 visible TTFT increased 2.56× | `20459.291709 / 8006.4425 = 2.56×` |

## Required claim boundaries

- “Users” means synthetic closed-loop load, not subscribers, customers or live agent workers.
- Two slots per user is a client workload ceiling; the server `max-num-seqs` setting was eight.
- The configured 131,072-token context is not an observed 128K prompt workload. Valid prompts peaked at 6,569 tokens in the soaks and 6,691 across the sweeps.
- `cache_observed_requests=0` means no request reported a cached-token count; it does not prove zero cache hits.
- All four manifests have `unverified=true`; hardware verification is false; every level has `capacity_qualified=false`.
- The deployments differ in documented environment and launch details, so results are not a pure hardware-only A/B.
- H200 errors at levels 32 and 100 are client-observed `RemoteProtocolError` events, not proven OOM, model-quality or hardware failures.
- The workload does not execute tools or grade coding-task correctness.
- The two soaks have 2,316 and 3,566 valid responses with visible TTFT after excluding three RTX and two H200 valid responses without that event.
- The dashboard now exposes the RTX/H200 session study as a separate `#session-study` view; Episode 0 remains a separate historical dataset.
- The latest handoff has no matched provider-cost comparison, GPU power series or energy data.
- The ZIP includes an H200 `max_users_knee=2` heuristic even though every level is unqualified and every SLO-table capacity is null. Do not publish that field as a finding.

## Prior-publication review

The September 23 LinkedIn post had 233 impressions, eight reactions and no visible comments when inspected on October 5. It opened with three generic use cases, then carried setup, concepts, results, limitations, cost and roadmap into one long post. The evidence was careful, but the central result arrived late and competed with several calls to action.

The linked Substack article was technically rigorous and visually dense. It taught request phases and KV concepts before reaching the results, used many large tables/screenshots, and repeated subscription and project calls to action. The new draft reverses the information order: surprise, result, meaning, method, limitations, next experiment.

## Link and publication status

- Earlier LinkedIn post: `https://www.linkedin.com/posts/durgasuresh-kagitha_llminference-llmops-vllm-ugcPost-7508307414425714688-MXnQ/`
- Earlier Substack post: `https://durgasuresh.substack.com/p/token-by-token-episode-0-warm-up`
- The new LinkedIn copy contains `[SUBSTACK LINK]`; replace it only after the new article has a verified public URL.
- The Substack copy contains `DASHBOARD LINK`; replace it only after the dashboard has a verified public URL.
- The README describes the repository as private and license-pending; current remote visibility was not independently checked. Do not call it open source or promise public evidence access until that state is verified.
