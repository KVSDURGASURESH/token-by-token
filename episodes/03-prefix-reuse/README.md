# Episode 3 — Prefix Reuse

> **Recorded two-leg study.** This directory contains the allowlisted public
> evidence behind Episode 3.

Read the companion article:
[Token by Token Episode 03 — Can prefix caching fix first-token tails?](https://durgasuresh.substack.com/p/token-by-token-episode-03-can-prefix).

Episode 3 ran two studies sequentially: an engine comparison first, followed by
one switch to a deeper tail-latency investigation. The engine leg reports
within-engine cache-policy comparisons for vLLM and SGLang from separate
allocations; it is not an engine ranking. The tail leg then focuses on vLLM and
adds same-GPU pairs, retained distributions, and native phase context.

## Headline result

Across three fresh same-GPU pairs, the composite cache-plus-hybrid-align policy
recorded a 59% lower content-TTFT p95: 8.486 seconds OFF to 3.476 seconds ON,
with 150 measured primary requests per setting. The broader descriptive table
has 400 measured primary requests per setting and includes five
different-allocation pairs plus the three same-GPU pairs. Every block-level p95
delta favored ON.

P99 is descriptive because each arm has fewer than the 1,000 observations set
for a headline p99 claim. Native measurements are consistent with reduced
repeated-prefix work and queueing, but cache and hybrid alignment changed
together, OFF always preceded ON, clock alignment was not verified, and native
sampling gaps remain flagged. The evidence does not isolate an individual p99
cause, prove a universal SLO guarantee, or resolve an earlier episode's root
cause.

## Counts and controls

- Engine leg: 40 measured rows and 2,000 measured requests. Each engine has
  400 primary requests per cache setting and 100 control requests per setting.
- Tail leg: 800 complete measured primary requests, with 150 per setting in the
  same-GPU headline subset. Thirty-two supplementary partial primary records
  remain excluded from the complete population and are not double-counted.
- Load means four concurrent requests, not four users. Each repetition has 50
  measured requests plus 8 warm-up, 1 insertion, and 1 verification request.
- Primary cohorts use eight repetitions per setting; controls use two. The
  server budget is 8,192 tokens with at most 16 sequences. Inputs are 32,768
  tokens, the output cap is 256, and observed outputs were 31–37 tokens in the
  engine leg and 32–37 in the tail follow-up.
- Exact row-level flags are retained in the source projections. Aggregate
  flagged-row counts are 13 and 3 for vLLM primary/control cohorts, and 16 and
  4 for SGLang primary/control cohorts. Tail scientific flags include native
  sampling gaps and unverified warm hits.

## Cost boundary

The provider-reported Episode 3 campaign total is **$35.041662906**. It includes
$28.823776262 for earlier trials, recovery, and earlier engine work plus
$6.217886644 for the two final comparison allocations. GPU and disk charges are
included. The surrounding account window was $35.052895514, leaving
$0.011232608 unassigned and excluded from Episode 3 attribution. These totals
are provider reported, not invoice certified, and do not support a per-setting
cost-efficiency claim.

## Inspect the public evidence offline

From the repository root:

```bash
python3 -m json.tool episodes/03-prefix-reuse/engine-study.json >/dev/null
python3 -m json.tool episodes/03-prefix-reuse/results.json >/dev/null
python3 -m json.tool episodes/03-prefix-reuse/context.json >/dev/null
python3 -m json.tool episodes/03-prefix-reuse/distribution.json >/dev/null
python3 -m json.tool episodes/03-prefix-reuse/native-phase.json >/dev/null
python3 -m json.tool episodes/03-prefix-reuse/cost.json >/dev/null
```

These commands parse static, allowlisted files. They start no inference engine,
make no provider call, and do not reproduce the paid measurements. The public
client's `selftest --offline` remains deterministic synthetic plumbing and must
not be presented as recorded Episode 3 evidence.

The package contains aggregate measurements only: no prompts, raw traces,
provider or account identifiers, allocation identifiers, credentials, private
profiles, operational endpoints, or deployment recipes. Original evidence
stays private.

Next episode, we’ll test draft-token proposals against the target model and
measure acceptance, rejected work, draft/verification time and end-to-end
speed.
