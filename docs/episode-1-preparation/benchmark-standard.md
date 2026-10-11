# Episode 1 benchmark standard

## Decision

Episode 1 will use established upstream benchmark definitions for claims that
are meant to be comparable with other inference work:

1. **Online serving:** the ShareGPT workload shape exposed by
   `sglang.bench_serving`, using the same harness against both the SGLang and
   vLLM OpenAI-compatible endpoints. This is the cross-runtime latency and
   throughput benchmark.
2. **Model quality:** the `gsm8k` task from EleutherAI's
   `lm-evaluation-harness`, using its declared five-shot, deterministic
   generation and exact-match configuration. This is a parity guard, not a
   serving-throughput workload.
3. **Application conformance:** the existing 24 synthetic JSON-extraction
   cases remain a small Episode 1 acceptance test. They must be reported as a
   project-specific conformance check, never as a standard benchmark or a
   leaderboard-quality score.

The serving and quality results must remain separate. They answer different
questions and must not be collapsed into a single score.

## Frozen inputs required before a paid run

The execution plan must bind all of the following before it can be presented
for approval:

- exact SGLang benchmark package version and source commit;
- exact `lm-evaluation-harness` package version and source commit;
- exact ShareGPT file revision, byte length, and SHA-256 digest;
- exact GSM8K dataset revision and task-YAML SHA-256 digest;
- Qwen tokenizer/model revision and chat-template digest;
- seed, request count, arrival policy, concurrency, warmups, output cap,
  timeout policy, and cache policy;
- the selected `lm-eval` task name, task version, few-shot count, filter name,
  decoding settings, and complete sample count.

An automatically downloaded moving dataset or an unpinned `main` branch is not
acceptable evidence. If any bound byte or setting changes, the benchmark is a
different run and needs a newly compiled plan.

## Pilot profile

For the first bounded run, use ShareGPT with deterministic selection, an output
cap of 128 tokens, unlimited request arrival, and the already-declared
concurrency levels. Preserve per-request TTFT, end-to-end latency, output-token
count, failure status, and the common wall interval used for throughput. The
exact prompt selection must be exported as opaque row identities plus hashes;
raw conversation text stays private.

Run the complete `gsm8k` test split once per runtime configuration with the
same model revision and decoding contract. A reduced slice may be used only as
a local smoke test and must be labeled as such; it cannot be published as a
GSM8K result.

## Local readiness exercise

The upstream artifacts and adapter protocol are pinned in
`fixtures/episode1/benchmark-standard.json`. The zero-cost exercise verifies
all artifact bytes, reproduces the SGLang 0.5.20 ShareGPT selection with the
frozen tokenizer, and runs the strict-match evaluator over all 1,319 GSM8K
test rows. This is readiness evidence, not a model-result claim: provider-side
inference remains gated by the digest-bound execution plan, explicit maximum
charge, and user approval.

```bash
PYTHONPATH=src .venv/bin/python scripts/exercise_episode1_standard.py \
  --manifest fixtures/episode1/benchmark-standard.json \
  --sharegpt /path/to/ShareGPT_V3_unfiltered_cleaned_split.json \
  --gsm8k-test /path/to/gsm8k-test.jsonl \
  --gsm8k-train /path/to/gsm8k-train.jsonl \
  --gsm8k-task-config /path/to/gsm8k.yaml \
  --tokenizer /path/to/pinned-qwen-tokenizer \
  --output /private/path/benchmark-standard-exercise.json
```

The current authored fixed-token cells and 24 extraction tasks remain useful
for harness validation, failure-path testing, and the application gate. They
are not the standard comparison workload.

Primary references:

- SGLang serving benchmark guide: <https://github.com/sgl-project/sglang/blob/main/docs/docs/developer_guide/bench_serving.mdx>
- SGLang ShareGPT loader: <https://github.com/sgl-project/sglang/blob/main/python/sglang/benchmark/datasets/sharegpt.py>
- lm-evaluation-harness GSM8K task: <https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/gsm8k/gsm8k.yaml>
