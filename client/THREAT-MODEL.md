# Public client threat model

## Assets and trust boundary

The public client protects the user's workstation, local files, command output,
and the meaning of an evidence classification. Its trusted computing base is the
checked-out client source, locked build dependencies, Python runtime or reviewed
standalone executable, and the local operating system.

The client currently performs only four operations: list public episodes,
describe a public contract, run a deterministic offline synthetic self-test, and
verify a bounded `.tbt.zip` archive. It has no authenticated service, provider
adapter, telemetry upload, auto-update path, or recorded-evidence signature
authority.

## Threats and controls

### Malicious archives

An attacker may use traversal, absolute paths, links, duplicate names, unlisted
members, hash confusion, oversized payloads, or compression bombs. Verification
enumerates the archive before reading payloads, requires canonical member names
and a detached inventory, rejects links and duplicate/unlisted entries, checks
declared sizes and SHA-256 digests, and applies per-entry, aggregate-size, and
compression-ratio limits. Verification does not extract into the user's working
tree.

Residual risk: parser or compression-library defects remain possible. Open only
bundles from a known source and keep the runtime patched.

### Environment and network leakage

A local tool could accidentally read environment variables, host identity,
credentials, clocks, or network services and embed them in output. The synthetic
engine uses explicit inputs and deterministic constants. Source tests replace
socket and DNS entry points, and Linux CI executes source and standalone
self-tests in a separate network namespace under syscall tracing. Bundle schemas
admit only the expected public fields.

Residual risk: non-Linux platforms do not receive the same syscall proof in CI.
The code review and schema boundary remain required.

### Binary supply chain

A compromised dependency or build worker could alter a candidate. Build tooling
and transitive dependencies are version- and hash-locked. The build runs in a
fresh temporary environment, emits a checksum, scans its module/resource
inventory, extracts nested PyInstaller archives, and executes the result.

Residual risk: candidates are not yet signed, notarized, accompanied by an SBOM,
or published through an approved release channel. A checksum from the same
compromised worker is not independent attestation. These are release blockers.

### Accidental private-content inclusion

Broad import paths or package-data rules could include private modules, profiles,
raw exports, credentials, or deployment recipes. The standalone specification
points only at `client/src` and explicit public JSON resources. A fail-closed
audit rejects forbidden module roots, resource paths, and high-confidence private
markers in the executable and extracted contents. Repository publication scans
remain mandatory.

Residual risk: no heuristic scanner proves absence. Review the staged diff,
binary inventory, extracted payloads, images, metadata, and reachable Git history.

### Evidence-classification confusion

A synthetically generated bundle could be presented as measured evidence. Every
manifest, event stream, replay, inventory, CLI success message, and verifier
result carries the `synthetic_mock` classification. The self-test states that it
validates plumbing only. The verifier rejects mixed classifications.

Residual risk: a user can remove surrounding explanatory text or make a false
claim. Recorded evidence will require a separately designed signature and
provenance model; this client does not provide one.

### Future hosted and cross-tenant risks

Hosted execution would introduce authentication, authorization, tenant
isolation, rate and spend limits, request privacy, artifact access control,
retention/deletion, abuse handling, worker trust, and auditability. None of those
controls exists in this release. The CLI therefore offers no submit, login,
provider, or remote-run command. Adding one requires a separate threat model and
reviewed implementation plan.

## Security invariants

1. `selftest` requires the literal `--offline` flag.
2. The self-test never performs a provider or network operation.
3. Only declared per-episode controls are accepted.
4. Output paths must end in `.tbt.zip` and must not already exist.
5. The current writer emits only `synthetic_mock` evidence.
6. Bundle verification fails closed on structural or integrity ambiguity.
7. A standalone candidate contains only the public client and public resources.
8. No CI job publishes a release or authorizes a paid benchmark.

Changes that weaken an invariant require security review, new negative tests,
and explicit owner approval.
