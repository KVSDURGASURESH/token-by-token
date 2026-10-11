# Experiment planner

Open `#experiment-planner` in the local dashboard, or choose **Design experiment** from an episode. The planner covers canonical Episodes 1–16 with versioned templates for serving, model, training, decision, topology, platform and release work.

The planner is deliberately unable to launch anything. It has no Run button, provider adapter, endpoint field, credential input, arbitrary flag field or shell-command path. Every configuration permanently records:

```json
{
  "planning_only": true,
  "execution_ready": false,
  "execution_authorized": false
}
```

An exported JSON file is an immutable planning snapshot. Its SHA-256 digest is computed over canonical configuration content; timestamps and the digest envelope are not included. This is a **planning configuration digest, not paid-execution approval**. Import verifies the digest, the closed shape and semantic constraints, then opens a new editable draft.

## Interpretation

- **Requested** means a setting belongs in a proposed experiment arm.
- **Preflight required** means support is unknown for the selected engine version, image, model and GPU.
- **Measured** is never assigned by the planner. Only retained experiment evidence can earn that label.
- Unknown hourly price displays as **Unavailable**, never zero. Desired budget is not an enforced spending cap, and cost per million tokens cannot be derived without measured throughput.

Continuous batching and paged KV memory are informational engine capabilities unless the pinned runtime exposes a verified control. Smaller-model and distillation choices create new model or training artifacts and require a new quality contract. Speculative decoding promises no gain; draft/target compatibility must be preflighted.

The portable shape is defined by [`schemas/experiment-plan.schema.json`](../schemas/experiment-plan.schema.json). Browser validation is mirrored by the provider-free validator in [`scripts/experiment_plan.py`](../scripts/experiment_plan.py).

## Episode-numbering compatibility

The current template registry uses `episode-catalog.v2`. It moves the former Episodes 8–15 to 3–10 and the former Episodes 3–7 to 11–15; Episodes 0–2 and 16 are unchanged. The exact old-to-current map is published in [`dashboard/src/data/episodes.json`](../dashboard/src/data/episodes.json).

Historical handoffs, evidence and exported planner snapshots keep the episode number and template identity recorded when they were created. Do not relabel those artifacts in place. A planner snapshot created against the former catalog may fail current template validation; migrate it deliberately with the published map and export a new draft, while retaining the original snapshot as immutable provenance.
