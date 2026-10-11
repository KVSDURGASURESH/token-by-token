# Publication visual

## Lead card

Publish: `h200-16-vs-64-share-card.png`

Editable source: `h200-16-vs-64-share-card.svg`

Suggested caption:

> More concurrency added substantial waiting with little additional output. In one H200 session-replay sweep, moving from 16 to 64 simulated users increased aggregate output by 3.2% while median wait for visible text became 19× as long. This is a measured operating tradeoff, not a production-capacity claim.

Alt text:

> Comparison card for one H200 deployment. At 16 simulated users, aggregate output was 359.81 tokens per second and median visible-text wait was 1.17 seconds. At 64 users, output was 371.32 tokens per second and median wait was 22.23 seconds. The card says capacity remains unqualified.

## Export notes

- Preserve the 4:5 aspect ratio when rasterizing for LinkedIn or Substack.
- Do not crop the bottom evidence qualifier.
- Do not replace “19× the wait” with “19× slower”; the former is the supported calculation.
- The two bar groups use separate scales. They compare values within each metric, not the visual length of throughput against latency.
