# Contributing to Token by Token — Inference Lab

This directory is a local repository candidate and is not yet licensed for
public contribution. The process below documents the intended review contract;
external contributions should open only after the owner selects explicit terms
for code, data, and documentation.

## Reproduce before proposing

Run the zero-cost checks first:

```bash
python3 scripts/verify_bundle.py data/public
python3 scripts/rehearse_workflow.py --output /tmp/inference-lab-episode-0
python3 scripts/verify_bundle.py /tmp/inference-lab-episode-0
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
```

Do not commit generated `dashboard/dist/`, dependency directories, raw request
records, prompt or output payloads, credentials, provider identifiers, billing
records, or local environment files.

## Propose one measurable change

An optimization proposal should state:

- one changed variable and a paired baseline;
- immutable runtime image, model, tokenizer, prompt, harness, and dependency
  identities;
- the same GPU offer and physical GPU for the paired arms;
- randomized or counterbalanced arm order and at least three repetitions;
- requested and delivered output lengths plus stop-reason distributions;
- success, error, quality, latency, throughput, and predeclared goodput gates;
- a budget, teardown horizon, and evidence-retention plan.

Keep proposed work separate from measured results. A GitHub issue, pull request,
or local manifest does not authorize a paid run. Before any provider resource is
created, the owner must review the complete current manifest and compiled plan
and give the exact approval phrase bound to that plan digest and maximum charge.
Any change to the image, GPU, price, workload, runtime, arm, duration, or cost
requires a new plan and approval.

Every authorized paid workflow must permanently delete every created resource
and verify deletion with a fresh provider-side read before claiming completion.
Publication remains a separate action.

## Evidence changes

`data/public/` is an immutable checksum-bound unit. Do not edit one file in
place. Produce a new reviewed snapshot, rebuild its checksum manifest, run the
strict verifier, and explain all provenance and comparability changes. Never
publish raw private observations as a shortcut.

Pull requests should state the problem, resulting behavior, evidence boundary,
commands run, and any unresolved ownership or dependency issue.
