#!/usr/bin/env python3
"""Deterministic, value-free privacy checks for a publication checkout.

This is a narrow heuristic gate, not a proof that content is free of secrets.
It reports only a location and finding category; matched text is never emitted.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dependencies",
    "dist",
    "generated",
    "node_modules",
    "site-packages",
    "vendor",
    "venv",
}
MAX_TEXT_BYTES = 8 * 1024 * 1024
LOCKFILE_NAMES = {
    "Cargo.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
RESERVED_EMAIL_DOMAINS = {"example.com", "example.net", "example.org", "test.invalid"}
PRIVATE_HOST_SUFFIXES = (
    ".corp",
    ".internal",
    ".lan",
    ".local",
)

PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)
TOKEN_PATTERNS = (
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\brp_[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Z0-9_.-])"
    r"[\"']?(?:API[_-]?KEY|ACCESS[_-]?KEY(?:[_-]?ID)?|SECRET[_-]?ACCESS[_-]?KEY|"
    r"AUTHORIZATION|PASSWORD|PASSWD|TOKEN|SECRET|CLIENT[_-]?SECRET|PRIVATE[_-]?KEY)"
    r"[\"']?(?![A-Z0-9_.-])\s*(?:"
    r":\s*[\"']([^\"'\r\n]{6,})[\"']|"
    r"=\s*(?:[\"']([^\"'\r\n]{6,})[\"']|([A-Za-z0-9_+/=-]{16,})))"
)
URL_RE = re.compile(r"\b(?:https?|wss?|ssh)://[^\s<>\"']+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
POSIX_HOME_RE = re.compile(r"(?<![A-Za-z0-9_.-])/(?:Users|home)/[^/\s'\"<>]+(?:/[^\s'\"<>]*)?")
WINDOWS_HOME_RE = re.compile(r"(?i)(?<![A-Z0-9_])(?:[A-Z]:)?\\Users\\[^\\\s'\"<>]+")
HOST_PORT_RE = re.compile(
    r"(?<![A-Z0-9_.-])(?:\[([0-9A-F:.%]+)\]|"
    r"((?:[A-Z0-9-]+\.)+[A-Z0-9-]+|(?:\d{1,3}\.){3}\d{1,3}))"
    r":(?:[1-9]\d{0,4})(?!\d)",
    re.IGNORECASE,
)
IP_RE = re.compile(r"(?<![A-F0-9:.])(?:\d{1,3}\.){3}\d{1,3}(?![A-F0-9:.])", re.IGNORECASE)
PRIVATE_NAME_RE = re.compile(
    r"\b[A-Z0-9-]+(?:\.[A-Z0-9-]+)*(?:\.corp|\.internal|\.lan|\.local)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class Finding:
    location: str
    line: int
    category: str

    def render(self) -> str:
        return f"file={self.location} line={self.line} category={self.category}"


class PrivacyCheckError(RuntimeError):
    """Operational failure that does not include scanned content."""


def _run_git(root: Path, *args: str, text: bool = False) -> bytes | str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=text,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrivacyCheckError("git command failed") from exc
    if completed.returncode != 0:
        raise PrivacyCheckError("git command failed")
    return completed.stdout


def _repository_root(root: Path) -> Path | None:
    try:
        literal = str(_run_git(root, "rev-parse", "--show-toplevel", text=True)).strip()
    except PrivacyCheckError:
        return None
    resolved = Path(literal).resolve()
    return resolved if resolved == root else None


def _safe_git_path(raw: str) -> Path | None:
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    if any(part in EXCLUDED_DIRS for part in pure.parts):
        return None
    return Path(*pure.parts)


def _tracked_paths(root: Path) -> list[Path]:
    output = _run_git(root, "ls-files", "-z")
    assert isinstance(output, bytes)
    paths: list[Path] = []
    for item in output.split(b"\0"):
        if not item:
            continue
        try:
            relative = _safe_git_path(item.decode("utf-8", "strict"))
        except UnicodeDecodeError as exc:
            raise PrivacyCheckError("tracked path is not valid UTF-8") from exc
        if relative is None:
            raise PrivacyCheckError("tracked path is unsafe")
        paths.append(relative)
    return sorted(set(paths), key=lambda path: path.as_posix())


def _filesystem_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in EXCLUDED_DIRS)
        base = Path(directory)
        for name in sorted(files):
            path = base / name
            relative = path.relative_to(root)
            if not any(part in EXCLUDED_DIRS for part in relative.parts):
                paths.append(relative)
    return paths


def publication_paths(root: Path, *, files_only: bool = False) -> list[Path]:
    """Return Git-tracked paths for a checkout, otherwise package files."""

    if not files_only and _repository_root(root) is not None:
        return _tracked_paths(root)
    return _filesystem_paths(root)


def _decode_text(data: bytes) -> str | None:
    if len(data) > MAX_TEXT_BYTES or b"\0" in data:
        return None
    try:
        return data.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return None


def _placeholder_or_reference(value: str) -> bool:
    normalized = value.strip("\"'`[](){}<>").lower()
    if not normalized:
        return True
    markers = (
        "change_me",
        "changeme",
        "dummy",
        "example",
        "fake",
        "placeholder",
        "redacted",
        "replace_me",
        "replace",
        "test",
        "your_",
    )
    if any(marker in normalized for marker in markers):
        return True
    if normalized.startswith(("$", "os.environ", "os.getenv", "process.env", "secretref", "vault")):
        return True
    return len(set(normalized)) <= 2


def _is_documentation_ip(address: ipaddress._BaseAddress) -> bool:
    networks = (
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
        ipaddress.ip_network("2001:db8::/32"),
    )
    return any(address in network for network in networks if address.version == network.version)


def _private_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.rstrip(".").lower()
    if normalized in {"localhost", "0.0.0.0", "::", "::1"}:
        return False
    try:
        address = ipaddress.ip_address(normalized.split("%", 1)[0])
    except ValueError:
        return normalized.endswith(PRIVATE_HOST_SUFFIXES)
    return (
        (address.is_private or address.is_link_local)
        and not address.is_loopback
        and not address.is_unspecified
        and not _is_documentation_ip(address)
    )


def _scan_line(location: str, line_number: int, line: str, *, lockfile: bool) -> set[Finding]:
    findings: set[Finding] = set()

    def add(category: str) -> None:
        findings.add(Finding(location, line_number, category))

    if PRIVATE_KEY_RE.search(line):
        add("private-key")
    if not (lockfile and re.search(r"(?i)\b(?:integrity|checksum|resolved)\b", line)):
        if any(pattern.search(line) for pattern in TOKEN_PATTERNS):
            add("credential-token")
        assignment = SENSITIVE_ASSIGNMENT_RE.search(line)
        assigned_value = next(
            (value for value in assignment.groups() if value is not None), None
        ) if assignment else None
        if assigned_value is not None and not _placeholder_or_reference(assigned_value):
            add("credential-assignment")
    for match in URL_RE.finditer(line):
        try:
            parsed = urlsplit(match.group(0))
            if parsed.username is not None or parsed.password is not None:
                add("credential-url")
            if _private_host(parsed.hostname):
                add("private-host")
        except ValueError:
            continue
    for match in EMAIL_RE.finditer(line):
        domain = match.group(1).lower().rstrip(".")
        if (
            domain.endswith("users.noreply.github.com")
            or domain.endswith(".invalid")
            or domain in RESERVED_EMAIL_DOMAINS
        ):
            continue
        add("email-address")
    if POSIX_HOME_RE.search(line) or WINDOWS_HOME_RE.search(line):
        add("private-home-path")
    if PRIVATE_NAME_RE.search(line):
        add("private-host")
    for match in HOST_PORT_RE.finditer(line):
        if _private_host(match.group(1) or match.group(2)):
            add("private-host")
    for match in IP_RE.finditer(line):
        if _private_host(match.group(0)):
            add("private-host")
    return findings


def scan_text(location: str, text: str) -> set[Finding]:
    lockfile = PurePosixPath(location.split(":", 1)[-1]).name in LOCKFILE_NAMES
    findings: set[Finding] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        findings.update(_scan_line(location, line_number, line, lockfile=lockfile))
    return findings


def scan_snapshot(root: Path, *, files_only: bool = False) -> set[Finding]:
    findings: set[Finding] = set()
    for relative in publication_paths(root, files_only=files_only):
        path = root / relative
        try:
            if path.is_symlink():
                text = os.readlink(path)
            else:
                text = _decode_text(path.read_bytes())
        except OSError as exc:
            raise PrivacyCheckError(f"unable to read publication file: {relative.as_posix()}") from exc
        if text is not None:
            findings.update(scan_text(relative.as_posix(), text))
    return findings


def _history_commits(root: Path) -> list[str]:
    output = _run_git(root, "rev-list", "--reverse", "HEAD", text=True)
    assert isinstance(output, str)
    commits = [line.strip() for line in output.splitlines() if line.strip()]
    if not commits:
        raise PrivacyCheckError("repository has no reachable commits")
    return commits


def scan_history(root: Path) -> set[Finding]:
    if _repository_root(root) is None:
        raise PrivacyCheckError("--history requires --root to be a Git repository root")
    findings: set[Finding] = set()
    for commit in _history_commits(root):
        short = commit[:12]
        metadata = _run_git(
            root,
            "show",
            "-s",
            "--format=%an%n%ae%n%cn%n%ce%n%B",
            commit,
            text=True,
        )
        assert isinstance(metadata, str)
        findings.update(scan_text(f"commit={short}:<metadata>", metadata))
        tree = _run_git(root, "ls-tree", "-r", "-z", "--name-only", commit)
        assert isinstance(tree, bytes)
        for item in tree.split(b"\0"):
            if not item:
                continue
            try:
                raw_path = item.decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise PrivacyCheckError("history path is not valid UTF-8") from exc
            relative = _safe_git_path(raw_path)
            if relative is None:
                continue
            blob = _run_git(root, "show", f"{commit}:{raw_path}")
            assert isinstance(blob, bytes)
            text = _decode_text(blob)
            if text is not None:
                findings.update(scan_text(f"commit={short}:{relative.as_posix()}", text))
    return findings


def check(
    root: Path, *, history: bool = False, files_only: bool = False
) -> tuple[Finding, ...]:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise PrivacyCheckError("root must be an existing directory")
    if history and files_only:
        raise PrivacyCheckError("--history and --files-only cannot be combined")
    findings = scan_history(resolved) if history else scan_snapshot(resolved, files_only=files_only)
    return tuple(sorted(findings))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check publication files for high-confidence privacy hazards. "
        "This heuristic scan cannot guarantee that content is secret-free."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--history",
        action="store_true",
        help="scan all commits reachable from HEAD, including commit metadata",
    )
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="scan package files directly without probing or invoking Git",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        findings = check(args.root, history=args.history, files_only=args.files_only)
    except PrivacyCheckError as exc:
        print(f"privacy-check error: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.render())
    if findings:
        print(f"privacy-check failed: findings={len(findings)}", file=sys.stderr)
        return 1
    print("privacy-check passed: no high-confidence findings")
    print(
        "limitation: heuristic checks cannot guarantee that publication content is secret-free",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
