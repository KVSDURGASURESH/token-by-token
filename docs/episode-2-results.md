# Episode 02: completed run, no qualified winner

The recorded comparison of **vLLM 0.29.0 and SGLang 0.5.20** completed six paired blocks on one NVIDIA H200. Both served Qwen2.5-32B-Instruct at the same pinned revision, sequentially with a fresh process per block, two concurrent workflows, and 20-second request deadlines. The profile is **native performance defaults + tool compatibility**: vLLM uses Hermes and SGLang uses qwen25 for required tool calls. These compatibility flags are explicit; this is not a claim about unmodified stock tool serving.

All **144 planned measured requests** were sent and reached terminal streams; **12 warmups** are excluded. Each engine qualified **66 of 72 requests** and completed **42 of 48 workflows**. Each had six output-heavy semantic failures, with explanation lengths below the frozen 12–18-word requirement. There were no dropped, blocked, or cancelled positions. A terminal response does not necessarily satisfy the quality contract.

| Qualified metric (ms) | Applicable n per engine | vLLM p50 / p95 | SGLang p50 / p95 |
|---|---:|---:|---:|
| Request E2E | 66 | 295.956 / 1620.601 | 295.650 / 1585.175 |
| Content TTFT | 54 | 141.060 / 1142.097 | 136.530 / 972.156 |
| Content TPOT | 54 | 15.126 / 35.646 | 16.039 / 50.814 |
| First tool event | 12 | 285.612 / 296.194 | 295.108 / 333.436 |
| Workflow E2E | 42 | 747.177 / 1741.351 | 746.046 / 1623.930 |

Metrics include only qualified observations. The 12 tool-only replies per engine have no content TTFT/TPOT and are counted separately in tool-event latency. Percentiles are pooled with linear interpolation. All groups have fewer than 1,000 applicable observations: **p95 is the headline; p99 is descriptive, not eligible for a headline comparison**.

| Class | Qualified / planned per engine | vLLM E2E p50 / p95 (ms) | SGLang E2E p50 / p95 (ms) |
|---|---:|---:|---:|
| short | 6 / 6 | 1307.933 / 1784.706 | 1540.735 / 2080.036 |
| long_prefill | 6 / 6 | 1618.991 / 1865.983 | 1562.979 / 2163.748 |
| output_heavy | 0 / 6 | Unavailable | Unavailable |
| structured | 6 / 6 | 295.956 / 328.100 | 295.650 / 334.722 |
| code_reasoning | 6 / 6 | 348.200 / 360.462 | 359.520 / 372.170 |
| conversation | 12 / 12 | 221.685 / 241.303 | 220.822 / 242.293 |
| tool_call | 12 / 12 | 359.923 / 504.496 | 363.852 / 508.164 |
| agent_chain | 18 / 18 | 235.235 / 485.818 | 231.522 / 450.462 |

The formal comparison is **rejected**, with **no winner**. Both engines fail the frozen quality and error-rate safeguards, and delivered-output differences exceed the equivalence tolerance. The primary vLLM-minus-SGLang p95-minus-p50 E2E-gap estimate is **35.119 ms**, with a paired whole-block 95% interval **[−349.512, 153.922] ms** (six pairs, 2,000 resamples). The interval includes zero. These latency values are descriptive; they do not establish a faster engine for equivalent qualified work.

Export, permanent deletion, inventory absence, and direct not-found checks are verified. Billing is **provisional**. The compiled 50-minute maximum estimate was **$4.43**; measured-window cost and resource attribution remain unavailable. The per-engine projection records its pre-teardown cleanup snapshot; the [evidence index](../public-data/evidence/episode-2/index.json) separately records the later verified terminal disposition and redacted receipt digest.

The initial offline validator rejected null optional ID/name fields in real SGLang tool-continuation events. A narrow post-run validator correction accepts those nulls while preserving all identity, argument, timestamp, usage, and quality checks. Raw measurements were unchanged. The evidence index records both the measured public-source digest and the later analysis-source digest.

The [vLLM summary](../public-data/evidence/episode-2/vllm-summary.json), [SGLang summary](../public-data/evidence/episode-2/sglang-summary.json), and [comparison](../public-data/evidence/episode-2/comparison.json) are validated against the closed public aggregate schema. They omit raw responses, event streams, physical identifiers, account balances, and operator credentials. Earlier incomplete attempts are excluded from these results.
