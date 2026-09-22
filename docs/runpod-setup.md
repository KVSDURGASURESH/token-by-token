# Runpod setup, GPU selection, and cost control

This is the canonical setup guide for a fresh measurement. It does not
authorize a provider call. Try the README's [zero-cost quickstart](../README.md#zero-cost-quickstart)
and local dashboard first; they use the checked-in offline fixture and create
no Runpod resource.

Runpod controls and prices can change. Before a paid run, confirm every field
in the current console and installed CLI rather than copying an old screenshot
or price:

- [Runpod Pods console](https://www.console.runpod.io/pods)
- [Get started with Pods](https://docs.runpod.io/get-started)
- [Choose a Pod](https://docs.runpod.io/pods/choose-a-pod)
- [Manage Pods](https://docs.runpod.io/pods/manage-pods)
- [Manage templates](https://docs.runpod.io/pods/templates/manage-templates)
- [SSH access](https://docs.runpod.io/pods/configuration/use-ssh)
- [Port exposure](https://docs.runpod.io/pods/configuration/expose-ports)
- [Storage types](https://docs.runpod.io/pods/storage/types)
- [`runpodctl pod` reference](https://docs.runpod.io/runpodctl/reference/runpodctl-pod)

The runtime sources are the [vLLM Docker guide](https://docs.vllm.ai/en/latest/deployment/docker/),
[SGLang installation guide](https://github.com/sgl-project/sglang/blob/main/docs/docs/get-started/install.mdx),
and [SGLang v0.5.20 release](https://github.com/sgl-project/sglang/releases/tag/v0.5.20).

## 1. Choose the learning path before choosing a GPU

The recorded Episode 0 path is Qwen/Qwen2.5-32B-Instruct at BF16 with a
16,384-token context on one H100 80GB per runtime arm. Use one H100 80GB for a
fresh reproduction-shaped arm. Do not treat a different GPU, precision, model,
context, or runtime version as the same experiment.

Model weights are only part of VRAM demand:

```text
required VRAM = model weights + KV cache + runtime/CUDA allocations
              + temporary workspaces and safety headroom
```

The 32B BF16 weights alone are roughly 64GB. That leaves limited space on an
80GB GPU for KV cache and runtime overhead, so startup at 16K context still has
to be proved. If it does not fit without changing a bound setting, fail the arm
and create a new plan.

For a lower-cost learning run, choose a smaller or quantized model and author a
new manifest. Runpod's current guidance lists 24GB-class GPUs as a starting
point for many quantized 7B–13B models and 48–80GB-class GPUs for 30B–70B
models. Treat those ranges as screening guidance, then check the model's own
requirements and leave memory headroom. These alternatives have **not** been
benchmarked equivalently by this repository and cannot reproduce its H100/Qwen
32B BF16 results.

| Goal | Planning starting point | Meaning in this project |
|---|---|---|
| Follow the recorded configuration | 1 × H100 80GB, Qwen 32B, BF16, 16K context | Reproduction-shaped new arm; still not the historical machine or image |
| Learn the workflow with a small BF16 model | 24GB-class GPU for roughly 7B/8B, after a VRAM check | New experiment with a new manifest and labels |
| Learn with a quantized 7B–13B model | 24GB-class GPU, subject to model requirements | New quantized experiment; not comparable to Episode 0 |
| Try a quantized 30B/32B model | 48GB or larger, after a VRAM check | New quantized experiment; capacity is not guaranteed |

Record the exact GPU variant, VRAM, offer ID, cloud type, data center, driver
and CUDA compatibility, availability, and every displayed charge. Do not mix
PCIe, SXM, NVL, cloud classes, data centers, or host configurations inside a
claimed paired comparison.

## 2. Prepare the account and workstation

1. Sign in at the [Pods console](https://www.console.runpod.io/pods). Complete
   account and billing setup only if you intend to prepare a paid plan.
2. Install Python 3.12 and `runpodctl` using Runpod's current instructions.
   Configure the CLI through its supported credential store. Never put a
   Runpod API key in a manifest, Pod variable, command, screenshot, or log.
3. Create an SSH key if needed and add its **public** key in Runpod account
   settings, or use `runpodctl ssh add-key`. Keep the private key local. Runpod
   documents that its basic SSH connection does not provide SCP/SFTP; full SSH
   requires a public IP. If a public IP changes the charge, it must be in the
   plan.
4. Create the local client environment from the repository root:

   ```bash
   python3 -m venv .venv-live
   . .venv-live/bin/activate
   python3 -m pip install '.[live]'
   python3 -c 'import importlib.metadata; print(importlib.metadata.version("transformers"))'
   ```

   The final command must print `5.17.0`. This install may contact PyPI but
   creates no provider resource. Record the resolved environment privately and
   bind Python 3.12 and Transformers 5.17.0 in the execution manifest.

The recorded Qwen revision is public, so no Hugging Face token is normally
needed. If upstream policy changes, inject a provider secret and redact it from
all evidence.

## 3. Resolve the recommended future images

Episode 0 did not preserve its container image digests or Runpod template IDs.
The following are **future-run recommendations**, not recovered historical
provenance:

| Arm | Official versioned base tag | Historical image? |
|---|---|---|
| vLLM | `vllm/vllm-openai:v0.29.0` | Unknown; do not claim it is |
| SGLang | `lmsysorg/sglang:v0.5.20` | Unknown; do not claim it is |

The small operator Dockerfiles under `containers/` inherit those bases, copy
the benchmark tools, clear the upstream entrypoint, and idle until the reviewed
server command starts. Build one private image per arm, push it to the approved
registry, and resolve its platform-specific `linux/amd64` digest:

```bash
docker build --platform linux/amd64 \
  -f containers/vllm/Dockerfile \
  -t REGISTRY/OWNER/inference-lab-vllm:0.29.0-episode0 .
docker build --platform linux/amd64 \
  -f containers/sglang/Dockerfile \
  -t REGISTRY/OWNER/inference-lab-sglang:0.5.20-episode0 .
docker push REGISTRY/OWNER/inference-lab-vllm:0.29.0-episode0
docker push REGISTRY/OWNER/inference-lab-sglang:0.5.20-episode0
docker buildx imagetools inspect REGISTRY/OWNER/inference-lab-vllm:0.29.0-episode0
docker buildx imagetools inspect REGISTRY/OWNER/inference-lab-sglang:0.5.20-episode0
```

Never substitute `latest`, `dev`, `nightly`, or a different runtime version.
Bind the derived image digest, architecture, and any non-secret registry
credential ID in the private plan. A changed base, Dockerfile, dependency, or
derived digest requires a new plan. Local builds and image inspection are
preflight checks; loading the model on a GPU is part of the paid run.

## 4. Create the project template

Create one **private custom template** per runtime. This is the default template
for this project; do not use an unidentified historical or generic template.
From the [Pods console](https://www.console.runpod.io/pods), open **Templates**
or **My Templates**, choose **New Template**, and enter the following settings.
Exact labels may change, so compare them with the current
[template documentation](https://docs.runpod.io/pods/templates/manage-templates).

| Template field | Project setting |
|---|---|
| Name | `inference-lab-vllm-0.29.0` or `inference-lab-sglang-0.5.20` |
| Visibility | Private |
| Compute type | NVIDIA GPU |
| Container image | The corresponding derived image at the reviewed `sha256` digest |
| Container start command | Leave blank; the derived image supplies `sleep infinity` |
| Container disk | `APPROVED_GB`, sized for the image, tools, and model cache |
| Volume disk | `0` unless its size, mount, lifetime, and charge are explicitly approved |
| Network/global volume | None unless separately approved for its full lifetime |
| HTTP ports | None |
| TCP ports | None; enable SSH with Runpod's SSH control during deployment |
| Environment variables | None containing secrets; use provider secrets if a reviewed run needs one |
| Registry authentication | The approved non-secret provider credential ID, if required |

The API server and metrics endpoint listen only on `127.0.0.1:8000` inside the
Pod and the workstation reaches them through SSH forwarding. Do not add port
8000 to template HTTP/TCP exposure. If a future design uses Runpod's HTTP proxy
or any public port, bind it in a new plan and apply authentication; the current
runbook does not support that mode.

Runpod documents that the container disk is erased when a Pod stops. A Pod
volume mounted at `/workspace` survives stop/restart but is deleted when the
Pod is terminated. Network and global volumes have separate lifetimes. This
project defaults to no persistent volume; copy approved evidence off the Pod
before deletion.

## 5. Compile the plan and obtain exact approval

This local planning fixture validates schema and cost arithmetic without
contacting Runpod. Its output is deliberately non-executable:

```bash
python3 scripts/compile_plan_cli.py \
  --manifest manifests/h100-qwen32b-planning.json \
  --live-inputs examples/planning-live-inputs.json \
  --output /tmp/inference-lab-planning-plan.json
```

For a paid run, create one private execution manifest per runtime/allocation.
Bind the current image digest, offer, dependency versions, model/tokenizer,
workload, storage, access mode, termination guard, duration, and cost fields.
Calculate the maximum charge from the current console values through the worst
case verified-deletion time, including every displayed GPU, storage, volume,
public-IP, egress, startup, image-pull, and rounding component that applies.
The recorded USD 2.19 is historical context, not a current price quote.

Read the active manifest and compiled plan in full. Creation is allowed only
after the owner replies exactly:

```text
APPROVE RUNPOD BENCHMARK <plan-sha256> MAX_USD <amount>
```

Any change to the digest, offer, price, workload, runtime flag, storage,
duration, access mode, or maximum charge invalidates that approval.

## 6. Deploy after approval

Only after the exact approval above:

1. Open the [Pods console](https://www.console.runpod.io/pods) and choose
   **+ New** → **Pod**.
2. Select the approved private runtime template.
3. Select the exact approved cloud type, data center, GPU variant, and one GPU.
   For the recorded configuration this is an H100 80GB; verify the displayed
   VRAM rather than relying on the family name.
4. Enter the approved container-disk setting and leave unapproved volume or
   network storage at zero/none.
5. Enable SSH access. Leave Jupyter, HTTP ports, TCP ports, and public proxy
   exposure off unless the plan explicitly includes them.
6. Review every displayed charge and the full configuration against the plan.
   If any field differs, stop and recompile; do not click **Deploy**.
7. Ensure the approved termination guard can be created and read back. The
   repository's preferred path uses `runpodctl pod create` with the bound
   `--terminate-after` value. If the console cannot preserve that exact guard,
   use the reviewed CLI command in the live-run guide rather than deploying
   through the console.
8. Deploy exactly one runtime arm. Immediately record the returned Pod ID and
   guard state in private evidence and start the independent local watchdog.

The provider-facing creation command and both supported guard modes live only
in Gate 1 of the [ordered live-run procedure](live-run.md)
so they do not drift between guides.

## 7. Connect, start, and tear down

Continue through [the live-run procedure](live-run.md) without skipping gates:

1. Wait for **Running**, then compare `runpodctl pod get` output with the
   approved GPU, image digest, storage, access, and termination guard.
2. Use the SSH command shown by Runpod or `runpodctl ssh info POD_ID`. Establish
   the documented local forwarding path to Pod loopback port 8000. Keep the
   endpoint off the public proxy.
3. Verify the repository transfer, CUDA/GPU identity, model revision, image
   identity, and free memory before starting a server.
4. Start the one approved vLLM or SGLang command inside `/opt/inference-lab`
   from Gate 2 of the [live-run procedure](live-run.md).
   Run the streamed smoke check, workload, and telemetry capture exactly once
   for that arm.
5. Copy private raw evidence and sanitized candidate outputs to the operator
   machine before deletion. Do not publish raw logs, request payloads,
   credentials, Pod IDs, IPs, or account data.
6. Permanently delete the Pod with `runpodctl pod delete`. A stopped Pod is not
   cleanup: it can retain storage and may still incur charges.
7. Freshly verify all three conditions: deletion acknowledgement, absence from
   `runpodctl pod list --all`, and a direct structured `not_found` response for
   the deleted ID. Then reconcile billing and capture sanitized evidence.

Complete and verify deletion of the first runtime allocation before creating
the second. Report two future arms as independent because provider allocation
does not prove they used the same physical GPU.
