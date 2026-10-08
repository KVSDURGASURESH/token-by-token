# Token by Token client

The Token by Token client is an **unreleased public-client candidate** for
exploring the Episode 00–16 contracts and testing the evidence workflow on your
own machine. Its self-test is deterministic synthetic plumbing: it costs $0,
makes no provider call, starts no inference engine, and does not reproduce or
extend the recorded benchmark results.

Hosted benchmark submission is not available in this release. The private
benchmark service, deployment recipes, and serving profiles are not included.

## Quick start from source

Requirements: Python 3.12–3.14 and a checkout of this repository.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install ./client
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

- Source state: unreleased candidate on the feature branch.
- Offline self-test: implemented for Episodes 00–16.
- Real benchmark submission: unavailable.
- Package registry and GitHub release: unpublished.
- Public support and security-reporting contacts: pending owner approval.

The absence of a license in the repository means redistribution and external
contribution remain pending the owner's licensing decision.
