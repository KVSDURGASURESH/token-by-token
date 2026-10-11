---
status: "DRAFT / NOT PUBLISHED"
evidence_revision: "8db391468aebdc7a5c3b30c7b2a265be96803e1b"
---

# 27.5% more throughput. Still below the decode target.

*Token by Token — Inference Lab. What two exploratory serving studies taught us about work, waiting, and evidence.*

At 16 simulated users, the recorded SGLang deployment delivered 480.44 output tokens per second. The recorded vLLM deployment delivered 376.73.

That is 27.5% more aggregate output, using vLLM as the denominator. It sounds like a straightforward result—until we ask whether either deployment met the experience target.

But both deployments missed the declared decode-speed floor. Their decode p10 values were 17.48 and 15.96 tokens per second, below the required 20. “More output” and “meets the target” are different findings. [Recorded Episode 01 evidence](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/dashboard/src/data/site-v2/episode-1.json).

The useful question is not simply “Which engine produces more tokens?” It is “Which deployment delivers the work we need, quickly enough for the people using it?”

**Token by Token** is a public learning series built around that question. We will establish a comparable baseline, test individual changes, and retest promising combinations against a declared workload and service objective. Episodes 00 and 01 are exploratory foundations, not the final selection exercise.

Three measurements help read the results: **TTFT** is the wait for the first visible content; **TPOT** describes a request's average token-delivery pace after that first token; **throughput** adds delivered output across requests. A deployment can look better on one and still disappoint on another.

## What changed between the two studies

| Study dimension | Episode 00: exploratory warm-up | Episode 01: measure what matters |
|---|---|---|
| Question | Are we comparing the same delivered work? | Does higher output also satisfy the declared decode target? |
| Hardware | One H100 80 GB per run | One H200 per recorded arm |
| Engines | vLLM and SGLang | vLLM and SGLang |
| Workload | Synthetic exact-token inputs; six input-length/concurrency combinations | Multi-turn session replay; 12, 16 and 24 simulated users |
| Load interpretation | Input length and concurrency change together | Two session slots per user; selected closed-loop loads |
| Observation policy | Three repetitions for baseline cells; two for stress cells | 120-second warm-up before each 300-second measured window |
| Acceptance boundary | Descriptive warm-up; no runtime winner | Decode p10 ≥ 20 tok/s; validity failures ≤ 1%; TTFT reported but not gated |

These are separate experiments, not a hardware upgrade comparison. Differences in hardware, model/workload setup and measurement protocol prevent attributing an Episode 00-to-01 change to the H200 or any one optimization. The setup comes from the [Episode 00 study record](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/episodes/00-warm-up/README.md) and [Episode 01 public evidence contract](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/dashboard/src/data/episode-1-public.v1.json).

Episode 01 benchmarking harness powered by AgentBench from Mirastack Labs. The harness remains private; the public repository contains learning material, a viewer and approved evidence, not a complete execution recipe.

## Episode 00: check the work before comparing the speed

The exploratory H100 study covered six input-length/concurrency combinations, each with both runtimes. The retained record contains 936 successful requests and zero recorded failures. Here, success means a completed valid stream, not demonstrated semantic correctness or production reliability. [Episode 00 study description](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/episodes/00-warm-up/README.md).

Consider the workload with 2,048 input tokens and concurrency 24:

| Recorded metric | vLLM | SGLang |
|---|---:|---:|
| Delivered output rate | 263.05 tok/s | 176.71 tok/s |
| TTFT p50 | 6.405 s | 10.688 s |
| Reported TPOT p50 | 35.59 ms/token | 29.70 ms/token |
| Mean delivered output/request | 128 tokens | 128 tokens |

Both arms recorded 96 successful requests and 12,288 delivered output tokens in this cell. The values come from the [public Episode 00 aggregate](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/dashboard/src/data/site-v2/episode-0.json).

Using SGLang as the denominator, vLLM recorded 48.9% higher output throughput and 19.8% higher reported median TPOT. Higher aggregate output coincided with a slower reported per-request token pace.

That is a descriptive observation. Equal mean output length helps interpret the comparison, but it does not establish equivalent semantic quality or isolate why the deployments behaved differently.

The longest stress workload adds a stronger warning. At 8,192 input tokens and concurrency 32, vLLM delivered an average of 99.89 output tokens per successful request; SGLang delivered 128. Both had a configured cap of 128.

