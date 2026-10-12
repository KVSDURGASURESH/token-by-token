# Episode 1 paired execution architecture

Status: Phase 2 implementation/review in progress, 2026-09-22. This document
authorizes no provider operation. The checked-in protocol remains planning-only.
The accepted measurement protocol is in [implementation-brief.md](implementation-brief.md).

## One allocation, six fresh processes

The candidate uses one custom `linux/amd64` image based on the digest-pinned
`nvidia/cuda:13.0.3-cudnn-devel-ubuntu24.04` image and Python 3.12. Both pinned
runtimes have independent virtual environments at `/opt/venvs/vllm` and
`/opt/venvs/sglang`, without `--system-site-packages`. Exactly one server runs at a time.
The launcher follows the frozen AB/BA/AB sequence, retaining the same Pod and
GPU allocation throughout. It never changes a Pod image, restarts the Pod,
switches to separate allocations, or silently changes runtime settings.

The build recipe must bind a platform-specific CUDA base digest, Python and
runtime versions, complete dependency locks with artifact hashes, system
packages, image entrypoint, supervisor and capture code. Environment isolation
means separate interpreters, site-packages and runtime/compiler cache paths;
it does not establish separate kernels or independent CUDA drivers. The exact
runtime build and GPU startup checks remain required. The final derived image
digest is an input to the execution compiler, not an invented fixture value.

