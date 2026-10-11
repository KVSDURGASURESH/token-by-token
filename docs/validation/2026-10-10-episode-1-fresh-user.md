# Episode 1 fresh-user check — 2026-10-10

Scope: public GitHub checkout and the zero-cost Episode 1 path. No Pod, paid
provider call, private AgentBench run, real latency sample, or publication was
part of this check.

The published checkout at `fad1452` was cloned into a new directory. On this
macOS host `python3` resolved to Python 3.9.6, below the documented minimum;
Python 3.12.13 was selected explicitly. The published first verifier returned
`integrity[checksum-missing] at bundle-entry` because the already committed
`runpod-billing-summary.json` was omitted from `checksums.sha256`. The published
full unittest command with `.[test]` ended with 2 failures and 4 errors, including
an installed-package source-root error and an absent locked live dependency.

This change adds only the existing billing file's verified SHA-256
`d31fae6223e0dfb68b428d81b91db718726a9414fd54b44660634474135c70a1`
to the checksum manifest; the billing file bytes are unchanged. The README now
selects a supported Python explicitly, runs the focused offline tests, and
provides a direct Episode 1 synthetic path. Contributor and CI commands use
the lockfile, source path, and complete test dependency set.

Checks on the repaired isolated worktree:

- `python3.12 scripts/verify_bundle.py data/public` — `ok: true`.
- `python3.12 scripts/rehearse_workflow.py --output NEW_DIR` followed by
  `python3.12 scripts/verify_bundle.py NEW_DIR` — zero provider attempts;
  verification `ok: true`.
- README quickstart `python -m unittest discover -s tests -p
  'test_offline_workflow.py' -v` — 3 passed.
- `uv sync --locked --extra test --extra live --python python3.12`, then
  `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p
  'test_*.py' -q` — 562 tests, OK (3 skipped).
- `python -m pip install ./client`, then the README Episode 1 block —
  `synthetic_mock` bundle and valid verification; digest
  `c6c75eccfacbc31dd2629c2f29881fb760b14ca4cb10dfe141c4919e163efb23`.
- `npm --prefix dashboard ci`, `npm --prefix dashboard run check`, and
  `npm --prefix dashboard run build` — passed on local Node 24.14.0. The
  documented Node 22 CI lane was not verified locally.
- `python3.12 scripts/check_publication_privacy.py --root .` — no
  high-confidence findings; this is a heuristic check.
- Public Linux build reproduced the CI audit failure in a local `linux/amd64`
  container: its sole unapproved resource was `libgcc_s.so.1`. After allowing
  that exact root-level system library, the hash-locked build, extracted archive
  audit, offline self-test, and bundle verification passed in the same local
  container. A regression test rejects `vendor/libgcc_s.so.1`.

The public client reports real execution unavailable. The Episode 1 self-test
checks installation and evidence plumbing only. Live provider measurement,
upstream CI after these changes, package release, and public link readiness
remain unverified until this change is published and CI passes. The latest published CI run also fails its history privacy scan:
147 commit-metadata email findings and 23 old-file findings, including a real
private checkout path in earlier dashboard data. Current files pass the scan.
The historical findings need an owner-reviewed disposition; this change does
not suppress them or rewrite Git history.
