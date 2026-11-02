# Episode 4 — Speculative Decoding

> **Recorded descriptive study; output adjudication pending.** This directory
> contains allowlisted aggregate evidence for target-only versus EAGLE-3
> configurations in vLLM and SGLang. The measured latency differences do not
> establish correctness, losslessness, or a provider-serving selection.

Episode 4 asks whether draft-token proposals reduce decode latency enough to
pay for verification. The experiment used Qwen3-32B BF16 with tensor
parallelism 1 on one H200, closed-loop concurrency 1, and separate short
(128-token) and long (512-token) output classes. Each runtime had a target-only
control and three speculative configurations. Runtime-compatible draft
checkpoints differed, so the package reports within-runtime comparisons and
does not rank vLLM against SGLang.

## Configuration notation and mechanism

The short labels encode the recorded runtime controls, not interchangeable
quality tiers:

- vLLM `k1`, `k3`, and `k5` set `num_speculative_tokens` to 1, 3, and 5.
- SGLang `s1d2`, `s3d4`, and `s5d6` set
  `speculative_num_steps` to 1, 3, and 5 and
  `speculative_num_draft_tokens` to 2, 4, and 6. All three keep
  `speculative_eagle_topk` fixed at 1.

EAGLE-3 proposes candidate tokens and the target model verifies them. Accepted
draft tokens can reduce target decode work; rejected proposals consume draft
and verification work without becoming delivered output. This is why the
package reports latency together with proposal acceptance telemetry and keeps
output adjudication as a separate gate.

## What was observed

Each chart cell contains 12 paired measured requests. Positive percentages
mean the speculative arm was faster than its paired target-only control.

| Runtime | Best observed setting | Output | Median TPOT difference | Median E2E difference | Median TTFT difference |
|---|---|---:|---:|---:|---:|
| vLLM 0.32.0 | 5 draft tokens | short | +49.09% | +48.85% | -8.74% |
| vLLM 0.32.0 | 3 draft tokens | long | +50.18% | +49.87% | -27.68% |
| SGLang 0.5.22 | 3 steps / top-k 1 / 4 draft tokens | short | +32.09% | +31.27% | -4.55% |
| SGLang 0.5.22 | 3 steps / top-k 1 / 4 draft tokens | long | +37.35% | +37.12% | -5.33% |

These are descriptive speed differences, not accepted winners. Exact generated
output hashes differed in 46 of 72 vLLM pairs and 64 of 72 SGLang pairs. The
task-specific validation oracle was unavailable, leaving every performance
cell `pending_output_adjudication`. Different hashes do not by themselves prove
semantic regression, but they prevent a losslessness or correctness claim.

The tuning tradeoff is visible in [the chart data](charts.json). vLLM's
five-token configuration had the strongest short-output TPOT result, while its
median draft-miss rate reached 75.09% (short) and 75.37% (long). SGLang's
three-step/four-token configuration had its best observed latency; increasing
to five steps/six draft tokens raised median draft-miss rates to 86.31% (short)
and 83.89% (long) without improving latency.

`k3` and `s3d4` are observed adjudication/balance candidates: they preserve
strong measured latency results without using each runtime's highest-miss
setting. They are not universal recommendations or accepted production
settings. The highest-miss settings were vLLM `k5` and SGLang `s5d6`. For
`k5`, the values above are medians of per-request miss ratios by output class;
aggregating the 24 primary requests instead gives 12,549 rejected of 16,725
proposed draft tokens, or 75.03%. For `s5d6`, the corresponding aggregate is
17,809 rejected of 21,135 proposed, or 84.26%. These aggregates are ratios of
summed counts, not medians. Draft telemetry was missing for 0 of 144 applicable
primary speculative responses across both valid runtime projections.

TTFT was mixed: a few SGLang cells improved, while the other measured cells
regressed. The TPOT and end-to-end results therefore do not imply a TTFT win,
and all timing results remain separate from task-specific output adjudication.

## Counts, controls, and exclusions

- The valid vLLM projection contains 180 terminal responses across 36 tuning
  rows. The valid SGLang recovery projection independently contains 180
  terminal responses across 36 tuning rows. Each runtime has 72 paired primary
  comparisons: 12 per configuration and output class.
- Draft telemetry was present for every applicable speculative response in the
  two valid projections. `results.json` and `charts.json` retain the exact
  denominators and claim status.
- The earlier main-store SGLang requests all returned HTTP 400. They are setup
  failure/RCA evidence only and are excluded from every SGLang performance
  aggregate here.
- Quantiles use linear interpolation over available nonnegative finite values.
  P99 is descriptive and not an SLO guarantee.
- Client timing was recorded at the inference-worker read boundary. Aggregate
  native snapshots are not per-request spans.

## Cost and cleanup

Known Episode 4 modeled exposure was **$12.455083155780555555555555556**:
the vLLM/main tuning run, the clean SGLang recovery, and two earlier canaries.
Provider billing was unavailable, so this is not invoice-certified. Cleanup of
every identified owned allocation was verified by permanent-delete
acknowledgment, direct not-found lookup, and empty inventory. One earlier
create attempt returned an unknown outcome without a resource handle; no
provider-backed charge was observed, inventory stayed empty, and its private
store remains conservatively cleanup-pending/no-replay. See [cost.json](cost.json).

## Inspect the public evidence offline

From the repository root:

```bash
python3 -m json.tool episodes/04-speculative-decoding/context.json >/dev/null
python3 -m json.tool episodes/04-speculative-decoding/results.json >/dev/null
python3 -m json.tool episodes/04-speculative-decoding/charts.json >/dev/null
python3 -m json.tool episodes/04-speculative-decoding/cost.json >/dev/null
python3 scripts/update_episode_index.py --check
python3 scripts/check_publication_privacy.py --root .
python3 scripts/check_public_repository_boundary.py
```

These commands parse and audit static, allowlisted files. They start no
inference engine, create no provider resource, and do not reproduce the paid
measurements. A new measurement requires a separately approved immutable plan,
budget, provider operation, evidence export, and verified cleanup.

## Play through the Episode 04 workflow

The [offline configuration example](../../examples/episode-04-offline-rehearsal.json)
binds the public protocol and its closed execution boundary. After installing
the client from this checkout, run the complete zero-cost path:

```bash
token-by-token episode 4 describe --format json
token-by-token capabilities --episode 4 --format json
token-by-token doctor --offline --format json
token-by-token episode 4 selftest --offline --users 1 --seed 42 \
  --output ./episode-04-rehearsal.tbt.zip --format json
token-by-token evidence verify ./episode-04-rehearsal.tbt.zip --format json
```

The self-test uses visibly synthetic `synthetic-target-only` and
`synthetic-eagle3` arms. It exercises deterministic events, bundle creation,
integrity verification, and classification only. It does not replay the
recorded values, contact a provider, run a GPU or inference engine, accept an
endpoint/profile/model/GPU, or evaluate output quality. Unsupported provider
or GPU flags fail at argument parsing before an output archive is created.

The package contains no prompts, raw traces, generated text, provider/account
or allocation identifiers, credentials, private profiles, operational
endpoints, or deployment recipes. Original evidence remains private.

## Limits and next question

This study covers one model, one H200, concurrency 1, the pinned runtime and
draft revisions, and the tested short/long output contracts. It establishes
the recorded within-runtime timing and draft-telemetry results for that scope;
cross-runtime superiority, semantic equivalence, quality preservation,
provider capacity, and cost efficiency were not established. The next required step is output
adjudication with a task-specific oracle; only then can a configuration pass or
fail the quality contract and become eligible for a recommendation.
