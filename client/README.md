# Token by Token client

The Token by Token client is an **unreleased public-client candidate** for
exploring the Episode 00–16 contracts and testing the evidence workflow on your
own machine. Its self-test is deterministic synthetic plumbing: it costs $0,
makes no provider call, starts no inference engine, and does not reproduce or
extend the recorded benchmark results.

The optional local AgentBench worker binary has one synthetic Episode 01
loopback diagnostic. It runs the real AgentBench coordinator and worker against
a local mock streaming server. It does not run a GPU episode or contact a
provider. Real model/GPU/load capabilities remain unavailable.

## What works today

| Capability | Command | Status |
| --- | --- | --- |
| List the curriculum | `token-by-token episodes` | Available |
| Inspect an episode and its allowed loads | `token-by-token episode N describe` | Available |
| Inspect the real-execution boundary | `token-by-token capabilities --episode N` | Available; real execution remains unavailable |
| Check the local installation offline | `token-by-token doctor --offline` | Available; diagnostic only |
| Exercise the client and bundle pipeline without a GPU | `token-by-token episode N selftest --offline …` | Available |
| Verify an emitted bundle and its classification | `token-by-token evidence verify FILE` | Available |
| Exercise the local AgentBench wrapper | `token-by-token episode 1 run-local --worker FILE --output NEW_FILE.tbt.json` | Available as a synthetic loopback diagnostic |
| Select a real model or GPU | — | Not yet available |
| Run a real GPU episode | — | Not yet available |
| Import a personal run into the dashboard | — | Not yet available |

The local worker path is opt-in. The public client invokes only the explicitly
selected executable, with a closed request, a minimal environment, and no shell.
The worker's temporary raw records are not copied into the public result. See
the [local wrapper status](../docs/agentbench-wrapper-implementation.md).

## Quick start from source

Requirements: Python 3.12–3.14 and a checkout of this repository.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install ./client
token-by-token --version
token-by-token episodes
token-by-token episode 2 describe
token-by-token capabilities --episode 2
token-by-token doctor --offline
token-by-token episode 2 selftest --offline --output ./token-by-token-selftest.tbt.zip
token-by-token evidence verify ./token-by-token-selftest.tbt.zip
```

The output archive must not already exist. A successful self-test reports the
`synthetic_mock` classification and the SHA-256 digest of its canonical
`inventory.json`. This content identity is not the checksum of the `.tbt.zip`
archive itself. The self-test proves that the public
contract, deterministic fake engine, bundle writer, and verifier work together;
it is not latency, throughput, quality, capacity, cost, vLLM, or SGLang evidence.

## Explore every episode

`token-by-token episodes` lists the Episode 00–16 catalog. Every episode uses
the same commands:

```bash
token-by-token episode 0 describe
token-by-token episode 1 describe
token-by-token episode 2 describe
token-by-token episode 16 describe

token-by-token episode 0 selftest --offline --users 4 --seed 42 --output ./episode-00.tbt.zip
token-by-token episode 1 selftest --offline --users 16 --seed 42 --output ./episode-01.tbt.zip
token-by-token episode 2 selftest --offline --users 4 --seed 42 --output ./episode-02.tbt.zip
token-by-token episode 16 selftest --offline --users 8 --seed 42 --output ./episode-16.tbt.zip
```

Use only a `--users` value declared by `episode N describe`. `--seed` controls
the deterministic synthetic stream. Episode 06 is the only current contract
that identifies speculative decoding as a future study variable; no CLI switch
claims that the capability exists today.

### Command reference

```text
token-by-token episodes
token-by-token capabilities --episode EPISODE [--format human|json]
token-by-token doctor --offline [--format human|json]
token-by-token episode EPISODE describe [--format human|json]
token-by-token episode EPISODE selftest --offline
    [--users USERS] [--seed SEED]
    --output NEW_FILE.tbt.zip [--format human|json]
token-by-token episode 1 run-local --worker AGENTBENCH_WORKER
    --output NEW_FILE.tbt.json [--format human|json]
token-by-token evidence verify FILE.tbt.zip [--format human|json]
```

- `EPISODE` is an integer from 0 through 16.
- `capabilities` reports no real models, GPUs, load profiles, or run path. The
  local binary's separate capability document contains only the loopback mock.
- `doctor --offline` creates, verifies, and removes a temporary synthetic bundle.
  It checks installation plumbing only and is not the hands-on AgentBench run path.
- `--users` must be one of the values printed by `episode EPISODE describe`.
- Omitting `--users` selects that episode's first declared diagnostic load.
- `--seed` accepts 0 through 2,147,483,647 and makes the offline event stream
  repeatable.
- `--output` must name a new `.tbt.zip` file inside an existing directory. The
  client refuses to overwrite it.
- `--format json` is intended for scripts and CI.
- `run-local` requires an executable built from the reviewed private AgentBench
  source. Verify its checksum before use. Its current aliases are fixed to the
  synthetic mock; no endpoint, provider token, engine flag, or profile path is
  accepted. The `.tbt.json` result is not a signed recorded-evidence bundle.

For machine-readable output, add `--format json` to `describe`, `selftest`, or
`evidence verify`.

## Run the local AgentBench diagnostic

Build or obtain a reviewed `agentbench-worker` candidate for your platform,
verify its checksum, and run:

```bash
token-by-token episode 1 run-local \
  --worker /absolute/path/to/agentbench-worker \
  --output ./episode-01-loopback.tbt.json
