# Public CLI and Offline Self-Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an isolated `token-by-token` public client that can describe Episode 02, validate its public protocol, run a deterministic zero-network synthetic self-test, verify the resulting bundle, and build as a standalone client executable without containing AgentBench or private benchmark material.

**Architecture:** A new `client/` Python distribution is the only public-client build context. It consumes strict public JSON contracts and an approved Episode 02 manifest, but it cannot import repository benchmark modules or execute remote runs. The self-test drives a deterministic fake engine through the same public event and bundle contracts that future hosted results will use; remote authentication, submission, replay observability, and private AgentBench integration are separate plans.

**Tech Stack:** Python 3.12, standard-library `argparse`, JSON Schema Draft 2020-12, `jsonschema==4.25.1`, PyInstaller one-file builds, `unittest`, GitHub Actions

**Spec:** `design/BENCHMARK-SERVICE-PROPOSAL.md`

## Global Constraints

- The public package and binary must never include `src/runpod_benchmark`, AgentBench, deployment recipes, corpus payloads, credentials, provider adapters, raw operational exports, private labels, or unrestricted engine flags.
- Phase 1 exposes only `version`, `episode 2 describe`, `episode 2 selftest --offline`, and `evidence verify PATH`; no command may allocate resources, issue inference to a remote endpoint, authenticate, or submit a paid run.
- `selftest` requires the literal `--offline` flag and rejects endpoint, token, proxy, provider, image, shell, corpus-path, plugin, and arbitrary configuration inputs.
- Every synthetic artifact uses `classification: synthetic_mock`; recorded and synthetic artifacts cannot be mixed.
- JSON contracts reject unknown properties and unsupported schema versions. Missing measurements use `null` plus a reason, never zero.
- Output directories must be new or empty. Archive extraction rejects absolute paths, traversal, links, duplicate names, oversized entries, excessive compression ratios, and unlisted files.
- The client build supports Python 3.12. The PyInstaller output is an internal release candidate until code/data licensing and signing ownership are approved.
- No paid Episode 02 run, hosted control-plane work, public service attribution, Grafana publication, or GitHub release is authorized by this plan.

## Review Focus

- A caller sets proxy and service URL environment variables: offline self-test makes zero outbound connections and records no endpoint material.
- A replay archive contains `../`, an absolute path, a symlink, a duplicate entry, or a decompression bomb: verification fails before writing outside its temporary extraction root.
- A bundle mixes `synthetic_mock` and recorded classifications: verification fails with a typed classification error.
- A manifest contains an unknown control such as `speculative_drafts`: strict validation fails and the CLI never forwards it.
- A binary is built from the repository root instead of `client/`: the build guard fails when forbidden modules or private markers appear in the analysis inventory.

---

### Task 1: Isolate the public client package and establish the command surface

