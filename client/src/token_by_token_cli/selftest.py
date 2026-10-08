from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Literal
from collections.abc import Callable

from .bundle import write_synthetic_bundle
from .contracts import episode_manifest
from .errors import ClientError
from .offline import run_synthetic_episode
from .verify import verify_bundle


@dataclass(frozen=True, slots=True)
class SelfTestReport:
    bundle: Path
    digest: str
    requests: int
    classification: Literal["synthetic_mock"]


def run_selftest(
    output_path: Path,
    *,
    episode: int,
    users: int,
    seed: int,
    offline: bool,
    stop_requested: Callable[[], bool],
) -> SelfTestReport:
    if not offline:
        raise ClientError("OFFLINE_REQUIRED", "--offline is required", 2)
    output_path = Path(output_path)
    if not output_path.name.endswith(".tbt.zip") or not output_path.parent.is_dir():
        raise ClientError("BUNDLE_PATH", "output must be a .tbt.zip file in an existing directory")
    if output_path.exists():
        raise ClientError("OUTPUT_EXISTS", f"refusing to overwrite {output_path}")
    manifest = episode_manifest(episode)
    if users not in manifest["load_levels"]:
        allowed = ", ".join(str(value) for value in manifest["load_levels"])
        raise ClientError("INVALID_USERS", f"Episode {episode:02d} allows synthetic loads: {allowed}")
    if seed < 0 or seed > 2_147_483_647:
        raise ClientError("INVALID_SEED", "seed must be between 0 and 2147483647")

    events = list(run_synthetic_episode(manifest, users=users, seed=seed, stop_requested=stop_requested))
    with tempfile.TemporaryDirectory(prefix=".token-by-token-", dir=output_path.parent) as temporary:
        temporary_bundle = Path(temporary) / "bundle.tbt.zip"
        write_synthetic_bundle(events, temporary_bundle)
        report = verify_bundle(temporary_bundle)
        try:
            os.link(temporary_bundle, output_path)
        except FileExistsError as error:
            raise ClientError("OUTPUT_EXISTS", f"refusing to overwrite {output_path}") from error
        except OSError as error:
            output_path.unlink(missing_ok=True)
            raise ClientError("OUTPUT_WRITE_FAILED", "could not atomically publish the verified bundle") from error
    return SelfTestReport(
        bundle=output_path,
        digest=report.digest,
        requests=sum(event.kind == "request" for event in events),
        classification="synthetic_mock",
    )
