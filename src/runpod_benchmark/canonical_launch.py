"""Fail-closed dashboard bridge to the canonical Episode 1 production command.

The browser never supplies a filesystem path or executable.  An operator selects one
immutable JSON bundle when starting the loopback server; every UI action is translated
to the repository-owned ``execute_episode1.py`` command with a fixed argument set.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .episode1_execution import spend_approval_phrase


SCHEMA_VERSION = "inference-lab.canonical-launch.v1"
REQUIRED_INPUTS = (
    "build_manifest",
    "prompt_evidence",
    "build_attestation",
    "material",
    "plan",
    "authorization_receipt",
    "authorization_source",
    "unique_name",
    "private_evidence_directory",
)


class CanonicalLaunchError(ValueError):
    """The fixed launch configuration or an invocation was rejected."""


def _relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalLaunchError(f"{label} must be a non-empty repository-relative path")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise CanonicalLaunchError(f"{label} must stay within the repository")
    return value


def _load_object(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CanonicalLaunchError(f"{label} is unreadable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise CanonicalLaunchError(f"{label} must contain a JSON object")
    return value


@dataclass(frozen=True)
class CanonicalBundle:
    episode: int
    inputs: Mapping[str, str]
    plan_sha256: str
    maximum_spend_usd: str
    approval_phrase: str

    @classmethod
    def load(cls, bundle_path: pathlib.Path, repository_root: pathlib.Path) -> "CanonicalBundle":
        raw = _load_object(bundle_path, "canonical launch bundle")
        if raw.get("schema_version") != SCHEMA_VERSION or raw.get("episode") != 1:
            raise CanonicalLaunchError("only the canonical Episode 1 launch schema is supported")
        inputs = raw.get("inputs")
        if not isinstance(inputs, dict) or set(inputs) != set(REQUIRED_INPUTS):
            raise CanonicalLaunchError("canonical launch bundle inputs do not match the fixed contract")
        checked: dict[str, str] = {}
        for key in REQUIRED_INPUTS:
            if key == "unique_name":
                value = inputs[key]
                if not isinstance(value, str) or not value.strip() or len(value) > 128:
                    raise CanonicalLaunchError("unique_name must be a non-empty string of at most 128 characters")
                checked[key] = value
            else:
                checked[key] = _relative_path(inputs[key], key)

        plan_path = (repository_root / checked["plan"]).resolve()
        root = repository_root.resolve()
        if root not in plan_path.parents:
            raise CanonicalLaunchError("plan must stay within the repository")
        plan = _load_object(plan_path, "execution plan")
        digest = plan.get("plan_sha256")
        maximum = plan.get("budget", {}).get("maximum_spend_usd") if isinstance(plan.get("budget"), dict) else None
        if not isinstance(digest, str) or len(digest) != 64 or not isinstance(maximum, (str, int, float)):
            raise CanonicalLaunchError("execution plan is missing its digest or maximum spend")
        try:
            phrase = spend_approval_phrase(plan)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalLaunchError("execution plan cannot produce an exact approval phrase") from exc
        return cls(1, checked, digest, str(maximum), phrase)

    def command(self, repository_root: pathlib.Path, mode: str) -> list[str]:
        if mode not in {"preflight", "run"}:
            raise CanonicalLaunchError("mode must be preflight or run")
        command = [
            sys.executable,
            str(repository_root / "scripts" / "execute_episode1.py"),
            mode,
            "--repository-root", str(repository_root),
        ]
        flags = {
            "build_manifest": "--build-manifest",
            "prompt_evidence": "--prompt-evidence",
            "build_attestation": "--build-attestation",
            "material": "--material",
            "plan": "--plan",
            "authorization_receipt": "--authorization-receipt",
            "authorization_source": "--authorization-source",
            "unique_name": "--unique-name",
            "private_evidence_directory": "--private-evidence-directory",
        }
        for key, flag in flags.items():
            command.extend((flag, self.inputs[key]))
        return command


Executor = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _execute(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, check=False,
    )


class CanonicalLaunchController:
    """Serializes preflight/run and exposes only sanitized state to the browser."""

    def __init__(
        self,
        bundle_path: pathlib.Path | None,
        repository_root: pathlib.Path,
        *,
        launch_enabled: bool = False,
        executor: Executor = _execute,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.launch_enabled = launch_enabled
        self.executor = executor
        self.bundle = CanonicalBundle.load(bundle_path, self.repository_root) if bundle_path else None
        self.lock = threading.Lock()
        self.phase = "not-configured" if self.bundle is None else "ready-for-preflight"
        self.last_result: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        with self.lock:
            result: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "configured": self.bundle is not None,
                "launch_enabled": self.launch_enabled,
                "phase": self.phase,
                "last_result": self.last_result,
                "supported_episodes": [1],
            }
            if self.bundle:
                result.update({
                    "episode": 1,
                    "plan_sha256": self.bundle.plan_sha256,
                    "maximum_spend_usd": self.bundle.maximum_spend_usd,
                    "approval_phrase": self.bundle.approval_phrase,
                })
            return result

    def _invoke(self, mode: str) -> dict[str, Any]:
        if self.bundle is None:
            raise CanonicalLaunchError("no canonical launch bundle was configured at server start")
        completed = self.executor(self.bundle.command(self.repository_root, mode))
        if completed.returncode != 0:
            # execute_episode1 deliberately emits only a typed rejection and no secret detail.
            reason = (completed.stderr or "canonical command rejected").strip()[:512]
            raise CanonicalLaunchError(reason)
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CanonicalLaunchError("canonical command returned invalid output") from exc
        if not isinstance(result, dict) or result.get("plan_sha256") != self.bundle.plan_sha256:
            raise CanonicalLaunchError("canonical command result is not bound to the configured plan")
        return result

    def preflight(self) -> dict[str, Any]:
        if self.bundle is None:
            raise CanonicalLaunchError("no canonical launch bundle was configured at server start")
        with self.lock:
            if self.phase in {"preflighting", "running"}:
                raise CanonicalLaunchError("a canonical operation is already active")
            self.phase = "preflighting"
        try:
            result = self._invoke("preflight")
        except Exception:
            with self.lock:
                self.phase = "preflight-rejected"
            raise
        with self.lock:
            self.phase = "preflight-passed"
            self.last_result = result
        return result

    def launch(self, approval_phrase: object) -> dict[str, Any]:
        if self.bundle is None:
            raise CanonicalLaunchError("no canonical launch bundle was configured at server start")
        if not self.launch_enabled:
            raise CanonicalLaunchError("canonical launch is disabled; restart with --enable-canonical-launch")
        if not isinstance(approval_phrase, str) or approval_phrase != self.bundle.approval_phrase:
            raise CanonicalLaunchError("the exact digest-bound spend approval phrase is required")
        with self.lock:
            if self.phase in {"preflighting", "running"}:
                raise CanonicalLaunchError("a canonical operation is already active")
            self.phase = "running"
            self.last_result = None
        threading.Thread(target=self._run_background, daemon=True).start()
        return {"accepted": True, "episode": 1, "plan_sha256": self.bundle.plan_sha256}

    def _run_background(self) -> None:
        try:
            result = self._invoke("run")
        except Exception as exc:
            with self.lock:
                self.phase = "run-rejected"
                self.last_result = {"error": str(exc)[:512]}
            return
        with self.lock:
            self.phase = (
                "complete"
                if result.get("status") == "complete" and result.get("deletion_verified") is True
                else "run-failed"
            )
            self.last_result = result