The tagged vLLM 0.29.0 Dockerfile defaults to CUDA 13.0.3, Python 3.12 and Ubuntu
24.04. SGLang 0.5.20 requires CUDA 13 and uses the same CUDA/Ubuntu base. These
are compatible build starting points, not evidence of a successful combined
image. CUDA 13 requires a compatible driver in the 580 family or newer; actual
GPU kernel/JIT behavior must still pass the bounded live startup checks.
Sources: [vLLM tagged Dockerfile](https://github.com/vllm-project/vllm/blob/v0.29.0/docker/Dockerfile),
[SGLang tagged Dockerfile](https://github.com/sgl-project/sglang/blob/v0.5.20/docker/Dockerfile),
[NVIDIA minor-version compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html).

Free registry metadata observation at `2026-09-22T12:51:32Z` resolved the base:

| Object | SHA-256 digest |
|---|---|
| Tag manifest list | `0230b7f243483cb15969fa3cc724a9459599604427052fc2a0d4291c7c0647dd` |
| `linux/amd64` image manifest | `a85c9f5af049f0ab679c1669ae6fa8393022886739af7361e85bb96878e8cdd4` |
| Config descriptor in that manifest | `bff9236e6fefbc528c24dbf2ea753b4afac833c12fb7af51cb4d19fa01afe95d` |

The config body was not fetched because the redirected registry object endpoint
failed local TLS validation. No image layer was downloaded. These observations
establish content addresses, not a signature verification or a successful build.

Runpod documents building custom images with dependencies and an explicit
startup configuration. That supports this packaging approach; it does not prove
that these two particular runtime environments work together. Source:
[custom Pod templates](https://docs.runpod.io/pods/templates/create-custom-template).
Nested Docker, privileged mounts, host Docker sockets and root filesystem
switching are not prerequisites of this design.

### Dependency resolution before the external build

Metadata-only resolution used `uv 0.12.3`, CPython 3.12 and the
`x86_64-manylinux_2_34` target. The preferred wheel-only inputs and locks are:

| Environment | Direct inputs | Packages | Lock SHA-256 |
|---|---|---:|---|
| vLLM | `vllm==0.29.0` | 196 | `c7319e5fc782b79780f4a4a1068f9feae6647531ab4b9540bf468f54a09b6b48` |
| SGLang | `sglang[all]==0.5.20`, `sglang-kernel==0.4.7`; NCCL override below | 243 | `6cba8a33762d2b224cf1599858e23dbc5c46384a25a4f7d84d0633c5ea848dc6` |

Both select PyTorch `2.13.0+cu130` and Triton `3.7.1`. Resolution uses PyPI and
the official PyTorch CUDA 13 index; SGLang additionally needs the official
NVIDIA index. Installation must enforce the retained artifact hashes and
wheel-only policy. Metadata resolution does not establish that installation
or native linkage succeeds.

SGLang's exact `cuda-tile==1.6.0rc5` dependency is a wheel-stub source package
on PyPI with an unconstrained build backend. The NVIDIA index supplies the
CPython 3.12 Linux x86_64 wheel directly, SHA-256
`b74c20348210d2182cd998a0ecb60c518989a79b28592d72eb8294b38ddb93d7`.
The preferred lock uses that wheel and does not rely on the source stub.
Its metadata and size were observed; the wheel was not downloaded.

The same rc5 metadata requires CUDA Toolkit 13.1 or newer for cuTile compiler
use and describes a TileIR 13.2 compiler without Hopper support. The selected
CUDA 13.0.3/H100 combination cannot claim cuTile kernel-launch support. SGLang's
own tagged image combines this base with that transitive package, so its
presence alone does not establish failure. The live Qwen startup gate must
verify that the selected execution path does not require unsupported cuTile
compilation; otherwise abort without changing CUDA or package versions.

SGLang's tagged Dockerfile deliberately replaces PyTorch's declared NCCL
`2.29.7` with `2.30.7` for DeepEP. The SGLang lock preserves that override.
This is an explicit dependency-metadata exception, not a clean dependency
check: only this exact mismatch may be accepted, with all other mismatches
rejected. Native imports, linkage, collectives and model-server startup must
still pass on the target H100. Source:
[SGLang tagged Dockerfile](https://github.com/sgl-project/sglang/blob/v0.5.20/docker/Dockerfile).

These wheel environments are derived serving candidates. They do not reproduce
the official images byte for byte: upstream source builds and precompiled
FlashInfer caches differ. The final report must identify the derived build,
lock hashes and observed runtime behavior. Pinning the CUDA base and Python
locks does not alone freeze system packages or builder tools; the build
specification and output provenance must cover those inputs too.

Model weights are staged once at the pinned revision into Pod-local ephemeral
storage. Both runtimes use that verified snapshot. Record the snapshot inventory
and tokenizer/template hashes; reject an incomplete cache or revision mismatch.
Subsequent blocks use offline/local-only loading. Keep kernel and runtime caches
separate by runtime and record the cache policy. Fresh process/KV state does not
mean a cold host filesystem cache, and the report must retain that distinction.
No incidental model-weight download belongs in free preflight.

## Access and runtime supervision

The candidate binds full SSH access, public-IP support and TCP port 22 in the
resource/cost contract. The custom image must install and start `sshd`; no
assumption that an arbitrary runtime image supplies it is allowed. The server
and metrics endpoints remain on Pod loopback. The client uses a bounded SSH
forward to preserve the existing loopback transport implementation.
Runpod's basic proxied SSH does not support SCP/SFTP; full SSH requires a public
IP and an SSH daemon. Source:
[SSH connection methods](https://docs.runpod.io/pods/configuration/use-ssh).

The local SSH adapter uses strict host-key validation, a supplied private
known-hosts file, key authentication, noninteractive mode and bounded connect,
command and keepalive deadlines. Trusted host-key establishment is a required
external preflight input. Provider credentials and deletion authority remain on
the workstation. Remote argv must be safely quoted because SSH passes command
text through a remote shell; local argv construction alone is insufficient.

Before each block, record GPU UUID/PCI identity, driver, image/build attestation
and Pod identity. Reject any change. A Pod supervisor starts one server process
group, records PID/start identity and readiness, and terminates the complete
group after each block. It must verify descendants absent, endpoint closed and
GPU memory returned to the recorded idle baseline within a bound before the
next block. Killing only the parent PID is insufficient. A failed isolation or
identity check aborts the whole paired run.

## Compiler and approval contract

Use a dedicated pure Episode 1 compiler. It consumes the validated protocol,
material manifest, build specification and closed operator-input schema; it
derives the exact six-block schedule and canonical execution digest. A blocked
candidate lists unresolved inputs and has no usable approval phrase. It cannot
borrow an Episode 0 plan or a synthetic fixture's successful status.

Pre-creation external inputs include the built image digest/provenance, current
offer and stock, exact GPU/data center/access/storage settings, complete charge
components, account reserve and auto-pay evidence, SSH prerequisites and guard
mode. Quotes expire within 15 minutes and are revalidated at creation. Static
plan integrity remains verifiable afterward without reapplying quote freshness
to the running allocation. GPU fit,
effective flags, runtime health and token behavior are planned post-creation
checks; the compiler must not require a previously allocated GPU as a circular
precondition to approving bounded startup validation.

Spending requires the exact compiler-produced digest-bound maximum-charge
phrase. Local-only watchdog fallback separately requires the exact
`ACCEPT LOCAL-WATCHDOG RISK` text, recorded against the same plan digest.
Acceptance belongs in a separate authorization envelope to avoid a circular
digest. Neither response is supplied by this preparation. A provider-deletion
deadline mode remains unavailable unless a supported creation/readback contract
is actually established; an old accepted CLI flag is not evidence.

## Lifecycle and failure contract

Start the monotonic lifetime clock before the first create invocation. Persist
a unique ownership correlation token before creation and the returned Pod ID
immediately. Never retry an ambiguous create request: recover by fresh provider
inventory using that token and the bound resource settings. A correlation name
is not an idempotency guarantee. An unresolved create result cannot be reported
as successful cleanup. Never delete an unrelated or pre-existing resource.

The bound budget includes creation, image pull, staging, all startups/warmups,
measurement/drain, essential export, retries and verified deletion, including
fixed fees and billing rounding. Unknown charge components are not zero. The
75% threshold stops new warmups/blocks; the 85% threshold stops active traffic
and starts bounded essential export/deletion. Check hard deadlines inside active
cells and transport, not just between cells. A new block may start only if its
worst-case work plus cleanup fits remaining time and charge. One bounded
startup retry is allowed for the whole run before that block's measurement;
performance-result retries are forbidden.

Both independent detached watchdogs must use the original creation time,
nonce-matched initial provider-poll arming evidence, fresh heartbeats, code
hashes and workstation sleep prevention. A later arming time must not reset the
budget clock. The compiler advances the deletion trigger by the complete
polling/CLI/retry/verification horizon. Local watchdogs share workstation and
network failure modes; their acceptance is not an absolute spending guarantee.

On every exit path, preserve partial request/phase evidence, stop traffic,
stop/reap runtime processes, export bounded essential evidence and permanently
delete every owned resource. Cleanup passes only with delete acknowledgement,
fresh complete inventory absence and fresh direct not-found evidence. A stale
receipt, exception, timeout, authorization failure or stopped state is not
proof. The documented REST deletion response is HTTP 204; list and direct
lookup are separate operations. Sources: [delete Pod](https://docs.runpod.io/api-reference/pods/DELETE/pods/podId),
[list Pods](https://docs.runpod.io/api-reference/pods/GET/pods),
[find Pod](https://docs.runpod.io/api-reference/pods/GET/pods/podId).

## Capture and local acceptance

Integrate the actual cell runner: 72 warmups and 528 measured attempts. Retain
partial observations incrementally after dispatch, including timeout, drain
and unsent records. The private ledger chains create, identity, start, ready,
warmup, cell, stop, export, delete and verification events. Public projections
remain closed/allowlisted. Do not promote fake receipts to provider evidence
or synthesize telemetry, settlement, latency or token counts.

Fake provider/SSH/process/clock interfaces must exercise actual command and
state-machine code, including zero-mutation rejection for absent/stale/wrong
approval, altered material/build inputs, fresh-process ordering, startup retry
exhaustion, descendant/memory/identity mismatch, threshold crossing during a
cell, ambiguous creation, capture/export failure and incomplete deletion proof.
Failure evidence must survive cleanup; clean deletion must not erase a failed
benchmark status. A successful fake scenario proves contracts, not CUDA or
provider capabilities.

The local Docker daemon is unavailable and the workstation had about 37 GiB
free during Phase 2 preflight. A full dual-runtime image build and large model
download are not being attempted in that environment. Remaining image build,
registry, host-key, account/offer/guard and GPU checks must be stated precisely
after the locally implementable compiler, concrete adapters, supervisor,
capture and test work is complete.