The recorded rates—57.5 versus 43.7 tokens per second—therefore describe unequal delivered work. Stop reasons and output-length distributions were not retained. The evidence cannot establish whether early stopping, different output behavior, or another factor explains the difference. [Recorded results and limitations](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/docs/results.md).

Input length and concurrency also change together across Episode 00’s six workloads. Connecting those points does not create a controlled concurrency-scaling curve. Each point represents a different workload.

## Episode 01: more output can still miss the target

The recorded comparison used one H200 per deployment and a matched model family, at 12, 16, and 24 simulated users. Each user had two session slots, giving 24, 32, and 48 slots. Session slots are not necessarily simultaneous active server requests.

Each load had a 120-second warm-up and a 300-second measured window. Multi-turn sessions were replayed against actual deployments. These are fresh inference measurements under replayed load, not an offline fixture and not a task-solving evaluation of live agents. The approved aggregates do not establish semantic answer quality. [Public study method and limits](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/episodes/01-measure-what-matters/README.md).

The declared decode floor was:

\[
p10(\text{per-request decode speed})\ge20\ \text{tok/s}
\]

This checks the lower tail of decoding speed: the intended requirement is that roughly 90% of valid requests decode at least that fast.

A separate validity limit allowed at most 1% of measured requests to fail the validity contract. TTFT was reported for experience analysis, but it was not a capacity gate. Passing validity and passing the decode floor are separate outcomes.

The public results are:

| Users | Deployment | Output tok/s | TTFT p50, s | TTFT p95, s | TPOT p50, ms/token | Decode p10, tok/s |
|---:|---|---:|---:|---:|---:|---:|
| 12 | vLLM | 374.76 | 2.327 | 14.548 | 36.75 | 21.65 |
| 12 | SGLang | 497.37 | 1.667 | 8.229 | 20.64 | 33.01 |
| 16 | vLLM | 376.73 | 2.790 | 17.179 | 49.54 | 15.96 |
| 16 | SGLang | 480.44 | 2.042 | 9.764 | 27.71 | 17.48 |
| 24 | vLLM | 379.48 | 5.455 | 30.787 | 74.48 | 9.58 |
| 24 | SGLang | 365.35 | 5.451 | 30.015 | 68.30 | 8.16 |

Values are rounded from the [published Episode 01 projection](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/dashboard/src/data/site-v2/episode-1.json).

Both deployments met the decode floor at 12 users. Both missed it at 16 and 24.

At 16 users, SGLang recorded more output, lower median TTFT, lower p95 TTFT, and lower median TPOT. Nevertheless, its decode p10 remained below the declared floor. A favorable comparison with another deployment does not establish that a deployment meets its own acceptance criteria.

At 24 users, the throughput ordering reversed: vLLM recorded 379.48 tokens per second, compared with SGLang’s 365.35. Both median first-token waits were approximately 5.45 seconds. Those observations do not establish a universal engine ranking.

The percentage calculation is straightforward, provided the denominator is explicit:

\[
\Delta\%=100\frac{\text{subject}-\text{baseline}}{\text{baseline}}
\]

For SGLang relative to vLLM at 16 users:

\[
100\frac{480.4362-376.7271}{376.7271}\approx27.5\%
\]

That calculation expresses an observed difference. It is not a confidence interval or a significance test.

## The median is not the whole experience

At 24 users, approximately 5.45-second median TTFT coexisted with p95 values of 30.787 seconds for vLLM and 30.015 seconds for SGLang. A p95 is an upper-tail threshold: approximately 95% of applicable measured observations fall at or below it. It is neither the maximum nor a guarantee about future requests.

Decode p10 looks in the opposite direction because higher speed is preferable. It summarizes the slow side of the speed distribution. It cannot be manufactured by taking the reciprocal of published median TPOT.

These tails identify an experience problem worth investigating. They do not identify its cause by themselves. Queueing, prefill scheduling, decode interruptions, transport, and client behavior need compatible measurements before time can be attributed to them.

GPU utilization and runtime queue gauges provide context. High utilization does not identify a particular limiting resource, and runtime-native cache gauges cannot be ranked when their definitions differ. Episode 01 explicitly retains those comparability limits in its [public evidence contract](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/dashboard/src/data/episode-1-public.v1.json).

## How to read the measurements

