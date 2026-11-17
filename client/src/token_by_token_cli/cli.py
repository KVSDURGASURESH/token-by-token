from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys
import tempfile

from . import __version__
from .errors import ClientError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token-by-token",
        description="Explore and verify Token by Token episodes.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("episodes", help="List the public episode catalog", allow_abbrev=False)

    capabilities = commands.add_parser(
        "capabilities", help="Report the bounded public execution surface", allow_abbrev=False
    )
    capabilities.add_argument("--episode", type=int, choices=range(17), required=True)
    capabilities.add_argument("--worker", help="Reviewed worker with Episode 02 capability proof")
    capabilities.add_argument("--format", choices=("human", "json"), default="human")

    doctor = commands.add_parser(
        "doctor", help="Check the client installation without provider access", allow_abbrev=False
    )
    doctor.add_argument("--offline", action="store_true", required=True)
    doctor.add_argument("--format", choices=("human", "json"), default="human")

    episode = commands.add_parser("episode", help="Describe or self-test an episode", allow_abbrev=False)
    episode.add_argument("number", type=int, choices=range(17), metavar="EPISODE")
    episode_commands = episode.add_subparsers(dest="episode_command", required=True)
    describe = episode_commands.add_parser(
        "describe", help="Describe the public episode contract", allow_abbrev=False
    )
    describe.add_argument("--format", choices=("human", "json"), default="human")
    selftest = episode_commands.add_parser(
        "selftest", help="Run a synthetic, offline client self-test", allow_abbrev=False
    )
    selftest.add_argument("--offline", action="store_true", required=True)
    selftest.add_argument("--users", type=int)
    selftest.add_argument("--seed", type=int, default=42)
    selftest.add_argument("--output", required=True)
    selftest.add_argument("--format", choices=("human", "json"), default="human")
    local_run = episode_commands.add_parser(
        "run-local", help="Run the constrained local AgentBench loopback diagnostic", allow_abbrev=False
    )
    local_run.add_argument(
        "--worker",
        required=True,
        metavar="AGENTBENCH_WORKER",
        help="Path to a reviewed agentbench-worker executable",
    )
    local_run.add_argument(
        "--output",
        required=True,
        metavar="NEW_FILE.tbt.json",
        help="New file for the validated synthetic diagnostic result",
    )
    local_run.add_argument("--format", choices=("human", "json"), default="human")

    select = episode_commands.add_parser("select", help="Write a bounded Episode 02 selection request", allow_abbrev=False)
    for option in ("worker", "mixture", "model", "gpu", "output"):
        select.add_argument(f"--{option}", required=True)
    select.add_argument("--format", choices=("human", "json"), default="human")

    evidence = commands.add_parser(
        "evidence", help="Verify a synthetic evidence bundle", allow_abbrev=False
    )
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    verify = evidence_commands.add_parser(
        "verify", help="Verify integrity and classification", allow_abbrev=False
    )
    verify.add_argument("path")
    verify.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "episodes":
            from .contracts import load_resource_json

            catalog = load_resource_json("episodes/catalog.v1.json")
            for item in catalog["episodes"]:
                print(f"Episode {item['episode']:02d} · {item['title']} · {item['status']}")
            return 0
        if args.command == "capabilities":
            from .contracts import public_capabilities

            if args.worker:
                from pathlib import Path
                from .selection import read_episode2_capability
                if args.episode != 2:
                    raise ClientError("UNAVAILABLE_EPISODE", "worker capability selection supports Episode 02 only")
                document = read_episode2_capability(Path(args.worker))
            else:
                document = public_capabilities(args.episode)
            if args.format == "json":
                print(json.dumps(document, sort_keys=True, separators=(",", ":")))
            elif args.worker:
                print(f"Episode 02 · capability {document['status']}")
                print("Selection grants no permission to create resources or execute a benchmark.")
            else:
                print(f"Episode {args.episode:02d} · real execution unavailable")
                print(document["reason"])
                print("No real model, GPU, endpoint, or execution profile is accepted by this client.")
            return 0
        if args.command == "episode" and args.episode_command == "select":
            from pathlib import Path
            from .selection import create_selection
            if args.number != 2:
                raise ClientError("UNAVAILABLE_EPISODE", "selection supports Episode 02 only")
            report = create_selection(Path(args.worker), Path(args.output), mixture=args.mixture, model=args.model, gpu=args.gpu)
            if args.format == "json":
                print(json.dumps(report, sort_keys=True, separators=(",", ":")))
            else:
                print(f"Episode 02 selection written: {args.output}")
                print("Execution requires a separate private operator action and current paid approval.")
            return 0
        if args.command == "doctor":
            from pathlib import Path
            from .selftest import run_selftest

            with tempfile.TemporaryDirectory(prefix="token-by-token-doctor-") as temporary:
                report = run_selftest(
                    Path(temporary) / "doctor.tbt.zip",
                    episode=0,
                    users=1,
                    seed=42,
                    offline=args.offline,
                    stop_requested=lambda: False,
                )
                document = {
                    "status": "pass",
                    "network": "forbidden",
                    "classification": report.classification,
                    "meaning": "client_installation_diagnostic_only",
                    "requests": report.requests,
                }
            if args.format == "json":
                print(json.dumps(document, sort_keys=True, separators=(",", ":")))
            else:
                print("PASS · offline client installation diagnostic")
                print("Network was forbidden; the temporary synthetic bundle verified and was removed.")
                print("This is not benchmark evidence from the private harness.")
            return 0
        if args.command == "episode" and args.episode_command == "describe":
            from .contracts import episode_manifest

            document = episode_manifest(args.number)
            if args.format == "json":
                print(json.dumps(document, sort_keys=True, separators=(",", ":")))
            else:
                levels = ", ".join(str(value) for value in document["load_levels"])
                speculation = "study variable" if document["speculative_decoding"] == "study_variable" else "excluded"
                print(f"Episode {document['episode']:02d} · {document['title']}")
                print(document["question"])
                print(document["summary"])
                print(f"Evidence: {document['evidence']}")
                print(f"Synthetic self-test loads: {levels}")
                print(f"Speculative decoding: {speculation}")
                print("The offline self-test validates client plumbing only; it is not benchmark evidence.")
            return 0
        if args.command == "episode" and args.episode_command == "selftest":
            from pathlib import Path
            from .contracts import episode_manifest
            from .selftest import run_selftest

            manifest = episode_manifest(args.number)
            users = args.users if args.users is not None else manifest["load_levels"][0]
            report = run_selftest(Path(args.output), episode=args.number, users=users, seed=args.seed, offline=args.offline, stop_requested=lambda: False)
            document = {
                "bundle": str(report.bundle),
                "classification": report.classification,
                "digest": report.digest,
                "digest_scope": "inventory.json",
                "episode": args.number,
                "requests": report.requests,
                "seed": args.seed,
                "users": users,
            }
            if args.format == "json":
                print(json.dumps(document, sort_keys=True, separators=(",", ":")))
            else:
                print(f"PASS · synthetic offline self-test · Episode {args.number:02d} · {users} users")
                print(f"Bundle: {report.bundle}")
                print(f"Inventory digest: sha256:{report.digest}")
                print("Digest scope: canonical inventory.json; this is not the archive-file checksum.")
                print("This validates client plumbing only; it is not benchmark evidence.")
            return 0
        if args.command == "episode" and args.episode_command == "run-local":
            from pathlib import Path
            from .local_worker import run_local

            report = run_local(Path(args.worker), Path(args.output), episode=args.number)
            if args.format == "json":
                print(json.dumps(report, sort_keys=True, separators=(",", ":")))
            else:
                print(f"PASS · AgentBench loopback diagnostic · Episode {args.number:02d}")
                print(f"Output: {args.output}")
                print(f"Valid streamed requests: {report['result']['valid_requests']}")
                print("Classification: synthetic_mock; this is not a GPU benchmark result.")
            return 0
        if args.command == "evidence" and args.evidence_command == "verify":
            from pathlib import Path
            from .verify import verify_bundle

            report = verify_bundle(Path(args.path))
            if args.format == "json":
                print(json.dumps({"valid": True, "classification": report.classification, "digest": report.digest, "digest_scope": "inventory.json", "files": report.files}, sort_keys=True, separators=(",", ":")))
            else:
                print(f"VALID · {report.classification} · inventory sha256:{report.digest}")
                print("Digest scope: canonical inventory.json; this is not the archive-file checksum.")
                for name in report.files:
                    print(name)
            return 0
        raise ClientError("NOT_IMPLEMENTED", f"{args.command} is not implemented yet")
    except ClientError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return error.exit_status


def entrypoint() -> None:
    raise SystemExit(main())
