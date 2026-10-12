"""Command line argument definitions."""

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bsi-wid-reporter",
        description="Monitor for the BSI CERT-Bund WID security advisory feed. Without --sync or "
        "--report, a run syncs and then reports the WIDs not reported before.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--sync",
        action="store_true",
        help="Fetch the lookback window from the feed into the DB only. No report; "
        "Teams is notified only if the feed cannot be loaded.",
    )
    mode.add_argument(
        "--report",
        action="store_true",
        help="Report WIDs new or changed in the DB within the lookback window. No feed fetch.",
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
