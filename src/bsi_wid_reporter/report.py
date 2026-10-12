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

STYLESHEET = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --text: #1d2330; --muted: #5b6475; --border: #dde1e8;
  --kritisch: #b42318; --hoch: #c4500a; --mittel: #a87900; --niedrig: #3b6e3b;
  --match-bg: #fff4c2; --match-text: #5c4300; --error-bg: #fdecea;
  --new-bg: #dcecff; --new-text: #0b4a8f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c; --card: #1d2128; --text: #e4e7ec; --muted: #9aa3b2; --border: #313744;
    --kritisch: #f97066; --hoch: #fb9a4b; --mittel: #f5c542; --niedrig: #8bc48b;
    --match-bg: #4a3d0a; --match-text: #ffe58a; --error-bg: #4a1d1a;
    --new-bg: #13345a; --new-text: #9fcbff;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 24px 16px 48px; max-width: 1000px;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--text);
}
h1 { font-size: 1.6rem; margin: 0 0 16px; }
h2 { font-size: 1.2rem; margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 2px solid var(--border); }
h3 { font-size: 1.05rem; margin: 0 0 10px; }
code { font: 0.9em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.stats { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin: 0 0 14px; }
.stat {
  background: var(--card); border: 1px solid var(--border); border-top: 4px solid var(--muted);
  border-radius: 8px; padding: 10px 12px; text-align: center;
}
.stat .num { display: block; font-size: 1.8rem; font-weight: 700; line-height: 1.2; }
.stat .label { color: var(--muted); font-size: 0.85rem; }
.stat.risk-kritisch { border-top-color: var(--kritisch); }
.stat.risk-kritisch .num { color: var(--kritisch); }
.stat.risk-hoch { border-top-color: var(--hoch); }
.stat.risk-hoch .num { color: var(--hoch); }
.stat.match-stat { border-top-color: var(--match-text); background: var(--match-bg); }
.summary {
  list-style: none; margin: 0; padding: 12px 16px; background: var(--card);
  border: 1px solid var(--border); border-radius: 8px;
}
.summary li { padding: 2px 0; }
.wid {
  background: var(--card); border: 1px solid var(--border); border-left: 5px solid var(--muted);
  border-radius: 8px; padding: 14px 18px; margin: 0 0 14px;
}
.wid.risk-kritisch { border-left-color: var(--kritisch); }
.wid.risk-hoch { border-left-color: var(--hoch); }
.wid.risk-mittel { border-left-color: var(--mittel); }
.wid.risk-niedrig { border-left-color: var(--niedrig); }
.badge {
  display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.8rem;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;
  border: 1px solid currentColor; vertical-align: middle;
}
.badge.risk-kritisch { color: var(--kritisch); }
.badge.risk-hoch { color: var(--hoch); }
.badge.risk-mittel { color: var(--mittel); }
.badge.risk-niedrig { color: var(--niedrig); }
.match {
  display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.85rem;
  background: var(--match-bg); color: var(--match-text); font-weight: 600;
}
.status-new {
  display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.85rem;
  background: var(--new-bg); color: var(--new-text); font-weight: 600;
}
dl { display: grid; grid-template-columns: 11rem 1fr; gap: 4px 16px; margin: 0; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
.empty { color: var(--muted); font-style: italic; }
.error { background: var(--error-bg); border-radius: 8px; padding: 12px 16px; }
@media (max-width: 600px) {
  .stats { grid-template-columns: repeat(3, 1fr); }
  dl { grid-template-columns: 1fr; }
  dt { font-weight: 600; margin-top: 6px; }
}
"""


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
    from_db: bool = False  # --report: built from the database, not from a feed fetch


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
        "kritisch": sum(1 for w in wids if w.risk.upper() == "KRITISCH"),
        "hoch": sum(1 for w in wids if w.risk.upper() == "HOCH"),
    }


def render_stats(wids: list[Wid]) -> str:
    c = counts(wids)
    tiles = [
        ("Advisories", c["total"], ""),
        ("New", c["new"], ""),
        ("Updated", c["updated"], ""),
        ("Critical", c["kritisch"], "risk-kritisch"),
        ("High", c["hoch"], "risk-hoch"),
        ("Match hits", c["matches"], "match-stat"),
    ]
    items = "\n".join(
        f'  <div class="stat {css}"><span class="num">{value}</span>'
        f'<span class="label">{escape(label)}</span></div>'
        for label, value, css in tiles
    )
    return f'<div class="stats">\n{items}\n</div>'


def render_value(label: str, value: str) -> str:
    if label == "Status" and value == STATUS_LABELS["new"]:
        return f'<span class="status-new">{escape(value)}</span>'
    return escape(value)


def render_entry(wid: Wid) -> str:
    tags = match_tag_text(wid)
    risk_class = risk_css_class(wid.risk)
    heading = (f'<span class="badge {risk_class}">{escape(wid.risk or "unknown")}</span> '
               + escape(wid.title)
               + (f' <span class="match">{escape(tags)}</span>' if tags else ""))
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
    body = "\n".join(f"  <dt>{escape(label)}</dt><dd>{render_value(label, value)}</dd>"
                     for label, value in rows)
    return f'<article class="wid {risk_class}">\n<h3>{heading}</h3>\n<dl>\n{body}\n</dl>\n</article>'


def render_section(title: str, wids: list[Wid]) -> str:
    if not wids:
        return ""
    entries = "\n".join(render_entry(w) for w in sorted(wids, key=sort_key))
    return f"<h2>{escape(title)} ({len(wids)})</h2>\n{entries}"


def render_summary(summary: RunSummary, wids: list[Wid]) -> str:
    c = counts(wids)
    fmt = "%Y-%m-%d %H:%M %Z"
    window = f"Window: {summary.window_start.strftime(fmt)} to {summary.window_end.strftime(fmt)}"
    reported = f"Reported: {c['total']} (new: {c['new']}, updated: {c['updated']}, match hits: {c['matches']})"
    below = f"Below risk threshold: {summary.filtered_out}"
    if summary.from_db:
        items = [window, f"WIDs new or changed in the database in window: {summary.in_window}",
                 reported, below]
    else:
        items = [
            window,
            f"RSS items in window: {summary.in_window}",
            reported,
            below,
            f"Already reported in an earlier run: {summary.already_seen}",
            f"Failed to fetch: {summary.failed}",
        ]
    if summary.dry_run:
        items.append("Dry run: database not updated, Teams not notified")
    return '<ul class="summary">\n' + "\n".join(f"  <li>{escape(i)}</li>" for i in items) + "\n</ul>"


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
        content = '<p class="empty">No advisories qualified for this report.</p>'
    return html_page(title, f"{render_stats(wids)}\n{render_summary(summary, wids)}\n{content}")


def render_failure_report(generated_at: datetime, error: str, window_start: datetime) -> str:
    title = f"{report_title(generated_at)}: run failed"
    rerun_from = window_start.strftime("%Y-%m-%d %H:%M %Z")
    body = (
        f'<div class="error">\n<p>Error: {escape(error)}</p>\n'
        f"<p>Nothing was processed. Rerun with <code>uv run run.py --lookback HOURS</code>, "
        f"where HOURS reaches back to at least {escape(rerun_from)}.</p>\n</div>"
    )
    return html_page(title, body)


def html_page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{escape(title)}</title>\n<style>{STYLESHEET}</style>\n</head>\n<body>\n"
        f"<h1>{escape(title)}</h1>\n{body}\n</body>\n</html>\n"
    )


def risk_css_class(risk: str) -> str:
    level = risk.lower()
    return f"risk-{level}" if level.upper() in RISK_ORDER else "risk-unknown"


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
