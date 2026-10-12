"""Command line argument definitions."""

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bafin-wid-reporter",
        description="Daily monitor for the BSI CERT-Bund WID security advisory feed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and process, but do not write to the DB or post to Teams. "
        "The report gets a -dryrun suffix.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove WIDs not seen for --older-than days from the DB and exit.",
    )
    parser.add_argument(
        "--older-than",
        type=int,
        metavar="DAYS",
        help="Age threshold for --cleanup (default: retention.db_days from config).",
    )
    parser.add_argument(
        "--cleanup-reports",
        action="store_true",
        help="Delete HTML reports older than retention.report_days and exit.",
    )
    parser.add_argument("--no-teams", action="store_true", help="Skip the Teams post for this run.")
    parser.add_argument(
        "--lookback",
        type=float,
        metavar="HOURS",
        help="Override the lookback window (default: lookback_hours from config).",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("config"),
        metavar="PATH",
        help="Config folder (default: config/).",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)
