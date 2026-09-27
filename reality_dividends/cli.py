"""Command-line interface for dividend collection."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from .constants import CREATION_BLOCK, RPC_PROVIDERS, RPC_URL_ENV
from .output import write_csv, write_markdown
from .rpc import CollectionError, RpcCollector
from .state import ScanState, StateError


def nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Reality Finance dividend events on Arbitrum One."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--provider", choices=RPC_PROVIDERS, required=True)
        subparser.add_argument("--output-dir", type=Path, default=Path("output"))
        subparser.add_argument(
            "--output-type",
            choices=("csv", "markdown"),
            required=True,
            help="report format to write (scan state is always checkpointed)",
        )

    creation = subparsers.add_parser(
        "creation", help=f"scan from oracle creation block {CREATION_BLOCK}"
    )
    add_common(creation)

    block_range = subparsers.add_parser("range", help="scan an inclusive block range")
    add_common(block_range)
    block_range.add_argument("--from-block", type=nonnegative_int, required=True)
    block_range.add_argument("--to-block", type=nonnegative_int, required=True)
    return parser


def _paths(args: argparse.Namespace, start: int, end: int | None) -> dict[str, Path]:
    suffix = "creation" if args.mode == "creation" else f"{start}-{end}"
    return {
        "csv": args.output_dir / f"dividends-{args.provider}.csv",
        "markdown": args.output_dir / f"dividends-{args.provider}.md",
        "state": args.output_dir / f".{args.provider}-{suffix}-state.json",
    }


def run(args: argparse.Namespace) -> int:
    start = CREATION_BLOCK if args.mode == "creation" else args.from_block
    end = None if args.mode == "creation" else args.to_block
    if start < CREATION_BLOCK:
        raise CollectionError(
            f"--from-block must be greater than or equal to oracle creation block "
            f"{CREATION_BLOCK}"
        )
    if end is not None and start > end:
        raise CollectionError("--from-block must be less than or equal to --to-block")

    rpc_url_name = RPC_URL_ENV[args.provider]
    rpc_url = os.environ.get(rpc_url_name)
    if not rpc_url:
        raise CollectionError(f"{rpc_url_name} is required")

    paths = _paths(args, start, end)
    requested_end = end if end is not None else start
    state = ScanState(paths["state"], args.provider, start, requested_end)
    collector = RpcCollector(args.provider, rpc_url, state)

    collector.validate_chain()
    if end is None:
        end = collector.head_block()
        if end < start:
            raise CollectionError(
                f"provider head {end} precedes oracle creation block {start}"
            )
        state.data["requested_to"] = max(int(state.data["requested_to"]), end)
        state.save()

    try:
        collector.collect(start, end)
    finally:
        records = [
            record
            for record in state.records
            if start <= int(record["block_number"]) <= end
        ]
        if args.output_type == "csv":
            write_csv(paths["csv"], records)
        else:
            write_markdown(paths["markdown"], records)

    output_path = paths[args.output_type]
    print(f"wrote {len(records)} dividend events to {output_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (CollectionError, StateError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
