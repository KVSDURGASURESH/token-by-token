# Live Runpod benchmark journal

Date: 2026-09-19

This is the operational learning log for the Qwen2.5-32B inference-runtime
comparison. It intentionally excludes credentials, public addresses, SSH
material, account identifiers, and raw generated text.

## Incident format

Each entry records the symptom, cause or best-supported diagnosis, mitigation,
prevention, and whether it affects cost or result comparability. Unknowns stay
unknown until verified.

## J01 — catalog stock did not mean allocatable stock

- **Symptom:** Community H100 NVL, RTX PRO 6000 96 GB, and H200 pools appeared
  as Low or Medium stock, but the scheduler rejected every attempted location.
- **Diagnosis:** The catalog is a coarse availability snapshot. The subset that
  also satisfied the requested public-IP and exact GPU constraints was already
  exhausted by allocation time.
- **Mitigation:** Retried each advertised location once, verified that failed
  attempts created no Pod, and used Secure Cloud only after explicit approval.
- **Prevention:** Treat catalog availability as a lead, not a reservation. List
  two approved hardware/cloud fallbacks before the test window and attach the
  same model, budget, and comparability contract to each.
- **Impact:** No GPU charge from failed scheduling. Delayed experiment start.

## J02 — current runpodctl has no server-side terminate-after flag

- **Symptom:** The installed current CLI did not expose the documented
  `--terminate-after` option.
- **Diagnosis:** The flag was removed from the current CLI release even though
  older Runpod skill/runbook material still referenced it.
- **Mitigation:** Added and tested a local balance/time/cost watchdog that calls
  `runpodctl pod delete`, then installed a second self-deletion timer inside the
  Pod immediately after SSH became ready.
- **Prevention:** Inspect live CLI help before rental. Keep two independent
  deletion paths and verify `pod list --all` plus current spend after cleanup.
- **Impact:** No measurement impact. Stronger operational evidence is required
  because automatic deletion is implemented outside Pod creation.

## J03 — macOS archive metadata caused noisy Linux extraction failures

- **Symptom:** The first source extraction emitted ownership errors and exited
  nonzero even though many files were unpacked.
- **Diagnosis:** The macOS archive carried Apple extended-attribute headers and
  local UID/GID metadata that the remote filesystem would not apply.
- **Mitigation:** Quarantined the partial extraction and re-extracted with GNU
  tar `--no-same-owner --no-same-permissions`; verified the benchmark entrypoint.
- **Prevention:** Build transfer archives with metadata stripped, exclude Apple
  `._*` files and caches, and test extraction in a Linux container before paid
  time.
- **Impact:** A few minutes of paid setup time; no benchmark data affected.

## J04 — local default Python was below the repository contract

- **Symptom:** A broad local test run failed in Python 3.9 on syntax and API
  features supported by the project, alongside sandboxed loopback failures.
- **Diagnosis:** Apple system Python was selected instead of the repository's
  supported Python 3.10+ runtime.
- **Mitigation:** Re-ran focused tests under Python 3.12 and granted loopback
  access for the integration suite. New cost-guard and reporting tests passed.
- **Prevention:** Make the supported interpreter explicit in the test command or
  project environment; add a preflight that rejects Python below 3.10.
- **Impact:** Local validation noise only; no GPU measurement impact.

## J05 — base image contains CUDA/PyTorch but no serving runtimes

- **Symptom:** The selected Runpod PyTorch image provided CUDA 12.8, PyTorch
  2.9.1, and `uv`, but not vLLM, SGLang, TGI, TensorRT-LLM, Hugging Face CLI,
  or NumPy.
- **Diagnosis:** The base image is intentionally a framework image rather than
  a multi-runtime inference image.
- **Mitigation:** Use isolated runtime environments and a shared model cache;
  record exact resolved versions and installation duration before measurement.
- **Prevention:** Prepare a pinned benchmark image or pre-warm a network volume
  after the exploratory run, while keeping each runtime dependency-isolated.
- **Impact:** Paid cold-setup time. Runtime comparisons remain valid only after
  configuration and readiness evidence are captured for every arm.

## J06 — latest vLLM cold import and architecture resolution were slow

- **Symptom:** `vllm==0.29.0` took about a minute to import during installation
  and another roughly 80 seconds to resolve the Qwen architecture before model
  download began; the health port was not listening during that period.
