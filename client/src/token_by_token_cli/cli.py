from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import sys

from . import __version__
from .errors import ClientError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-by-token", description="Explore and verify Token by Token episodes.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("episodes", help="List the public episode catalog")

    episode = commands.add_parser("episode", help="Describe or self-test an episode")
    episode.add_argument("number", type=int, choices=range(17), metavar="EPISODE")
    episode_commands = episode.add_subparsers(dest="episode_command", required=True)
    describe = episode_commands.add_parser("describe", help="Describe the public episode contract")
    describe.add_argument("--format", choices=("human", "json"), default="human")
    selftest = episode_commands.add_parser("selftest", help="Run a synthetic, offline client self-test")
    selftest.add_argument("--offline", action="store_true", required=True)
    selftest.add_argument("--users", type=int, default=4)
    selftest.add_argument("--seed", type=int, default=42)
    selftest.add_argument("--output", required=True)
    selftest.add_argument("--format", choices=("human", "json"), default="human")

    evidence = commands.add_parser("evidence", help="Verify a synthetic evidence bundle")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    verify = evidence_commands.add_parser("verify", help="Verify integrity and classification")
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
        raise ClientError("NOT_IMPLEMENTED", f"{args.command} is not implemented yet")
    except ClientError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return error.exit_status


def entrypoint() -> None:
    raise SystemExit(main())
