---
handoff_version: 1
created_utc: 2026-09-30T09:09:58Z
topic: all-episodes-experiment-planner
repository: KVSDURGASURESH/token-by-token
branch: codex/episode-1-local-prep
baseline_commit: 5fc1691c84811d46d010d020190937f3324d592f
status: implemented-local-verification-passed-frontend-build-pending
---

# All-episodes experiment planner handoff

## Outcome

The dashboard now represents Episode 0 plus all 16 canonical planned stages. Episodes 1–16 open a planning-only experiment configurator with versioned templates. It supports candidate vLLM and SGLang lanes, GPU type/count/nodes, model and tokenizer revisions, prompt/chat template identity, weight artifact, inference optimization requests, workload, quality gates, latency SLOs, and decimal-string cost inputs.

Exports are closed, digest-verified planning snapshots. They permanently retain `planning_only: true`, `execution_ready: false`, and `execution_authorized: false`. The planner has no provider adapter, endpoint, credentials, arbitrary runtime flags, shell command, Run button, or quick-test execution call.

## Ownership and bounded review

- Architecture owner: `gpt-6-astra` with ultra reasoning, planning only; it stopped before implementation.
- Implementation owner: `gpt-5.6-sol` with medium reasoning, bounded to the dashboard/catalog/schema/tests/docs changes.
- Final integration and review owner: the root task; one consolidated review/fix round completed.
- Acceptance criteria: full Episode 0–16 catalog; configurable experiment design; honest capability states; deterministic import/export; fail-closed validation; no live execution path; existing tests preserved.
- Review budget: one of at most three rounds used; two rounds remain. Any next review should verify the recorded frontend gap and the original acceptance criteria, not restart a broad redesign.

## Verification completed

- Full Python suite: `525 passed, 3 skipped in 72.15s`.
- Episode index generator check: passed.
- Publication privacy check: passed, subject to its documented heuristic limitation.
- Public bundle verifier: passed with no errors or warnings.
- Planner browser-acceptance script parses under Node.
- Review findings EP-001 and EP-002 were fixed; see the ignored local review record `context/review-experiment-planner-2026-09-30.md`.

## Receiving-machine checks

The current host could not install the pinned dashboard dependencies: `npm ci` made no progress and `tsc` is unavailable. After pulling the eventual handoff commit on a machine with registry access, run:

```bash
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
```

Then serve the dashboard on `127.0.0.1:5173` and run `node tests/dashboard_planner_acceptance.cjs`. Verify `#experiment-planner?episode=8` at 390 px and 1440 px, with no overflow, console errors, provider traffic, or execution action.

## Safety and remaining work

This is a planning surface, not evidence that Episodes 1–16 have been measured. Episode 0 remains the sole exploratory recorded study; Episode 1 remains a local contract fixture; Episodes 2–16 have no measurements. No pod, endpoint, volume, paid session, provider mutation, model download, or live benchmark was created or run.

Any future paid experiment still requires a freshly compiled exact plan, current provider evidence, an approval digest distinct from the planning-config digest, the owner's exact maximum-charge approval, and verified permanent deletion of every created resource.