- **Diagnosis:** The processes remained CPU-active and the model-registry child
  advanced normally; this was cold-start overhead rather than a deadlock.
- **Mitigation:** Monitored process state, network sockets, cache growth, and
  logs instead of restarting and paying the cold-start cost twice.
- **Prevention:** Pre-build version-pinned runtime images and cache both Python
  wheels and model snapshots for repeat experiments.
- **Impact:** Paid cold-start time only; measured requests begin after readiness.

## J07 — CUDA 12.8 could not identify Blackwell for FlashInfer sampling

- **Symptom:** After weights and CUDA graphs loaded, vLLM aborted in FlashInfer
  sampling with `SM 12.x requires CUDA >= 12.9` followed by the misleading
  fallback error `FlashInfer requires GPUs with sm75 or higher`.
- **Diagnosis:** The RTX PRO 6000 Blackwell is SM 12.x, but the selected Runpod
  PyTorch image exposes CUDA 12.8. FlashInfer's architecture probe therefore
  rejected a GPU that is newer, not older, than its stated minimum.
- **Mitigation:** Set the documented installed-runtime switch
  `VLLM_USE_FLASHINFER_SAMPLER=0` and restarted vLLM from the already cached
  weights and compile cache. FlashAttention remained the attention backend.
- **Prevention:** Match Blackwell images to CUDA 12.9+ and run a one-token smoke
  request before long model downloads when image/runtime compatibility is new.
- **Impact:** Added one startup retry and paid setup time; no request measurement
  was accepted before the failure.

## J08 — Transformers v5 chat-template return shape broke prompt accounting

- **Symptom:** The two-request smoke artifact reported two input tokens even
  though its prompt was visibly longer.
- **Diagnosis:** Transformers 5 returned a mapping containing batched
  `input_ids`; the first harness version applied `len()` to the mapping and
  counted its two keys.
- **Mitigation:** Discarded the smoke timings, added a failing regression test,
  and updated token counting to handle mappings, batched lists, and tensors.
- **Prevention:** Assert the requested and observed prompt-token range before
  launching any paid measurement cell.
- **Impact:** Two dry requests only; no published measurement was contaminated.

## J09 — a version probe cold-imported vLLM during the final sequential cell

- **Symptom:** A read-only dependency-version command remained CPU-active instead
  of returning promptly while the 4,096-token concurrency-1 cell was running.
- **Diagnosis:** Importing vLLM triggers costly cold initialization and registry
  discovery; it is not a harmless metadata lookup under load.
- **Mitigation:** Terminated only the probe, confirmed the serving and benchmark
  processes stayed healthy, and retained the incident as a comparability warning.
- **Prevention:** Capture package versions from installed distribution metadata
  (`importlib.metadata`) before measurement; never import the runtime package
  during a benchmark.
- **Impact:** The probe overlapped approximately the last 13 requests of one
  sequential cell on a 16-vCPU host. GPU utilization stayed at 100%, but that
  cell must be disclosed as having possible client/CPU-side interference.

## J10 — current SGLang default requires a newer NVCC on Blackwell

- **Symptom:** SGLang 0.5.20 completed dependency installation but its default
  server exited before weight loading with `NVCC version must be at least 12.9`.
- **Diagnosis:** On SM 12.x the default FlashInfer/DeepGEMM path checks the
  system CUDA compiler. CUDA 13 Python wheels do not replace the base image's
  CUDA 12.8 toolkit, so the mixed environment remains incompatible.
- **Mitigation:** Preserved the failed-default log and made one explicitly
  labelled compatibility retry using `SGLANG_ENABLE_JIT_DEEPGEMM=0`, Triton
  attention, PyTorch sampling, and Torch BF16 GEMM.
- **Prevention:** Select a CUDA 12.9+ (preferably current CUDA 13) Blackwell
  image before rental, or use a pinned runtime image whose backends have
  already passed a one-token smoke test on the exact GPU.
- **Impact:** Default SGLang cannot be fairly compared on this image. Any
  fallback result is useful operational evidence but not an optimal-runtime
  score and must be labelled separately.

## J11 — SGLang's fallback JIT needed an undeclared Ninja executable

