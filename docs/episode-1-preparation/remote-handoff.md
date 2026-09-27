# Episode 1 remote-machine handoff

For agent-to-agent continuation, first read the timestamped
[`handoffs/` log](../../handoffs/README.md), which records the current branch,
baseline commit, completed checks, ownership, and remaining gates.

This checkout is the source-complete Episode 1 handoff. It includes the pinned
standard-benchmark contract, candidate runtime specification, compiler,
authorization verifier, RunPod adapter, fresh-process supervisor, capture and
cleanup paths, dashboard, fixtures, schemas, and offline tests. It does not
include secrets, private provider observations, model weights, or a built
operator image.

## 1. Pull and verify

```bash
git clone --branch codex/episode-1-local-prep \
  https://github.com/KVSDURGASURESH/token-by-token.git
cd token-by-token
git rev-parse HEAD

python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install '.[test]'
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/check_publication_privacy.py
python scripts/update_episode_index.py --check
```

Compare the printed commit with the commit named in the publisher's handoff.
Keep provider credentials and every generated private input outside the
repository in a directory with mode `0700`.

## 2. Inspect locally without building or renting a GPU

The standardized profile is
`fixtures/episode1/benchmark-standard.json`. It pins a ShareGPT serving
workload and the `lm-evaluation-harness` GSM8K quality guard. The checked-in
Episode 1 planning fixture is deliberately non-executable.

To inspect the local quick-test CLI:

```bash
PYTHONPATH=src .venv/bin/python scripts/episode1_playground.py --help
PYTHONPATH=src .venv/bin/python scripts/compile_episode1_execution.py --help
PYTHONPATH=src .venv/bin/python scripts/execute_episode1.py --help
```

The browser dashboard is optional and its build is not required for the
RunPod handoff. If wanted, follow `docs/episode-1-preparation/quick-test.md`.

## 3. Complete the machine-specific gates

Read these files in order before any paid action:

1. `runtime/episode1/README.md`
2. `docs/episode-1-preparation/runtime-preflight.md`
3. `docs/episode-1-preparation/execution-architecture.md`
4. `docs/episode-1-preparation/operator-preflight.md`

The candidate Dockerfile intentionally refuses an unpinned build. On the
remote machine, produce and verify the required build inputs and operator-image
digest, then create the private build attestation. Obtain fresh RunPod offer,
stock, account, SSH, storage, and deletion-guard observations. Do not commit
any of those private artifacts.

Compile the private execution candidate with
`scripts/compile_episode1_execution.py`. A candidate with unresolved inputs
must remain blocked and must not emit a usable approval phrase. Run
`scripts/execute_episode1.py preflight` before considering `run`.

## 4. Authorization boundary

No repository command, commit, planning fixture, or prior approval authorizes
resource creation. Do not create a Pod, endpoint, volume, or other paid
resource until the current plan binds the exact operator-image digest, offer,
maximum charge, guard mode, material hashes, and cleanup contract, and the
owner gives the exact digest-bound approvals required by that plan.

After an authorized run, permanently delete every resource the run created and
verify deletion using a fresh complete provider inventory plus direct
not-found lookups. A stopped resource or successful delete request alone is
not cleanup proof.
