# Episode N — Experiment title

Copy this file to `episodes/<number>-<slug>/README.md`. Replace every placeholder
with retained evidence or an explicit “unavailable” before marking it available.
After copying, update the relative links from `../` to `../../` to match the
new directory depth.
Add an entry to `dashboard/src/data/episodes.json`, using Episode 0 as the field
reference, then run `python3 scripts/update_episode_index.py`. The registry row
is the episode's machine-readable metadata. Use `dashboardView: "guide"` until
a dedicated renderer exists; never point a new episode at Episode 0's charts.

## Problem and question

Explain the use case, why this test matters, the baseline, and the one factor
being changed. Declare quality and service targets before inspecting results.

## Evidence and setup

| Field | Recorded value |
|---|---|
| Status and evidence class | Planned / local rehearsal / actual experiment / prior trial / setup failure |
| Model, revision and precision | To be recorded |
| GPU count, memory and topology | To be recorded |
| Runtime version and immutable container digest | To be recorded |
| Dataset, prompt/output lengths, concurrency and arrival pattern | To be recorded |
| Harness revision, plan digest and repetitions | To be recorded |
| Controlled factor and baseline | To be recorded |

Link the sanitized evidence bundle, checksums, reproduction procedure and the
canonical [setup guide](../docs/runpod-setup.md). Keep credentials and raw
account records out of the repository.

## Concepts needed to read this experiment

Explain only the relevant mechanisms. Include a sourced, labeled diagram when
it teaches more clearly than prose. Retain its editable source and alt text.

## Results and charts

Use genuine dashboard captures with axis labels, units, sample counts, and
captions stating exactly what was measured. Include equal-work checks and
unavailable metrics. Separate observations from explanations and recommendations.

## What this experiment actually cost

| Activity | Amount | Evidence | Accounting limits |
|---|---:|---|---|
| Actual experiment | Unavailable | Retained provider record | State scope and attribution |
| Local rehearsal | $0 provider charges | Offline execution record | Not a provider measurement |
| Separate prior trials or setup failures | Unavailable | Separate retained records | Never add estimates as extra transactions |

## Limits, cleanup and conclusion

State missing provenance and uncertainty. For paid runs, cite retained verified
deletion evidence; do not imply a fresh provider check when reporting history.
Say which declared targets the evidence supports. Retest combined optimizations
against the original baseline before recommending a configuration.

## Next experiment

Link the relevant step in the single [experiment map](../docs/roadmap.md).
Update that source if the plan changes; do not create a separate future roadmap.

[Back to the series index](../README.md)
