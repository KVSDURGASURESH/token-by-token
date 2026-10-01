# Cross-machine handoffs

This directory is the durable, repository-visible handoff log for work that
will continue in another Codex task or on another machine. Handoffs are
append-only Markdown files named with a UTC timestamp:

```text
YYYY-MM-DDTHH-MM-SSZ-<short-topic>.md
```

## Current handoff

- [2026-10-01T07-39-48Z — Episodes 1–16 local stack](2026-10-01T07-39-48Z-episode-suite-local-stack.md)

## Update convention

When ownership moves again:

1. Keep the prior handoff unchanged.
2. Add a new UTC-timestamped file containing the branch, baseline commit,
   completed verification, unresolved work, safety boundaries, and exact next
   actions.
3. Move the **Current handoff** link above to the new file.
4. Commit and push both files so the receiving machine reads the same state.

Do not place credentials, private provider observations, approvals, complete
environment files, or unsanitized runtime evidence in this directory.
