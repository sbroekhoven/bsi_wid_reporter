"""Orchestrates one run: fetch, process, store, report, notify."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import storage
from .api_client import FetchError, PoliteClient, fetch_wid_record
from .cli import parse_args
from .config_loader import Config, ConfigError, load_config
from .matcher import find_matches, passes_filter
from .parser import Wid, parse_record
from .report import RunSummary, cleanup_reports, write_failure_report, write_report
from .rss import FeedItem, fetch_feed, filter_window
from .teams import post_failure_to_teams, post_to_teams

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    fetched: list[Wid] = field(default_factory=list)
    fresh: list[Wid] = field(default_factory=list)
    already_seen: int = 0
    failed: int = 0


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)


def fetch_and_classify(client: PoliteClient, con, config: Config, items: list[FeedItem]) -> FetchResult:
    """Fetch details for each feed item, tag matches and split off already seen revisions."""
    result = FetchResult()
    for index, item in enumerate(items, start=1):
        log.debug("Fetching %s (%d/%d)", item.wid_id, index, len(items))
        try:
            uuid, record = fetch_wid_record(client, config.api_base_url, item.wid_id)
            wid = parse_record(record, uuid, status=item.status)
        except FetchError as exc:
            log.error("Skipping %s: %s", item.wid_id, exc)
            result.failed += 1
            continue
        wid.match_tags = find_matches(wid, config.match_lists, config.match_fields)
        result.fetched.append(wid)
        if storage.is_already_seen(con, wid):
            log.debug("%s revision %s already reported", wid.wid_id, wid.latest_revision)
            result.already_seen += 1
        else:
            result.fresh.append(wid)
    return result


def run_cleanup(config: Config, args) -> int:
    now = datetime.now(timezone.utc)
    if args.cleanup:
        days = args.older_than if args.older_than is not None else config.db_retention_days
        con = storage.connect(config.db_path)
        storage.cleanup_db(con, days, now)
        con.close()
    if args.cleanup_reports:
        cleanup_reports(config.output_dir, config.report_retention_days, now.astimezone().date())
    return 0


def teams_wanted(config: Config, args) -> bool:
    return config.teams.enabled and not args.no_teams and not args.dry_run


def report_feed_failure(config: Config, args, error: str, generated_at: datetime,
                        window_start: datetime) -> int:
    """Write a failure report and notify Teams so the run can be repeated."""
    log.error("Could not load RSS feed: %s", error)
    path = write_failure_report(config.output_dir, generated_at, error, window_start, args.dry_run)
    if teams_wanted(config, args):
        post_failure_to_teams(generated_at, error, window_start, config.teams, path.name,
                              timeout=config.http.timeout_seconds)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    load_dotenv(args.config_dir.resolve().parent / ".env")
    try:
        config = load_config(args.config_dir)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    if args.cleanup or args.cleanup_reports:
        return run_cleanup(config, args)

    now = datetime.now(timezone.utc)
    generated_at = now.astimezone()
    lookback = args.lookback if args.lookback is not None else config.lookback_hours
    window_start = (now - timedelta(hours=lookback)).astimezone()

    with PoliteClient(config.http) as client:
        try:
            feed_items = fetch_feed(client, config.feed_url)
        except (FetchError, ValueError) as exc:
            return report_feed_failure(config, args, str(exc), generated_at, window_start)
        window_items = filter_window(feed_items, now, lookback)
        log.info("%d WIDs published in the last %g hours", len(window_items), lookback)
        con = storage.connect(config.db_path, read_only=args.dry_run)
        result = fetch_and_classify(client, con, config, window_items)

    reported = [w for w in result.fresh
                if passes_filter(w, config.risk_levels, config.match_overrides_risk_filter)]
    if not args.dry_run:
        storage.save_wids(con, result.fetched, now)
    con.close()

    summary = RunSummary(
        generated_at=generated_at,
        window_start=window_start,
        window_end=generated_at,
        in_window=len(window_items),
        already_seen=result.already_seen,
        failed=result.failed,
        filtered_out=len(result.fresh) - len(reported),
        dry_run=args.dry_run,
    )
    path = write_report(config.output_dir, summary, reported)

    if teams_wanted(config, args):
        post_to_teams(summary, reported, config.teams, path.name,
                      timeout=config.http.timeout_seconds)
    return 0
