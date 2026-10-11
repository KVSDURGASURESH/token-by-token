---
handoff_version: 1
created_utc: 2026-09-29T04:02:32Z
topic: episode-1-quick-test-launcher
repository: KVSDURGASURESH/token-by-token
branch: codex/episode-1-local-prep
baseline_commit: eaf5f35dce80705860c11aff7df9d6e87de1fdc0
status: local-launcher-verified-live-provider-inputs-pending
---

# Episode 1 quick-test launcher handoff

## Resume point

This update adds one entry point for the browser dashboard, loopback bridge,
and matching CLI. After pulling this handoff commit, run:

```bash
scripts/quick-test demo
```

Open <http://127.0.0.1:8765/#quick-test>. Leave the launcher running and use a
second terminal for `scripts/quick-test request` or
`scripts/quick-test compare`. On a fresh checkout, the launcher runs the pinned
dashboard dependency install and build only when `dashboard/dist/index.html`
is absent.

## Ownership and scope

- Implementation owner: the current root Codex task in the RUNPOD worktree.
- Receiving owner: the agent or operator on the other machine after verifying
  the clean checkout.
- Model and reasoning: no tool-confirmed model override was available, so this
  record does not claim one.
- Scope: local quick-test launcher, browser/CLI documentation, and durable
  cross-machine handoff only.
- Excluded: operator-image build, provider authentication, paid resource
  creation, formal Episode 1 execution, or publication.
- Acceptance criteria: one command launches the local dashboard and bridge;
  CLI single and comparison requests use that bridge; fresh clones bootstrap
  pinned frontend packages when network access is available.
- Review/fix budget: one bounded validation round used for this launcher; two
  rounds remain. Do not broaden later rounds beyond these acceptance criteria.

## Verification completed

- `sh -n scripts/quick-test`: passed.
- `scripts/quick-test help`: passed.
- `scripts/quick-test demo`: launched on loopback.
- Dashboard root: HTTP 200 with the React mount point present.
- Capabilities endpoint: HTTP 200 with both built-in profiles.
- CLI `request`: completed and wrote a nonempty aggregate result.
- CLI two-lane `compare` with two repetitions: completed and wrote a nonempty
  aggregate result.
- Relevant Python live-scaffolding tests: 7 passed.

The local pinned `npm ci` verification could not complete because this host
could not resolve the configured package registries. The already-built ignored
dashboard assets were sufficient for the runtime integration checks. A fresh
machine must have npm registry access for first-run bootstrap. This is an
environmental verification gap, not permission to commit generated
`node_modules` or `dashboard/dist` artifacts.

## Live RunPod boundary

The launcher is ready for the local demo and for a pre-existing configured
OpenAI-compatible endpoint. It does not create a RunPod resource. The live
provider run remains blocked until authenticated RunPod access supplies fresh
account, inventory, offer, rate, SSH/access, and guard observations and the
owner approves the resulting exact digest-bound plan and maximum charge.

No pod, endpoint, volume, image, model, provider mutation, or paid resource was
created during this update.
