# Portable workspace map

Resolve all paths from the current repository root. Do not put absolute home-directory paths, credentials, private resource identifiers, or private remote URLs into publication artifacts.

## Discover the active sources

Use repository search rather than assuming the dated example remains current:

```bash
git rev-parse --show-toplevel
rg --files docs manifests | sort
find docs/experiments -type f \( -name 'manifest.json' -o -name 'plan.json' -o -name 'report.md' -o -name 'roadmap.md' -o -name '*capstone*.md' \) -print
```

For the requested episode, identify and read its active manifest, compiled plan, normalized benchmark data, runtime/GPU telemetry summaries, teardown record, checksums, reproduction notes, and publication drafts. Prefer the experiment's `public/` sanitized bundle for public facts, while checking its values against private retained evidence when access is authorized. Do not publish ignored/private evidence.

The current workspace's retained Episode 0 material can be discovered beneath:

```text
docs/experiments/*/publication-drafts/episode-0/
docs/experiments/*/public/
```

The consolidated Episode 0 `capstone-projects.md` and `roadmap.md` are source material. Keep these as one canonical capstone catalog and one canonical roadmap in the reusable GitHub package. Do not turn dated paths into permanent product structure.

## Locate reusable code and packaging inputs

Relevant repository-relative areas are:

```text
src/runpod_benchmark/          reusable metrics and streaming code
scripts/                       planning, rehearsal, collection, normalization, and publication helpers
dashboard/                     local dashboard application
manifests/                     manifest schema and examples
skills/runpod-inference-benchmark/  experiment planning/execution contract
docs/experiments/              retained studies and publication sources
```

Existing episode package candidates may live under an episode's `github/` directory. Treat them as inputs to inspect, not as automatically current output.

## Target evergreen repository shape

When creating or upgrading the public learning project, use the existing structure if it already satisfies the contract. Otherwise converge on a portable layout such as:

```text
README.md
dashboard/src/data/episodes.json
episodes/TEMPLATE.md
episodes/<episode-slug>/README.md
episodes/<episode-slug>/figures/
docs/roadmap.md
docs/capstone-projects.md
docs/runpod-setup.md
dashboard/
scripts/
```

The exact filenames may follow an established repository convention, but there must be one authoritative registry, one maintained roadmap, one capstone catalog, and a reusable episode template. Run `python3 scripts/update_episode_index.py` to generate the root episode table of contents; CI runs the same command with `--check`.

## Rediscover external state

Before describing or changing the GitHub destination, inspect rather than hardcode:

```bash
git remote -v
git branch --show-current
git status --short
find . -maxdepth 2 -iname 'LICENSE*' -o -iname 'COPYING*'
```

When authenticated tooling is available and the user has asked for GitHub work, query the repository for its visibility, default branch, current head, and license state. Sanitize command output before recording it. The known repository from a prior task may be private and license-pending, but that is historical context only; no skill output should assert it without a fresh read. Never assign a new license on the user's behalf.

For Runpod setup material, verify links and UI terminology against current official documentation at publication time. Keep provider resource creation outside this publication skill unless the user separately invokes and authorizes the experiment workflow with an exact plan digest and maximum charge.
