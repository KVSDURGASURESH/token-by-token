---
status: "DRAFT / NOT PUBLISHED"
evidence_revision: "8db391468aebdc7a5c3b30c7b2a265be96803e1b"
---

27.5% more output throughput. Still below the decode target.

At 16 simulated users, the recorded SGLang deployment delivered 480.44 output tokens/s; vLLM delivered 376.73. Each ran on one H200.

Yet both missed the declared decode floor: p10 ≥ 20 tokens/s. Their slow-tail decode speeds were 17.48 and 15.96 tokens/s, respectively.

“More tokens” and “meets the target” are different findings.

That's why I'm building Token by Token — Inference Lab: a public learning series about what serving measurements actually let us conclude.

Episode 00 asked: are we comparing the same work?

In one H100 workload, vLLM recorded 48.9% higher output throughput alongside 19.8% higher median time per output token, relative to SGLang. In the longest stress workload, the arms delivered different output lengths despite the same cap. That prevents an equal-work efficiency claim.

Episode 01 asked: does more output meet the experience target?

We replayed multi-turn sessions at 12, 16 and 24 users, with two session slots per user, a 120-second warm-up and 300-second measured windows. Both deployments met the decode floor at 12 users; neither did at 16 or 24. At 24, both recorded p95 first-token waits of roughly 30 seconds.

These are tested closed-loop loads—not a measurement of maximum sustainable request rate, agent task quality or an engine-only causal effect. The two episodes are separate experiments, not an H100-versus-H200 comparison.

Cost matters too: Episode 00's broader campaign billed $11.83, including trials/setup and storage. The cost of the six Episode 01 measurements is not yet reconciled. Viewing the dashboard locally incurs no provider charge.

Episode 01 benchmarking harness powered by AgentBench from Mirastack Labs. The harness is private; the public learning repository is separate.

Next: equal-work controls and experiments that measure useful work meeting declared service objectives.

Explore the [evidence and methodology](https://github.com/KVSDURGASURESH/token-by-token). Which would rule out a deployment for your application: first-token wait, streaming pace or tail latency?

---

## Editorial checks — not part of the LinkedIn post

Use the article's pinned evidence links for the claim audit. The 27.5% comparison uses vLLM as denominator; the Episode 00 percentages use SGLang. Do not present the $19.0664 October 4–5 billing window as the six Episode 01 measurements' established cost. Keep workload wording neutral until public provenance is reconciled.

The post above excludes this note and the optional acknowledgement below. Confirm both intended identities before using it; omit it if confirmation is unavailable. Recheck the platform character count if adding it.

Thank you to [Vishakha Sadhwani](https://www.linkedin.com/in/vsadhwani) and [Aishwarya Srinivasan](https://www.linkedin.com/in/aishwarya-srinivasan) for sharing educational work on AI infrastructure and LLM systems, and to Shirin Khosravi Jam and Dev Jadhav (MLwithDev) for [*LLM Inference 101*](https://jamwithai.substack.com/p/llm-inference-101).
