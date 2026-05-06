from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from kronos_trading_bot.pipeline import run_fixture_cycle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kronos-paper-trade",
        description="Paper-only Kronos fixture dry-run CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_fixture = subparsers.add_parser(
        "run-fixture",
        help="Run a paper-only fixture dry run and write a local report.",
    )
    run_fixture.add_argument("--symbol", required=True)
    run_fixture.add_argument("--fixture", required=True, type=Path)
    run_fixture.add_argument("--report-dir", default=Path("reports"), type=Path)
    run_fixture.set_defaults(mode="paper")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run-fixture":
        result = run_fixture_cycle(
            symbol=args.symbol,
            fixture_path=args.fixture,
            report_dir=args.report_dir,
        )
        print(
            f"symbol={result.symbol} status={result.status} "
            f"live_orders_attempted={result.live_orders_attempted} "
            f"report_path={result.report_path}"
        )
        return 0
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