**Files:**
- Create: `client/pyproject.toml`
- Create: `client/src/token_by_token_cli/__init__.py`
- Create: `client/src/token_by_token_cli/__main__.py`
- Create: `client/src/token_by_token_cli/cli.py`
- Create: `client/src/token_by_token_cli/errors.py`
- Create: `client/tests/test_cli_surface.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `token_by_token_cli.cli.main(argv: Sequence[str] | None = None) -> int`
- Produces: console entry point `token-by-token = token_by_token_cli.cli:entrypoint`
- Produces: typed `ClientError(code: str, message: str, exit_status: int)` rendered without tracebacks for expected failures

- [ ] **Step 1: Write the failing command-surface tests**

```python
class CliSurfaceTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONPATH": str(CLIENT_SRC)}
        return subprocess.run(
            [sys.executable, "-m", "token_by_token_cli", *args],
            text=True, capture_output=True, env=env, check=False,
        )

    def test_help_exposes_only_phase_one_commands(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("episode", result.stdout)
        self.assertIn("evidence", result.stdout)
        self.assertNotIn("runs submit", result.stdout)
        self.assertNotIn("auth login", result.stdout)

    def test_unknown_command_is_a_clean_usage_error(self):
        result = self.run_cli("runs", "submit")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `python3 -m unittest client.tests.test_cli_surface -v`

Expected: FAIL because `token_by_token_cli` does not exist.

- [ ] **Step 3: Add the isolated package and minimal parser**

```toml
[project]
name = "token-by-token-client"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["jsonschema==4.25.1"]

[project.scripts]
token-by-token = "token_by_token_cli.cli:entrypoint"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

Implement `build_parser()` with the exact hierarchy `episode 2 describe`, `episode 2 selftest`, and `evidence verify`. `main()` returns an integer; `entrypoint()` raises `SystemExit(main())`. Parser creation must import only `token_by_token_cli` modules.

- [ ] **Step 4: Run the command-surface tests**

Run: `python3 -m unittest client.tests.test_cli_surface -v`

Expected: PASS.

- [ ] **Step 5: Commit the isolated package skeleton**

```bash
git add client .gitignore
git commit -m "feat(client): establish isolated public CLI"
```

### Task 2: Define strict public contracts and Episode 02 description

**Files:**
- Create: `client/src/token_by_token_cli/contracts.py`
- Create: `client/src/token_by_token_cli/resources/schemas/episode-manifest.v1.schema.json`
- Create: `client/src/token_by_token_cli/resources/schemas/run-replay.v1.schema.json`
- Create: `client/src/token_by_token_cli/resources/schemas/inventory.v1.schema.json`
- Create: `client/src/token_by_token_cli/resources/episodes/episode-02-v1.json`
- Create: `client/tests/test_contracts.py`
- Create: `client/tests/test_episode_describe.py`
- Modify: `client/pyproject.toml`
- Modify: `client/src/token_by_token_cli/cli.py`

**Interfaces:**
- Produces: `load_resource_json(relative_path: str) -> dict[str, object]`
- Produces: `validate_document(schema_name: str, document: Mapping[str, object]) -> None`
- Produces: `episode_manifest(episode: int, protocol: str) -> dict[str, object]`
- Consumes: `ClientError` from Task 1

- [ ] **Step 1: Write failing strict-validation tests**

```python
def test_manifest_rejects_unknown_control(self):
    document = copy.deepcopy(episode_manifest(2, "episode-02-v1"))
    document["allowed_parameters"]["speculative_drafts"] = {"type": "integer"}
    with self.assertRaisesRegex(ClientError, "UNKNOWN_PROPERTY"):
        validate_document("episode-manifest.v1", document)

def test_manifest_requires_explicit_mock_classification(self):
    document = copy.deepcopy(episode_manifest(2, "episode-02-v1"))
    del document["selftest"]["classification"]
    with self.assertRaisesRegex(ClientError, "INVALID_CONTRACT"):
        validate_document("episode-manifest.v1", document)
```

The literal expected manifest allows only `protocol`, `users`, `seed`, and `output`; its Episode 02 arms are `vLLM` and `SGLang`, and speculation is excluded.

- [ ] **Step 2: Run the contract tests and verify they fail**

Run: `python3 -m unittest client.tests.test_contracts -v`

Expected: FAIL because the resource loader and schemas do not exist.

- [ ] **Step 3: Add Draft 2020-12 schemas and validation**

Each root schema uses:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "classification"]
}
```

`validate_document()` uses `Draft202012Validator`, sorts errors by JSON path, and maps `additionalProperties` failures to `ClientError("UNKNOWN_PROPERTY", ...)`. Package all schemas and the manifest via `tool.setuptools.package-data`.

- [ ] **Step 4: Write the failing human and JSON description tests**

```python
def test_episode_2_describe_names_public_controls_and_exclusions(self):
    result = run_cli("episode", "2", "describe")
    self.assertEqual(result.returncode, 0)
    self.assertIn("Equal-work runtime baseline", result.stdout)
    self.assertIn("2, 4, 8, 12, 16, 24", result.stdout)
    self.assertIn("Speculative decoding: excluded", result.stdout)
    self.assertNotIn("profile", result.stdout.lower())

def test_episode_2_describe_json_is_schema_valid(self):
    result = run_cli("episode", "2", "describe", "--format", "json")
    document = json.loads(result.stdout)
    validate_document("episode-manifest.v1", document)
    self.assertEqual(document["protocol"], "episode-02-v1")
```

- [ ] **Step 5: Implement `episode 2 describe` and rerun both test modules**

Run: `python3 -m unittest client.tests.test_contracts client.tests.test_episode_describe -v`

Expected: PASS.

- [ ] **Step 6: Commit the public contracts**

```bash
git add client
git commit -m "feat(client): publish strict episode contracts"
```

### Task 3: Build the deterministic fake engine and synthetic event stream

**Files:**
- Create: `client/src/token_by_token_cli/offline.py`
- Create: `client/src/token_by_token_cli/model.py`
- Create: `client/tests/test_offline_engine.py`
- Create: `client/tests/fixtures/offline-expected-events.json`

**Interfaces:**
- Produces: immutable `SyntheticRequest(request_id: str, users: int, seed: int, input_tokens: int, output_tokens: int)`
- Produces: immutable `SyntheticEvent(sequence: int, kind: str, monotonic_ms: int, payload: Mapping[str, object])`
- Produces: `run_synthetic_episode(manifest, *, stop_requested: Callable[[], bool]) -> Iterator[SyntheticEvent]`
- Consumes: validated Episode 02 manifest from Task 2

- [ ] **Step 1: Write the failing deterministic-stream tests**

```python
def test_same_manifest_produces_byte_identical_events(self):
    first = [event.to_json() for event in run_synthetic_episode(MANIFEST, stop_requested=lambda: False)]
    second = [event.to_json() for event in run_synthetic_episode(MANIFEST, stop_requested=lambda: False)]
    self.assertEqual(first, second)
    self.assertEqual(first, json.loads(EXPECTED.read_text()))

def test_stop_request_emits_terminal_interrupted_event(self):
    calls = iter([False, False, True])
    events = list(run_synthetic_episode(MANIFEST, stop_requested=lambda: next(calls, True)))
    self.assertEqual(events[-1].kind, "run_interrupted")
    self.assertFalse(any(event.kind == "run_completed" for event in events))
```

- [ ] **Step 2: Run the engine tests and verify they fail**

Run: `python3 -m unittest client.tests.test_offline_engine -v`

Expected: FAIL because `offline.py` and `model.py` do not exist.

- [ ] **Step 3: Implement deterministic generation**

Use integer arithmetic and a local `random.Random(seed)` instance. Emit a fixed sequence of plan, arm-start, request, metric, arm-complete, and run-complete events with logical millisecond offsets; never read wall-clock time, hostname, environment variables, network state, or repository-private data. Request identifiers are `mock-{arm_index:02d}-{request_index:04d}`.

- [ ] **Step 4: Run the engine tests**

Run: `python3 -m unittest client.tests.test_offline_engine -v`

Expected: PASS with byte-identical fixture output.

- [ ] **Step 5: Commit the fake engine**

```bash
git add client
git commit -m "feat(client): add deterministic offline engine"
```

### Task 4: Assemble and verify bounded synthetic bundles

**Files:**
- Create: `client/src/token_by_token_cli/bundle.py`
- Create: `client/src/token_by_token_cli/verify.py`
- Create: `client/tests/test_bundle.py`
- Create: `client/tests/test_hostile_bundle.py`
- Modify: `client/src/token_by_token_cli/cli.py`

**Interfaces:**
- Produces: `write_synthetic_bundle(events, output_dir: Path) -> Path`
- Produces: `verify_bundle(path: Path) -> VerificationReport`
- Produces: `VerificationReport(classification: str, files: tuple[str, ...], digest: str)`
- Consumes: `inventory.v1` and `run-replay.v1` schemas from Task 2

- [ ] **Step 1: Write failing round-trip and classification tests**

```python
def test_bundle_round_trip_is_complete_and_synthetic(self):
    bundle = write_synthetic_bundle(EVENTS, self.output)
    report = verify_bundle(bundle)
    self.assertEqual(report.classification, "synthetic_mock")
    self.assertEqual(report.files, ("events.jsonl", "inventory.json", "replay.json"))

def test_mixed_classification_is_rejected(self):
    bundle = make_bundle(replay_classification="recorded", inventory_classification="synthetic_mock")
    with self.assertRaisesRegex(ClientError, "MIXED_CLASSIFICATION"):
        verify_bundle(bundle)
```

- [ ] **Step 2: Write failing hostile-archive tests**

```python
def test_hostile_archives_fail_closed(self):
    fixture_names = (
        "../escape", "/absolute", "duplicate", "symlink",
        "unlisted-file", "oversized-entry", "compression-ratio",
    )
    for fixture_name in fixture_names:
        with self.subTest(fixture_name=fixture_name):
            archive = build_hostile_archive(fixture_name)
            with self.assertRaises(ClientError):
                verify_bundle(archive)
            self.assertEqual(list(self.extraction_parent.iterdir()), [])
```

- [ ] **Step 3: Run both test modules and verify the missing implementation**

Run: `python3 -m unittest client.tests.test_bundle client.tests.test_hostile_bundle -v`

Expected: FAIL because the bundle writer and verifier do not exist.

- [ ] **Step 4: Implement canonical bundle output and safe verification**

Canonical JSON uses UTF-8, sorted keys, compact separators, and a trailing newline. Inventory entries contain `path`, `size`, `media_type`, and lowercase SHA-256. Verification reads at most 32 MiB total, 8 MiB per entry, 64 entries, and a 100:1 compression ratio; it hashes bytes before parsing JSON and rejects every archive member not listed in the inventory.

- [ ] **Step 5: Add `evidence verify PATH --format human|json`**

The human result is exactly one summary line plus the verified file list. JSON output is a stable object containing `valid`, `classification`, `digest`, and `files`. Expected failures return exit status 3 and never print a traceback.

- [ ] **Step 6: Run round-trip, hostile, and CLI tests**

Run: `python3 -m unittest client.tests.test_bundle client.tests.test_hostile_bundle client.tests.test_cli_surface -v`

Expected: PASS.

- [ ] **Step 7: Commit bundle verification**

```bash
git add client
git commit -m "feat(client): verify bounded synthetic bundles"
```

### Task 5: Wire the end-to-end offline self-test and prove zero network use

**Files:**
- Create: `client/src/token_by_token_cli/selftest.py`
- Create: `client/tests/test_selftest.py`
- Create: `client/tests/test_offline_network.py`
- Modify: `client/src/token_by_token_cli/cli.py`

**Interfaces:**
- Produces: `run_selftest(output: Path, *, offline: bool, stop_requested: Callable[[], bool]) -> SelfTestReport`
- Produces: `SelfTestReport(bundle: Path, digest: str, requests: int, classification: Literal['synthetic_mock'])`
- Consumes: deterministic events from Task 3 and bundle APIs from Task 4

- [ ] **Step 1: Write failing CLI behavior tests**

```python
def test_selftest_requires_literal_offline_flag(self):
    result = run_cli("episode", "2", "selftest", "--output", str(self.output))
    self.assertEqual(result.returncode, 2)
    self.assertIn("--offline is required", result.stderr)
    self.assertFalse(self.output.exists())

def test_selftest_refuses_nonempty_output(self):
    self.output.mkdir()
    (self.output / "owner-file").write_text("preserve me")
    result = run_cli("episode", "2", "selftest", "--offline", "--output", str(self.output))
    self.assertEqual(result.returncode, 3)
    self.assertEqual((self.output / "owner-file").read_text(), "preserve me")

def test_selftest_produces_a_verified_synthetic_bundle(self):
    result = run_cli("episode", "2", "selftest", "--offline", "--output", str(self.output), "--format", "json")
    report = json.loads(result.stdout)
    self.assertEqual(result.returncode, 0)
    self.assertEqual(report["classification"], "synthetic_mock")
    self.assertEqual(verify_bundle(self.output).digest, report["digest"])
```

- [ ] **Step 2: Write the failing real-network sentinel test**

Start a real loopback TCP listener in the test, set `HTTPS_PROXY`, `HTTP_PROXY`, `TOKEN_BY_TOKEN_SERVICE_URL`, and fake credential variables to that listener, then execute the self-test subprocess. Assert the listener accepts zero connections, the command passes, and neither the endpoint nor credential value occurs in any output byte.

- [ ] **Step 3: Run the self-test modules and verify they fail**

Run: `python3 -m unittest client.tests.test_selftest client.tests.test_offline_network -v`

Expected: FAIL because `selftest.py` does not exist and the command has no handler.

- [ ] **Step 4: Implement the self-test orchestration**

The command loads only packaged resources, validates the manifest, checks the output directory, runs the fake engine, writes the bundle into a sibling temporary directory, verifies it, and atomically renames it to the requested path. On interruption or failure it removes only the temporary directory it created.

- [ ] **Step 5: Run all client tests**

Run: `python3 -m unittest discover -s client/tests -p 'test_*.py' -v`

Expected: PASS, including zero accepted network connections.

- [ ] **Step 6: Commit the complete offline flow**

```bash
git add client
git commit -m "feat(client): complete offline episode self-test"
```

### Task 6: Build a standalone client executable with a fail-closed content guard

**Files:**
- Create: `client/token-by-token.spec`
- Create: `client/requirements-build.in`
- Create: `client/requirements-build.lock`
- Create: `client/scripts/build_binary.py`
- Create: `client/scripts/audit_binary.py`
- Create: `client/tests/test_binary_audit.py`
- Modify: `.github/workflows/offline.yml`

**Interfaces:**
- Produces: `client/dist/token-by-token` on Linux/macOS or `token-by-token.exe` on Windows
- Produces: `client/dist/SHA256SUMS`
- Produces: `audit_binary(path: Path, analysis_inventory: Path) -> None`
- Consumes: only `client/src`, packaged public resources, Python runtime, `jsonschema`, and its locked transitive dependencies

- [ ] **Step 1: Write the failing binary-audit tests**

```python
def test_audit_rejects_private_module_inventory(self):
    inventory = self.write_inventory(["token_by_token_cli.cli", "runpod_benchmark.episode1_runner"])
    with self.assertRaisesRegex(ClientError, "FORBIDDEN_BUILD_INPUT"):
        audit_binary(self.binary, inventory)

def test_audit_rejects_private_markers_in_executable(self):
    self.binary.write_bytes(b"safe-prefix agentbench --profile private safe-suffix")
    with self.assertRaisesRegex(ClientError, "FORBIDDEN_BINARY_CONTENT"):
        audit_binary(self.binary, self.write_inventory(["token_by_token_cli.cli"]))
```

The forbidden inventory prefixes are `runpod_benchmark`, `scripts`, `runtime`, `deploy`, and `data`. Marker scanning uses the repository privacy scanner’s high-confidence rules plus AgentBench and serving-profile terms; it does not print matched secret-like bytes.

- [ ] **Step 2: Run the audit tests and verify they fail**

Run: `python3 -m unittest client.tests.test_binary_audit -v`

Expected: FAIL because build and audit scripts do not exist.

- [ ] **Step 3: Add the pinned build environment and PyInstaller specification**

Write `requirements-build.in` with `pyinstaller==6.16.0` and generate the hashed transitive lock using `pip-compile --generate-hashes --output-file client/requirements-build.lock client/requirements-build.in`. The spec sets `pathex=[client/src]`, explicitly includes the three public schema files and Episode 02 manifest, and errors if the analysis graph contains a forbidden prefix.

- [ ] **Step 4: Implement build and audit scripts**

`build_binary.py` refuses to run unless its resolved working directory is `client/`, deletes only `client/build/` and `client/dist/`, invokes PyInstaller with a clean environment, audits the analysis inventory and executable, runs `token-by-token --version`, runs the offline self-test in a fresh temporary directory, and writes `SHA256SUMS`.

- [ ] **Step 5: Run the client tests and an actual local binary build**

```bash
python3 -m unittest discover -s client/tests -p 'test_*.py' -v
python3 client/scripts/build_binary.py
client/dist/token-by-token episode 2 selftest --offline --output /tmp/token-by-token-binary-selftest
client/dist/token-by-token evidence verify /tmp/token-by-token-binary-selftest
```

Expected: all commands exit 0; the bundle is `synthetic_mock`; the audit reports no forbidden build inputs.

- [ ] **Step 6: Add a non-publishing CI binary job**

The job runs on `ubuntu-latest` with `contents: read`, builds the executable, audits it, executes the offline self-test with external networking denied after dependency installation, and uploads the candidate artifact for maintainers. It does not create a GitHub release or sign an artifact.

- [ ] **Step 7: Commit executable packaging**

```bash
git add client .github/workflows/offline.yml
git commit -m "build(client): produce guarded standalone executable"
```

### Task 7: Publish maintainable onboarding without overstating availability

**Files:**
- Create: `client/README.md`
- Create: `client/SECURITY.md`
- Create: `client/THREAT-MODEL.md`
- Create: `docs/client-release-checklist.md`
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`
- Modify: `design/CONTINUATION-GUIDE.md`

**Interfaces:**
- Documents: install-from-source, candidate binary verification, Episode 02 description, offline self-test, evidence verification, security boundary, known limitations, ownership, and release gates
- Consumes: exact commands implemented and tested in Tasks 1–6

- [ ] **Step 1: Write the public-client README using only verified commands**

The quick start contains:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install ./client
token-by-token episode 2 describe
token-by-token episode 2 selftest --offline --output ./token-by-token-selftest
token-by-token evidence verify ./token-by-token-selftest
```

State prominently that the self-test is synthetic, costs $0, makes no provider call, and does not benchmark vLLM or SGLang. State that hosted submission is unavailable in this release and that AgentBench is neither included nor named as an affiliated public product.

- [ ] **Step 2: Document security and release ownership**

`SECURITY.md` gives a private reporting route supplied by the owner before public release. `THREAT-MODEL.md` covers malicious archives, environment leakage, binary supply chain, accidental private-module inclusion, classification confusion, and future cross-tenant service risks. The release checklist requires license approval, trademark/attribution approval, checksums, SBOM, code signing, privacy scan, hostile-bundle tests, offline network proof, and owner sign-off.

- [ ] **Step 3: Update root discovery and contributor guidance**

The root README links to `client/README.md` as an unreleased public-client candidate. `CONTRIBUTING.md` explains that client changes must remain inside `client/` except for approved public contracts and documentation, and must pass the forbidden-import audit.

- [ ] **Step 4: Run every documented command in a clean virtual environment**

```bash
python3 -m venv /tmp/token-by-token-doc-check
/tmp/token-by-token-doc-check/bin/python -m pip install ./client
/tmp/token-by-token-doc-check/bin/token-by-token episode 2 describe
/tmp/token-by-token-doc-check/bin/token-by-token episode 2 selftest --offline --output /tmp/token-by-token-doc-bundle
/tmp/token-by-token-doc-check/bin/token-by-token evidence verify /tmp/token-by-token-doc-bundle
```

Expected: all commands exit 0 without provider credentials or external service access.

- [ ] **Step 5: Run repository-wide verification**

```bash
python3 -m unittest discover -s client/tests -p 'test_*.py' -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/check_publication_privacy.py --root .
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 scripts/check_publication_privacy.py --root dashboard/dist --files-only
node tests/dashboard_offline_acceptance.cjs dashboard/dist
```

Expected: all client checks pass; existing repository failures, if any, are named with their pre-existing reason and are not hidden.

- [ ] **Step 6: Commit the onboarding and operational handoff**

```bash
git add README.md CONTRIBUTING.md client docs/client-release-checklist.md design/CONTINUATION-GUIDE.md
git commit -m "docs(client): add offline client onboarding"
```

## Out of Scope and Required Follow-On Plans

The following approved architectural components require their own specs or implementation plans before code is written:

1. Authenticated hosted control plane and private AgentBench worker adapter.
2. Signed recorded replay bundles, key rotation, and tenant artifact authorization.
3. Sanitized local VictoriaMetrics/Grafana replay packaging.
4. Deliberately public read-only hosted Grafana at `graph.endlesstokens.ai`.
5. Paid Episode 02 execution, qualification, cost reconciliation, and publication.
6. GitHub release publication, public licenses, service terms, support, data retention, and branding.
