"""Daily HTML report generation and report retention."""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from .parser import Wid

log = logging.getLogger(__name__)

RISK_ORDER = {"KRITISCH": 0, "HOCH": 1, "MITTEL": 2, "NIEDRIG": 3}
STATUS_LABELS = {"new": "New", "updated": "Updated", "unknown": "Unknown"}
REPORT_NAME_PATTERN = re.compile(r"^report-(\d{4}-\d{2}-\d{2})(-\d{6})?(-dryrun)?(-failed)?\.html$")
TITLE_TIME_FORMAT = "%Y-%m-%d %H:%M"


@dataclass
class RunSummary:
    generated_at: datetime  # local time of the run, used in title and filename
    window_start: datetime
    window_end: datetime
    in_window: int
    already_seen: int
    failed: int
    filtered_out: int
    dry_run: bool = False


def sort_key(wid: Wid) -> tuple:
    return (RISK_ORDER.get(wid.risk.upper(), 99), wid.wid_id)


def yes_no(value: bool | None) -> str:
    if value is None:
        return "Unknown"
    return "Yes" if value else "No"


def match_tag_text(wid: Wid) -> str:
    return " ".join(f"[MATCH: {group} / {keyword}]" for group, keyword in wid.match_tags)


def counts(wids: list[Wid]) -> dict[str, int]:
    return {
        "total": len(wids),
        "new": sum(1 for w in wids if w.status == "new"),
        "updated": sum(1 for w in wids if w.status == "updated"),
        "matches": sum(1 for w in wids if w.match_tags),
    }


def render_entry(wid: Wid) -> str:
    tags = match_tag_text(wid)
    heading = escape(wid.title) + (f" <strong>{escape(tags)}</strong>" if tags else "")
    rows = [
        ("WID", wid.wid_id),
        ("Status", STATUS_LABELS.get(wid.status, wid.status)),
        ("Risk", wid.risk),
        ("Remotely exploitable", yes_no(wid.remotely_exploitable)),
        ("CVEs", wid.cve_ids or "-"),
        ("Description", wid.description),
        ("Product description", wid.productdescription),
        ("Import status", wid.import_status),
        ("Damage", wid.damage),
        ("WID advisory list", yes_no(wid.wid_advisory_liste)),
        ("Match tags", wid.match_tags_text or "-"),
    ]
    body = "\n".join(f"  <dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in rows)
    return f"<h3>{heading}</h3>\n<dl>\n{body}\n</dl>"


def render_section(title: str, wids: list[Wid]) -> str:
    if not wids:
        return ""
    entries = "\n<hr>\n".join(render_entry(w) for w in sorted(wids, key=sort_key))
    return f"<h2>{escape(title)} ({len(wids)})</h2>\n{entries}"


def render_summary(summary: RunSummary, wids: list[Wid]) -> str:
    c = counts(wids)
    fmt = "%Y-%m-%d %H:%M %Z"
    items = [
        f"Window: {summary.window_start.strftime(fmt)} to {summary.window_end.strftime(fmt)}",
        f"RSS items in window: {summary.in_window}",
        f"Reported: {c['total']} (new: {c['new']}, updated: {c['updated']}, match hits: {c['matches']})",
        f"Below risk threshold: {summary.filtered_out}",
        f"Already reported in an earlier run: {summary.already_seen}",
        f"Failed to fetch: {summary.failed}",
    ]
    if summary.dry_run:
        items.append("Dry run: database not updated, Teams not notified")
    return "<ul>\n" + "\n".join(f"  <li>{escape(i)}</li>" for i in items) + "\n</ul>"


def render_report(summary: RunSummary, wids: list[Wid]) -> str:
    title = report_title(summary.generated_at)
    matched = [w for w in wids if w.match_tags]
    others = [w for w in wids if not w.match_tags]
    if wids:
        content = "\n".join(s for s in (
            render_section("Match list hits", matched),
            render_section("Other advisories", others),
        ) if s)
    else:
        content = "<p>No advisories qualified for this report.</p>"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{escape(title)}</title>\n</head>\n<body>\n"
        f"<h1>{escape(title)}</h1>\n{render_summary(summary, wids)}\n{content}\n"
        "</body>\n</html>\n"
    )


def render_failure_report(generated_at: datetime, error: str, window_start: datetime) -> str:
    title = f"{report_title(generated_at)}: run failed"
    rerun_from = window_start.strftime("%Y-%m-%d %H:%M %Z")
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{escape(title)}</title>\n</head>\n<body>\n"
        f"<h1>{escape(title)}</h1>\n"
        f"<p>Error: {escape(error)}</p>\n"
        f"<p>Nothing was processed. Rerun with <code>uv run run.py --lookback HOURS</code>, "
        f"where HOURS reaches back to at least {escape(rerun_from)}.</p>\n"
        "</body>\n</html>\n"
    )


def report_title(generated_at: datetime) -> str:
    return f"BSI WID report {generated_at.strftime(TITLE_TIME_FORMAT)}"


def report_filename(generated_at: datetime, dry_run: bool, failed: bool = False) -> str:
    suffix = ("-dryrun" if dry_run else "") + ("-failed" if failed else "")
    return f"report-{generated_at.strftime('%Y-%m-%d-%H%M%S')}{suffix}.html"


def write_html(output_dir: Path, filename: str, html: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(html, encoding="utf-8")
    log.info("Wrote report %s", path)
    return path


def write_report(output_dir: Path, summary: RunSummary, wids: list[Wid]) -> Path:
    filename = report_filename(summary.generated_at, summary.dry_run)
    return write_html(output_dir, filename, render_report(summary, wids))


def write_failure_report(output_dir: Path, generated_at: datetime, error: str,
                         window_start: datetime, dry_run: bool) -> Path:
    filename = report_filename(generated_at, dry_run, failed=True)
    return write_html(output_dir, filename, render_failure_report(generated_at, error, window_start))


def cleanup_reports(output_dir: Path, older_than_days: int, today: date) -> list[Path]:
    cutoff = today - timedelta(days=older_than_days)
    removed = []
    for path in sorted(output_dir.glob("report-*.html")):
        match = REPORT_NAME_PATTERN.match(path.name)
        if match and date.fromisoformat(match.group(1)) < cutoff:
            path.unlink()
            removed.append(path)
    log.info("Removed %d reports older than %s", len(removed), cutoff.isoformat())
    return removed
