# Episode 07 aggregate replay

**We Split Prefill and Decode. Why Did First Text Still Get Slower?**

Run `python3 replay.py` next to `episode-07.json`. The command reproduces the steady-load comparison, both burst outcomes and the four sustained rates from the retained paired aggregates. It needs only the Python standard library and makes no network or GPU calls.

Read the companion article, [“We Split Prefill and Decode. Why Did First Text Still Get Slower?”](https://durgasuresh.substack.com/p/we-split-prefill-and-decode-why-did), explore the [live Episode 07 dashboard](https://tokenbytoken.org/episodes/07-prefill-and-decode-disaggregation/), or [play the Episode 07 video](https://tokenbytoken.org/videos/episode-07.mp4). These links present the same recorded study; the files in this directory remain the offline arithmetic-replay surface.

The steady result averages the p95 from four windows at 0.5 requests/sec and 4,096-token chunks. The burst result averages the four block-level burst-minus-control changes. Incoming first text is the mean of the four per-block medians. The sustained sweep uses four 240-second offers per rate and layout. A null latency summary at 4 requests/sec indicates that client dispatch missed the timing gate. The observed counts at that rate remain in the packet for diagnostics.

This packet contains reader-safe aggregates. It reproduces the headline arithmetic. Rerunning native model serving requires the benchmark execution environment, frozen prompts and provider setup. The PCIe record describes the host qualification failure and contains zero PCIe performance rows.

## Recorded result

Across four matched NVLink burst blocks, disaggregation reduced the foreground
added pause from **43.0 ms to 5.3 ms**. The same layout change increased new
arrivals' mean window-median time to first visible text from **215.5 ms to
425.4 ms**. These are separate measured populations and do not establish a
single causal explanation.

Both layouts passed all four repeats at **2 requests/sec** under the recorded
targets. At **4 requests/sec**, every window was client dispatch-limited, so
the packet makes no server-capacity claim at that rate.

Both tested Hyperstack PCIe hosts failed direct CUDA peer access in each
direction. The PCIe comparison therefore has **zero performance cells**. The
cost record keeps **$68.7031089631 in Runpod debits** separate from **$0.80 in
Hyperstack qualification spend**; it does not present their sum as one
provider charge.

## Public boundary

The allowlist contains this guide, the reader-safe aggregate, its standard
library replay, the replay result and checksums. It excludes prompts, generated
text, raw traces, profiles, credentials, account or allocation identifiers,
private endpoints and launch recipes. The aggregate is byte-aligned with the
reviewed Dashboard reader source. Episode 04 remains the package reference for
explicit denominators, configuration, limits, cost basis and offline inspection.

There are three different reproducibility levels:

1. **Published arithmetic — available here.** With Python 3.12 or newer, run:

   ```sh
   shasum -a 256 -c SHA256SUMS
   PYTHONDONTWRITEBYTECODE=1 python3 -I replay.py > /tmp/episode07-replay.json
   cmp /tmp/episode07-replay.json replay-result.json
   ```

   This recomputes the retained summary from the included aggregates. It does
   not send requests or create a measurement.
2. **A new independent benchmark against a reader-owned endpoint — not
   publicly implemented for Episode 07.** Public client version 0.1.0 accepts
   no endpoint, provider, model, GPU or live load profile. Its `capabilities`
   response reports `execution_status: unavailable` and `real_submission:
   false`. Its versioned Episode 7 catalog entry still describes the earlier
   “Parallelism within one node” plan, so `episode 7 describe` and `episode 7
   selftest` are not this recorded NVLink workload. The self-test is synthetic
   client plumbing only.
3. **Exact original native campaign — not publicly reproducible.** It requires
   the reviewed private AgentBench execution worker, frozen request material,
   runtime and launch closure, provider environment, scheduling controls and
   raw provenance used to adjudicate the retained aggregates. None of those is
   included here. The public `run-local` command requires a reviewed private
   worker and currently supports only an Episode 1 synthetic loopback; it is
   not an Episode 07 GPU runner.

A future self-service Episode 07 benchmark needs a separately reviewed public
contract, sanitized workload generator, endpoint-only runner, result schema and
verifier. That follow-up may accept a reader-owned endpoint while excluding
provider provisioning. It must be approved and tested as a new public
capability; this package does not imply that it already exists.

This local candidate is prepared for private review only. It has not been
pushed, published, deployed or staged in a native publishing surface.
