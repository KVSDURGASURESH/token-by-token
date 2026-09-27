# Episode 1 candidate image

This is a blocked, digest-first build specification for one Linux/amd64 image
with isolated Python 3.12 environments at `/opt/venvs/vllm` and
`/opt/venvs/sglang`. It is not a built or validated image.

The base is the observed Linux/amd64 child manifest of
`nvidia/cuda:13.0.3-cudnn-devel-ubuntu24.04` at
`sha256:a85c9f5af049f0ab679c1669ae6fa8393022886739af7361e85bb96878e8cdd4`.
The manifest was content-hashed but not signature-verified, and its config body
was not inspected because TLS verification failed. Never disable TLS to bypass
that gate.

The hash-complete serving candidates are:

- `vllm.lock`: 196 packages, SHA-256 `c7319e5fc782b79780f4a4a1068f9feae6647531ab4b9540bf468f54a09b6b48`.
- `sglang-wheel.lock`: 243 packages, SHA-256 `6cba8a33762d2b224cf1599858e23dbc5c46384a25a4f7d84d0633c5ea848dc6`.

They reconstruct PyPI serving environments, not byte-equivalent upstream
official images. A release build must additionally bind the Ubuntu package
versions, the uv amd64 archive hash, Dockerfile/entrypoint/source hashes, build
platform, BuildKit version, resulting manifest/config/image digests, and SBOM.
The unresolved build arguments deliberately make accidental unpinned builds
fail.

SGLang mirrors its v0.5.20 image's deliberate NCCL 2.30.7 override even though
Torch 2.13 metadata requires 2.29.7. Only that exact `pip check` discrepancy is
allowable; all others fail. Native linkage, imports, a collective smoke, server
smoke, and model load must pass on the H100. `cuda-tile==1.6.0rc5` declares a
CUDA 13.1+ compiler requirement and no Hopper support for its TileIR 13.2
compiler. The Qwen/H100 startup gate must prove that the selected path never
requires cuTile compilation; if it does, abort without a silent CUDA or package
override.

No local build was attempted: the workstation has no usable container daemon
and insufficient evidence to claim the external GPU gates. The eventual build
and runtime attestation remain blockers before an execution plan can become
approval-eligible.
