# Episode 1 tokenizer-only preflight

Observed locally on 2026-09-22 using public tokenizer/configuration assets for `Qwen/Qwen2.5-32B-Instruct` revision `5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd`. No weights, image layers, provider access or paid resources were used. This proves a prompt construction recipe, not runtime equivalence or model quality.

The final isolated check used Python 3.12.3, the candidate's pinned Transformers 5.17.0, tokenizers 0.23.2 and Jinja2 3.1.6. This loads `Qwen2Tokenizer` with `is_fast=false` and returns `BatchEncoding`; normalize its `input_ids` before hashing/counting. An earlier check used Transformers 4.57.1 / tokenizers 0.22.2 with `Qwen2TokenizerFast`. Both produced identical template bytes and complete input-ID arrays at both target lengths. Bind and verify the versions actually used by the final harness and both servers separately. Loading was offline after the five public assets were downloaded, with remote code disabled.

| Asset | SHA-256 |
|---|---|
| `config.json` | `9c6772f138ef9e5b3d1c18f2c87e451bbc01f5f1a4eabb36f9bf4f53829b903e` |
| `tokenizer.json` | `c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539` |
| `tokenizer_config.json` | `5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583` |
| `vocab.json` | `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` |
| `merges.txt` | `599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3` |

The UTF-8 chat-template SHA-256 is `cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f`. Source assets are at `https://huggingface.co/Qwen/Qwen2.5-32B-Instruct/resolve/5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd/` followed by the listed asset name.

Construct one user message whose content starts with `Extract a concise answer from this deterministic synthetic service note. Synthetic benchmark content:`. Render with `apply_chat_template(tokenize=True, add_generation_prompt=True)`. Its full templated base is 44 tokens. Appending the constant string `" x"` exactly `target - 44` times reaches both targets. Repeated rendering was identical, and direct encoding of the rendered template with `add_special_tokens=False` produced identical IDs.

| Target input | Maximum input plus output | Canonical JSON input-ID SHA-256 |
|---|---:|---|
| 512 | 640 | `22c030f9b84e937cb921ba79597ab2ac6ac73b93c9ee87c3d6de0d576ace2426` |
| 2048 | 2176 | `701f3d70021261d26c248b5247bc5f63408fbd4d305296fc98c43de435868a2b` |

Canonical JSON uses sorted keys, separators `(',', ':')`, `ensure_ascii=False`, and UTF-8 bytes. These hashes apply only to these exact messages and options. Any corpus/template/version change requires regeneration. The candidate's original numbered filler skipped 510→514 and 2046→2050 with this tokenizer; tests using whitespace tokenization did not expose it.

The local review artifacts are retained at `/private/tmp/episode1-tokenizer-preflight/`: `evidence.json` includes authored messages, rendered text, exact token IDs and asset hashes; `generate_evidence.py` reproduces the check using the isolated `venv`. The Transformers 5.17.0 evidence SHA-256 is `ffc132d41b26261f6e5fa7c366140ea29970eea67f07774d4af7dccfec49bcfd`. The original 4.57.1 evidence is preserved as `evidence-transformers-4.57.1.json`, SHA-256 `4c0cd16a2d08ab8baf93ab5eca453d1cfaac2c51b6cd6baa79ebfbfaa2fbffd9`. This temporary evidence is an independent review input. The repository implementation must provide its own reproducible generator and bind the artifacts it actually consumes.
