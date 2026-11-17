# Public client release checklist

The Token by Token client is currently an unreleased candidate. This checklist
is the minimum release gate; a passing local build alone is not a production or
public-release approval.

## Ownership and policy

- [ ] Name the release owner, security owner, and rollback owner.
- [ ] Approve code, documentation, evidence-format, and bundled-data licenses.
- [ ] Approve product name, trademarks, attribution, and third-party notices.
- [ ] Publish a verified private security-reporting route in
      `client/SECURITY.md` and define supported versions and response targets.
- [ ] State clearly that local loopback execution is synthetic and no hosted
      benchmark service exists.
- [ ] Confirm public documentation contains no private tool identity,
      organization identity, profiles, endpoints, credentials, payloads, raw
      exports, or internal deployment recipes.

## Source and behavior

- [ ] Review the release diff and reachable Git history.
- [ ] Confirm Episodes 00–16 have valid public manifests and accurate
      recorded/planned labels.
- [ ] Run the complete client test suite, including hostile-bundle tests.
- [ ] Prove the source and binary self-tests make no network syscall in the
      Linux CI network namespace.
- [ ] Confirm every generated artifact is labeled `synthetic_mock` and cannot
      be mistaken for recorded benchmark evidence.
- [ ] Run the repository privacy scanner against source and built contents.
- [ ] Verify the only added run path is the allowlisted local loopback mock;
      no provider, paid-run, login, or auto-update path is present.
- [ ] Verify the local worker schemas and binary contain no private profiles,
      corpus content, provider identifiers, endpoints, or credentials.

## Reproducible build and supply chain

- [ ] Build from the complete hash-locked dependency file in a clean runner.
- [ ] Archive the build log, compiler/runtime versions, source commit, and CI
      workflow identity.
- [ ] Review the PyInstaller analysis inventory and recursively extracted
      archive audit.
- [ ] Generate an SBOM for the exact platform artifact and review its licenses
      and known vulnerabilities.
- [ ] Produce SHA-256 checksums from the final immutable artifacts.
- [ ] Code-sign each platform artifact; notarize where the platform requires it.
- [ ] Verify signatures and checksums on a separate clean machine.
- [ ] Re-run `--version`, one Episode 00 self-test, one Episode 16 self-test,
      and evidence verification from each final artifact.

## Documentation and usability

- [ ] Execute every command in `client/README.md` from a clean checkout.
- [ ] Confirm the README states $0, offline, synthetic-only behavior prominently.
- [ ] Confirm real GPU runs and recorded replay remain unavailable unless a
      separately approved release implements them.
- [ ] Document supported operating systems, architectures, Python versions,
      installation, uninstall, known limitations, and rollback.
- [ ] Verify links, examples, accessibility, and deterministic documentation URLs.

## GitHub release and rollback

- [ ] Obtain the owner's explicit approval for the exact commit, tag, version,
      artifact checksums, release notes, and public visibility.
- [ ] Create an immutable signed tag only after approval.
- [ ] Publish through a protected release workflow with least-privilege
      permissions; do not publish from a developer workstation.
- [ ] Attach checksums, signatures, SBOMs, notices, and verification commands.
- [ ] Install from the public release on clean supported systems and record the
      evidence.
- [ ] Verify the documented revocation/rollback procedure and responsible owner.
- [ ] Record final development, staging, and production evidence separately;
      label any unverified environment as unverified.

## Explicitly separate follow-on work

Real local GPU execution, recorded-evidence verification, provider action,
public Grafana, and paid measurements require independent security review and
owner approval. Releasing this synthetic local diagnostic does not authorize
any of them.

For Episode 02, run `client/tests/test_episode2_selection.py` with the existing local-worker, hostile-bundle and binary/import audit tests. Verify exact combination rejection, expired proof rejection, duplicate/nonfinite JSON rejection, exclusive private output and symlink-ancestor rejection. Package both `episode2-selection.v1` and `episode2-capabilities.v1` schemas. A synthetic selection pass does not verify a provider, paid run or hosted environment; worker distribution still requires the reviewed inventory and owner release authority.
