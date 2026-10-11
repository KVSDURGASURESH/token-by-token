# Author an execution-ready plan

`examples/execution-manifest.template.json` is the complete one-runtime vLLM
shape for the recommended six-cell experiment. It is intentionally invalid:
every `REQUIRED_…` value must come from current, private evidence. A template
file is never authorization and cannot be used to create a resource.

1. Copy both execution templates into a private directory outside the repo.
2. Resolve the derived image to an immutable OCI digest. Record the exact GPU
   offer, secure-cloud region/datacenter, current price, account balance,
   ancillary billing states, and evidence timestamps. Evidence expires after
   15 minutes for plan compilation.
3. Replace every `REQUIRED_…` value. A billed ancillary component uses only
   `{"status":"billed","hourly_usd":"…"}`; an included or zero component
   uses only `{"status":"included|zero","amount_usd":"0"}`.
4. Generate the exact workload and tokenizer contract with the same code the
   live runner enforces. This may download the pinned tokenizer from its model
   repository, but it creates no paid compute resource:

```bash
python3 scripts/generate_workload_contract.py \
  --model Qwen/Qwen2.5-32B-Instruct \
  --model-revision 5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd \
  --matrix 128:1,128:32,2048:4,2048:32,8192:8,8192:32 \
  --request-count 128 --repetitions 3 --seed 20260920 \
  --transformers-version 5.17.0 \
  > PRIVATE/workload-contract.json
```

   Copy its `dataset`, `prompt_cells`, tokenizer fields, and chat-template hash
   into the private manifest. Preserve the output with private evidence.
5. Compile without provider or paid-resource access:

```bash
python3 scripts/compile_plan_cli.py \
  --manifest PRIVATE/execution-manifest.json \
  --live-inputs PRIVATE/execution-live-inputs.json \
  --output PRIVATE/execution-plan.json
```

The compiler validates the full contract, derives the budget cap, writes a
canonical plan digest, and prints an exact approval phrase. Review the compiled
plan in full. Resource creation is allowed only after the user replies with
that exact current digest-bound phrase and maximum charge.

The public runner independently revalidates the plan schema, digest, approval
phrase, one-runtime allocation, dependency version, workload, sampling,
warmups, repetitions, and per-cell timeouts before traffic. For SGLang, make a
separate one-runtime manifest and allocation, changing its runtime record,
derived image digest, fully verified launch arguments, and runtime ID. These
independent allocations are not paired same-GPU evidence.
