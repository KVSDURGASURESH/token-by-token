# Token by Token client

The Token by Token client is an **unreleased public-client candidate** for
exploring the Episode 00–16 contracts and testing the evidence workflow on your
own machine. Its self-test is deterministic synthetic plumbing: it costs $0,
makes no provider call, starts no inference engine, and does not reproduce or
extend the recorded benchmark results.

Hosted benchmark submission is not available in this release. The private
benchmark service, deployment recipes, and serving profiles are not included.

## What works today

| Capability | Command | Status |
| --- | --- | --- |
| List the curriculum | `token-by-token episodes` | Available |
| Inspect an episode and its allowed loads | `token-by-token episode N describe` | Available |
| Exercise the client and bundle pipeline without a GPU | `token-by-token episode N selftest --offline …` | Available |
| Verify an emitted bundle and its classification | `token-by-token evidence verify FILE` | Available |
| Select a real model or GPU | — | Not yet available |
| Submit a real AgentBench run | — | Not yet available |
| Import a personal run into the hosted dashboard | — | Not yet available |

The current executable is therefore an installation and evidence-pipeline
diagnostic. It is not the AgentBench wrapper promised by the hosted-service
design. The planned real path keeps AgentBench private behind an authenticated
service, validates a small allowlist of episode/model/GPU/load aliases, returns
a quote for explicit approval, and emits a sanitized `.tbt.zip` result. See the
[real wrapper specification](../docs/superpowers/specs/2026-10-08-real-agentbench-wrapper-and-shared-campaign-design.md).

## Quick start from source

Requirements: Python 3.12–3.14 and a checkout of this repository.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install ./client
token-by-token --version
token-by-token episodes
token-by-token episode 2 describe
token-by-token episode 2 selftest --offline --output ./token-by-token-selftest.tbt.zip
token-by-token evidence verify ./token-by-token-selftest.tbt.zip
```

The output archive must not already exist. A successful self-test reports the
`synthetic_mock` classification and a SHA-256 digest. It proves that the public
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
token-by-token episode EPISODE describe [--format human|json]
token-by-token episode EPISODE selftest --offline
    [--users USERS] [--seed SEED]
    --output NEW_FILE.tbt.zip [--format human|json]
token-by-token evidence verify FILE.tbt.zip [--format human|json]
```

- `EPISODE` is an integer from 0 through 16.
- `--users` must be one of the values printed by `episode EPISODE describe`.
- Omitting `--users` selects that episode's first declared diagnostic load.
- `--seed` accepts 0 through 2,147,483,647 and makes the offline event stream
  repeatable.
- `--output` must name a new `.tbt.zip` file inside an existing directory. The
  client refuses to overwrite it.
- `--format json` is intended for scripts and CI.
- Endpoint, provider, token, model, GPU, engine flags and arbitrary profile
  inputs are intentionally rejected because no real execution service exists.

For machine-readable output, add `--format json` to `describe`, `selftest`, or
`evidence verify`.

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

A successful archive contains a public episode manifest, deterministic event
stream, replay summary and an inventory binding every member to its size and
SHA-256 digest. `evidence verify` validates the archive before reporting its
classification and digest. Do not upload a `synthetic_mock` archive as recorded
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
data is embedded in the static bundle. A future authenticated collection path
will sanitize real AgentBench output before a personal dashboard can load it;
that path is specified but not implemented.

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
- Real benchmark submission: unavailable.
- Package registry and GitHub release: unpublished.
- Public support and security-reporting contacts: pending owner approval.

Repository licensing and contribution terms are defined at the repository
root. A source license does not make the private AgentBench service, deployment
profiles or benchmark corpus public.