- **Symptom:** The CUDA-12.8 fallback loaded all 17 model shards, then failed
  during fused-RoPE CUDA-graph warm-up with `FileNotFoundError: ninja`.
- **Diagnosis:** SGLang's fused-kernel JIT invokes the Ninja executable. The
  resolved environment did not include it initially; after installation, an
  absolute-Python launch still omitted the venv's `bin` directory from `PATH`.
- **Mitigation:** Installed `ninja`, explicitly prepended the isolated venv's
  `bin` directory to `PATH`, and restarted the otherwise identical fallback
  configuration from cached weights.
- **Prevention:** Add `command -v ninja` and a one-token server smoke request to
  the runtime preflight before any measurement matrix.
- **Impact:** Paid startup retry only; no SGLang request measurement had begun.

## J12 — staged source path differed from the local repository path

- **Symptom:** The first SGLang smoke command tried to enter the capstone's
  repository-relative path and exited before issuing a request.
- **Diagnosis:** The transfer archive placed the capstone contents directly at
  `[local benchmark source directory]`; it did not preserve the local parent
  directories.
- **Mitigation:** Located the staged harness by filename, verified the expected
  source tree, and reran from the actual staging root.
- **Prevention:** Record and verify `REMOTE_SOURCE_ROOT` immediately after
  extraction, then use that single value in all runtime commands.
- **Impact:** No measurement impact. Telemetry began early and those setup-only
  samples are excluded by the measurement time window.

## J13 — tokenizer startup attempted avoidable network metadata checks

- **Symptom:** The first harness process opened outbound HTTPS connections even
  though the model and tokenizer revision were already present in the shared
  Hugging Face cache.
- **Diagnosis:** `AutoTokenizer.from_pretrained` may perform repository metadata
  checks unless offline mode is explicit; this adds unrelated and variable
  startup latency before the first measured request.
- **Mitigation:** Ran smoke and measured matrices with `HF_HUB_OFFLINE=1`,
  `TRANSFORMERS_OFFLINE=1`, and the verified shared `HF_HOME` cache.
- **Prevention:** Download and verify the immutable revision before measurement,
  then make offline-cache mode part of the benchmark contract.
- **Impact:** No request metric contamination: client timings start at the
  actual socket send. It did waste setup time and made process monitoring noisy.

## J14 — the broad local suite mixed real checks with checkout/environment failures

- **Symptom:** The first 631-test run produced 141 loopback bind errors inside
  the sandbox. Re-running 632 tests with loopback permission removed those but
  retained four copy-back errors from helper subprocesses selecting an older
  Python, plus 13 readiness failures caused by three pre-existing broken links
  to a design document absent from this worktree.
- **Diagnosis:** These failures are outside the new live-harness, normalizer,
  telemetry summarizer, reporting, and dashboard data paths. The exact 16
  affected Python tests pass under Python 3.12; the frontend type-check and
  production build also pass.
- **Mitigation:** Kept the broad-suite output as a disclosed repository-health
  limitation and validated the changed paths separately instead of weakening
  their gates or editing unrelated checkout state.
- **Prevention:** Pin the child-process interpreter in the copy-back fixtures,
  make the referenced design document part of the tested branch, and mark
  loopback-dependent tests so their runner requests network permission up front.
- **Impact:** No remote benchmark effect. Final validation must report both the
  passing affected suite and the pre-existing broad-suite failures.

## J15 — teardown was verified as deletion, not merely a stopped pod

- **Symptom:** A stopped Runpod resource can still retain billable storage, so a
  successful server shutdown was not sufficient evidence of cost termination.
- **Diagnosis:** The benchmark contract required permanent pod deletion after
  evidence copy-back, plus an independent provider-state check.
- **Mitigation:** Stopped the inference server, verified zero GPU memory use,
  copied and hash-checked both runtime evidence sets, deleted pod
  `local-historical-pod-1`, then verified an all-pods listing of `[]` and a direct
  `not_found` lookup. The overnight continuation automation was paused.
- **Prevention:** Make deletion confirmation, an empty provider inventory, and
  a private final balance snapshot mandatory teardown artifacts for every paid
  lab; publish only the aggregate charge.
- **Impact:** The total session charge was $4.1280. No Runpod pod remained after
  the study. Exact account balances remain private evidence.