```

The worker runs the real AgentBench coordinator and a worker process against
its own loopback HTTP streaming server. The output is a sanitized
`synthetic_mock` diagnostic with request counts and aggregate timing. It is
not a GPU measurement or a `.tbt.zip` recorded-evidence archive. The current
`evidence verify` command accepts the offline self-test archive format only.

## Verify an evidence bundle

The client writes `.tbt.zip` bundles with a detached `inventory.json`, canonical
JSON payloads, per-file hashes, sizes, and one explicit classification. Verify a
bundle before using it:

```bash
token-by-token evidence verify ./episode-02.tbt.zip
```

Verification fails closed on path traversal, absolute paths, links, duplicate or
unlisted members, noncanonical names, hash mismatches, mixed classifications,
oversized entries, excessive aggregate size, and suspicious compression ratios.
Treat a valid bundle as integrity-checked input, not as proof that a real
benchmark ran. The current writer emits only `synthetic_mock` bundles.

A successful archive contains a deterministic event stream, replay summary and
an inventory binding every member to its size and
SHA-256 digest. `evidence verify` validates the archive before reporting its
classification and canonical `inventory.json` digest. Use `shasum -a 256` (or
`sha256sum`) separately when you need the checksum of the archive file itself.
Do not upload a `synthetic_mock` archive as recorded
evidence or compare its timing-like values with Episode 00 or Episode 01.

## Website and dashboard

The website is a static reader for publication-reviewed aggregate evidence; it
does not execute the client and does not ingest the offline self-test archive.
Run it separately from the repository root:

```bash
npm --prefix dashboard ci
npm --prefix dashboard run dev -- --port 5173
```

Then open `http://127.0.0.1:5173/#episodes`. Recorded Episode 00 and Episode 01
data is embedded in the static bundle. The local loopback result is not yet a
dashboard input. A real local result would require reviewed sanitization and
recorded-evidence verification before dashboard import.

## Candidate standalone executable

Maintainers can build a platform-specific candidate in a fresh, locked build
environment:

```bash
cd client
python3 scripts/build_binary.py
cd ..
client/dist/token-by-token --version
cd client/dist
shasum -a 256 -c SHA256SUMS
```

On Linux, use `sha256sum -c SHA256SUMS` instead of `shasum`. The build audits the
PyInstaller module inventory and extracted archive contents, runs a binary
self-test, and emits `client/dist/SHA256SUMS`. Build products are intentionally
ignored by Git. Pull-request CI uploads a candidate artifact for maintainers but
does not publish a package or GitHub release.

Do not treat an unsigned CI artifact as a public release. Release still requires
the gates in [the client release checklist](../docs/client-release-checklist.md).

## Development checks

```bash
PYTHONPATH=client/src python3 -m unittest discover -s client/tests -p 'test_*.py' -v
(cd client && python3 scripts/build_binary.py)
```

Client code must stay independent of private runtimes, raw data, deployment
profiles, credentials, and provider SDKs. See [SECURITY.md](SECURITY.md),
[THREAT-MODEL.md](THREAT-MODEL.md), and the repository
[contribution guide](../CONTRIBUTING.md).

## Availability and support

- Source state: unreleased candidate in the repository.
- Offline self-test: implemented for Episodes 00–16.
- Real GPU benchmark runs: unavailable.
- Package registry and GitHub release: unpublished.
- Public support and security-reporting contacts: pending owner approval.

Repository licensing and contribution terms are defined at the repository
root. A source license does not make private AgentBench profiles or benchmark
corpora public. A distributable binary can be inspected; it must be audited
before release for embedded private content.

Episode 02 can write an explicit bounded selection through a reviewed worker:

```bash
token-by-token capabilities --episode 2 --worker /absolute/path/to/reviewed-worker --format json
token-by-token episode 2 select --worker /absolute/path/to/reviewed-worker \
  --mixture public-fixture-v1 --model loopback-model --gpu none \
  --output selection.json --format json
```

The request binds the formal protocol and capability digest and matches an approved combination. The synthetic aliases above require an `offline_verified` capability. Recorded aliases require a fresh `provider_verified` proof from the private operator; current actual provider execution remains unavailable. This command writes a new private file and grants no resource or spending authority. The historical `describe` and offline self-test formats remain separate from the formal measured contract.

A provider capability includes `observed_at` and `expires_at`; its validity window is at most fifteen minutes. The public mixture always declares twelve model turns per block. Offline proof may last at most one day. The binary audit requires the selection module and both packaged schemas before an updated client can pass its import/resource closure check.