The current repository contract makes the timing boundaries explicit. Let \(s\) be actual request-send time, \(f\) first non-empty content time, \(l\) last non-empty content time, \(d\) terminal stream validation time and \(N\) the exact delivered output-token count. With compatible time units:

\[
TTFT=f-s,\qquad
TPOT=\frac{l-f}{N-1}\quad(N\ge2)
\]

\[
E2E=d-s=TTFT+(N-1)TPOT+(d-l)
\]

TTFT includes whatever transport, queueing, prompt processing and first-content delivery occur before \(f\); it cannot separate them by itself. The final \(d-l\) term preserves terminal-stream and usage-validation overhead. These are per-request identities, not a license to add independently computed medians.

A streamed content event can contain several tokens. Client inter-chunk gaps are therefore not automatically server token-generation intervals. These definitions describe the [current measurement contract](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/docs/metric-definitions.md); they do not retroactively recover missing Episode 00 arrival traces or its original harness.

Aggregate output rate has a different denominator:

\[
R_{\text{output}}
=\frac{\sum_{i\in\text{successful cohort}}N_i}{T_{\text{cohort}}}
\]

The numerator adds output across requests. TPOT describes one request's average post-first-token pace. Inverting median TPOT does not produce deployment throughput or decode p10. Metric names alone are not enough: implementations may differ in event boundaries, token counts and benchmark duration, as [NVIDIA's metric documentation](https://docs.nvidia.com/nim/benchmarking/llm/metrics) also explains.

A credible comparison needs more than formulas.

First, fix the work contract: model and tokenizer identity, workload, output rules, sampling, load process, and warm-up policy. Where historical provenance is missing, state that absence.

Second, verify delivered work. An identical output cap does not guarantee identical output. Completion validity also does not demonstrate that an answer is useful or correct.

Third, preserve failures and denominators. At 12, 16 and 24 users respectively, Episode 01 records valid/total request counts of 641/642, 665/666 and 662/662 for vLLM; SGLang records 747/747, 889/889 and 601/601. All six published points are marked valid. These counts support the validity check, but the export does not establish that every metric percentile uses exactly the same applicable population. [Published counts](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/dashboard/src/data/site-v2/episode-1.json).

Fourth, distinguish observation from attribution. A deployment comparison includes the behavior of its complete configuration. Without controlled treatment arms, it cannot isolate an engine-only effect or attribute an improvement to a particular optimization.

Finally, retain repetitions and uncertainty. Many requests within one run do not replace independent repeated runs. Aggregate percentiles cannot recover the missing request distribution, and averaging previously computed percentiles does not produce a pooled percentile.

## What would establish useful capacity?

For a future experiment, let \(g_i=1\) only when request \(i\) satisfies all declared applicable validity, quality, and latency requirements. Then:

\[
G_{\text{tokens}}
=\frac{\sum_iN_i g_i}{T}
\]

This counts qualifying delivered output using the declared measurement denominator. The current public evidence does not provide the joint per-request outcomes needed to calculate that result. Multiplying throughput by a pass-rate estimate would not repair the gap.

Capacity requires another step: a declared arrival process, offered and achieved rates, client scheduling delay, sustained behavior, failures, and explicit service objectives. Closed-loop clients submit subsequent work as earlier work completes, so a slower service can also slow the incoming workload. Episode 01 did not perform an open-loop offered-rate sweep to locate maximum SLO-qualified goodput.

The concise conclusion is: **tested loads only; maximum sustainable request rate not measured.** Both deployments passed the decode floor at 12 users, but that does not make 12 users a measured maximum or a production-capacity certification.

## What this experiment actually cost

The bill and the benchmark window answer different questions. Provider billing includes paid activity outside successful measurements; a rate multiplied by a planned window is an estimate, not an invoice allocation.

| Activity | Amount, USD | Evidence and interpretation |
|---|---:|---|
| Episode 00 broader campaign | **11.8311** | Observed billing: 11.6870 GPU + 0.1441 storage; includes an earlier RTX PRO 6000 trial and the H100/A100 campaign activity. |
| Earlier RTX PRO 6000 trial | 4.2096, included above | Prior trial, not part of the published H100 comparison. |
| H100/A100 campaign activity | 7.6216, included above | Includes measurement, preflight and failed attempts; not a per-runtime or successful-run allocation. |
| Retained, unattributed AgentBench campaign billing | 19.0664 | Observed billing buckets: 18.8696 GPU + 0.1968 storage. Attribution to the six published Episode 01 measurements remains unresolved; this is not their established total cost. |
| Six published Episode 01 measurements | **Not established** | No reconciled billing allocation covering those measurements is available for this article. |
| Offline fixture rehearsal and local dashboard | **0 provider charge** | No provider resources are used. Local hardware and electricity are not estimated. |

Source: the reviewed [provider-billing summary](https://github.com/KVSDURGASURESH/token-by-token/blob/8db391468aebdc7a5c3b30c7b2a265be96803e1b/data/public/runpod-billing-summary.json) and [cost ledger](https://github.com/KVSDURGASURESH/token-by-token/blob/8db391468aebdc7a5c3b30c7b2a265be96803e1b/docs/cost-evidence.md). The two “included above” rows must not be added to the Episode 00 total again.

The newer billing read supersedes the earlier $2.19 CLI-debit note and $4.128 balance-derived trial figure. The separate $3.21 comparable-window calculation is rate × declared protocol time—not an observed bill, an additional charge, or a defensible allocation to these six results. We cannot yet use these records to rank runtime cost per successful request or per million qualifying tokens.

## What readers can reproduce

Episode 00 lacks the exact historical harness commit, immutable runtime images, raw repetitions, and other provenance. Episode 01 publishes aggregate observations while withholding deployment details. Its public export reports throughput alongside the measurement window, but does not retain enough numerator and cohort-boundary information to independently reconstruct that throughput. We therefore report the recorded rate; we do not infer total generated tokens by multiplying it by 300.

The open publication is a way to inspect evidence and reasoning. Exact execution replay remains constrained by what the historical record retained and what is approved for release.

The public dashboard follows the same boundary. It reads committed static aggregates. Grafana and VictoriaMetrics support source-stage validation and preparation; readers do not need those services to load the published dashboard. Selecting a load changes the view, not the experiment. [Static publication lifecycle](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/README.md).

The public client's offline self-test validates contracts and bundle plumbing. It performs no inference and contributes no benchmark result. A passing fixture test is not evidence of serving performance, agent task quality or an independently reproduced benchmark. [Client status at the cited revision](https://github.com/KVSDURGASURESH/token-by-token/blob/02dc9f2749e860abdae375861923f86047056591/client/README.md).

## The next experiment, not the next leaderboard

The [maintained roadmap](https://github.com/KVSDURGASURESH/token-by-token/blob/main/docs/roadmap.md) owns the future sequence: equal-work controls, isolated optimization tests and saturation under declared service objectives. Those are planned experiments, not results implied by this post. The broader [capstone portfolio](https://github.com/KVSDURGASURESH/token-by-token/blob/main/docs/capstone-projects.md) separates serving reliability, evidence-grounded RAG, and release/recovery work.

Episode 00 taught us to check the work. Episode 01 taught us to check the target. The next useful comparison must do both—and retain enough evidence for someone else to challenge the conclusion.

For additional conceptual reading, Shirin Khosravi Jam and guest author Dev Jadhav, writing as MLwithDev, explain prefill, decode, and resource constraints in [*LLM Inference 101*](https://jamwithai.substack.com/p/llm-inference-101). Thank you to both for making those mechanisms accessible.

---

## Editorial checks — not part of the published article

- Reconcile the Episode 01 billing window with the matched H200 measurements before replacing “not established” with a study total. Do not silently reuse the campaign label from the source ledger as proof of allocation.
- Resolve the public workload-provenance label against the retained experiment record. “Multi-turn session replay” is intentional here; this draft does not assert either a synthetic-only corpus or an approved release of a particular dataset mixture.
- Confirm that the cited evidence revision is reachable publicly before publishing. Local drafts and current uncommitted client changes are not a public release.
- Confirm both intended identities before using the Vishakha/Aishwarya acknowledgement below. Omit it if confirmation is unavailable.

Proposed acknowledgement wording:

Thank you to [Vishakha Sadhwani](https://www.linkedin.com/in/vsadhwani) and [Aishwarya Srinivasan](https://www.linkedin.com/in/aishwarya-srinivasan) for sharing educational work on AI infrastructure and LLM systems, and to Shirin Khosravi Jam and Dev Jadhav (MLwithDev) for [*LLM Inference 101*](https://jamwithai.substack.com/p/llm-inference-101).
