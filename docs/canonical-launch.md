# Canonical launch from the dashboard

The `#canonical-launch` dashboard route is a narrow UI over the existing Episode 1
production command. It is not the endpoint rehearsal runner, and it does not make the
other episode prompt packs canonical.

## Safety and configuration

Create a private launch bundle from `examples/canonical-launch-bundle.example.json`.
All paths in it are repository-relative and are selected when the loopback server
starts; the browser cannot supply paths, provider adapters, executables, or arbitrary
flags. The JSON keys map one-to-one to the flags of `scripts/execute_episode1.py`.

Start in read-only mode first:

```text
python scripts/episode1_playground.py serve \
  --canonical-launch-bundle .private/episode1/canonical-launch.json
```

The dashboard preflight performs the same validation as this CLI command and creates
no provider resource:

```text
python scripts/execute_episode1.py preflight <the fixed bundle flags>
```

Only after the owner has supplied the exact plan-digest/max-charge approval and the
immutable authorization source and receipt have been retained should the operator
restart with `--enable-canonical-launch`. The dashboard additionally requires the
exact digest-bound approval phrase. That typed phrase is only an accidental-click
guard: `execute_episode1.py run` revalidates the retained authorization, plan, build,
source commit, material closure and freshness before creation. The existing
orchestrator captures private evidence and does not report completion until deletion
is acknowledged and provider reads prove the resource absent.

No paid launch is part of repository validation. Tests inject a command executor and
exercise the real orchestrator lifecycle with provider/runtime fixtures.

## Current boundary

Only Episode 1 has a repository-owned canonical RunPod workload adapter. Episodes
2–16 require genuine adapters or an architecture decision; the endpoint rehearsal
packs remain useful diagnostics but are not canonical experiments. In particular,
Episode 10 needs an existing-cluster versus temporary-cluster decision, Episode 11
needs TensorLab instrumentation, Episode 12 needs LoRA/QLoRA training and quality
capture, and Episode 13 needs a selected Jev API/version. Runtime GPU/SKU, model
revision, image digests, maximum price and approval are bound inputs, not missing
launch software.
