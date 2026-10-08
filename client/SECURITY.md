# Client security policy

## Current status

This client is an unreleased candidate. A public security-reporting address has
not yet been approved. Until the owner supplies and verifies that route, do not
publish suspected vulnerabilities, malicious bundles, credentials, private
endpoints, or internal configuration in a public issue.

If you already have authorized private access to the repository, use the
repository host's private security-advisory workflow or the owner's existing
private contact channel. Otherwise, wait for the public reporting route before
sharing sensitive details. This missing contact is a release blocker.

## Supported versions

No version is publicly supported yet. The source candidate and CI artifacts are
provided for review, not as a security-supported release. A future release must
state its supported versions and remediation policy here.

## What to report

- archive traversal, link, duplicate-entry, size, compression, or hash bypasses;
- network access during an offline self-test;
- environment, hostname, credential, or request-payload leakage;
- inclusion of private modules, profiles, data, or identifiers in a candidate;
- classification confusion between synthetic and recorded evidence; and
- dependency, build, signing, checksum, or update-channel compromise.

Include the client version or commit, platform, exact command, minimal safe
reproducer, expected result, and observed result. Redact secrets and private
infrastructure details. Do not attach a live credential or private evidence.

## Security boundary

The client describes public episode contracts, runs a deterministic local fake
engine, creates a bounded synthetic archive, and verifies that archive. It does
not contain the private benchmark service, provider credentials, serving
profiles, hosted submission, an updater, or a trust root for signed recorded
evidence. See [THREAT-MODEL.md](THREAT-MODEL.md) for the detailed boundary.
