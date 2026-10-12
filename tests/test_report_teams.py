import json
from datetime import date, datetime, timezone

from bsi_wid_reporter.config_loader import TeamsSettings
from bsi_wid_reporter import teams
from bsi_wid_reporter.report import (RunSummary, cleanup_reports, render_report, write_failure_report,
                                       write_report)
from bsi_wid_reporter.teams import (MAX_PAYLOAD_BYTES, build_failure_payload, build_payload,
                                      payload_size, post_to_teams)

from conftest import make_wid

SUMMARY = RunSummary(
    generated_at=datetime(2026, 10, 12, 15, 0, 5, tzinfo=timezone.utc),
    window_start=datetime(2026, 10, 11, 15, tzinfo=timezone.utc),
    window_end=datetime(2026, 10, 12, 15, tzinfo=timezone.utc),
    in_window=3, already_seen=0, failed=0, filtered_out=1,
)


def card_content(payload):
    return payload["attachments"][0]["content"]


def test_report_escapes_and_tags():
    wids = [
        make_wid("WID-A", title="<script>x</script>", match_tags=[("virtualization", "vmware")]),
        make_wid("WID-B", title="Plain"),
    ]
    html = render_report(SUMMARY, wids)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "[MATCH: virtualization / vmware]" in html
    assert html.index("Match list hits") < html.index("Other advisories")
    assert "<dd>Yes</dd>" in html


def test_report_stats_tiles():
    wids = [
        make_wid("WID-A", risk="kritisch", status="new", match_tags=[("g", "k")]),
        make_wid("WID-B", risk="hoch", status="updated"),
        make_wid("WID-C", risk="hoch", status="updated"),
        make_wid("WID-D", risk="mittel", status="new", match_tags=[("g", "k")]),
    ]
    html = render_report(SUMMARY, wids)
    expected = {"Advisories": 4, "New": 2, "Updated": 2, "Critical": 1, "High": 2, "Match hits": 2}
    for label, value in expected.items():
        assert f'<span class="num">{value}</span><span class="label">{label}</span>' in html
    assert html.index('class="stats"') < html.index('class="summary"')


def test_empty_report_says_so(tmp_path):
    path = write_report(tmp_path, SUMMARY, [])
    assert path.name == "report-2026-10-12-150005.html"
    assert "No advisories qualified" in path.read_text(encoding="utf-8")


def test_dry_run_filename(tmp_path):
    summary = RunSummary(**{**SUMMARY.__dict__, "dry_run": True})
    assert write_report(tmp_path, summary, []).name == "report-2026-10-12-150005-dryrun.html"


def test_cleanup_reports(tmp_path):
    old = ["report-2026-01-01.html", "report-2026-01-02-150000-dryrun.html",
           "report-2026-01-03-150000-failed.html", "report-2026-01-04-150000-dryrun-failed.html"]
    keep = ["notes.html", "report-2026-10-01-150000.html"]
    for name in old + keep:
        (tmp_path / name).write_text("x")
    removed = cleanup_reports(tmp_path, 90, date(2026, 10, 12))
    assert sorted(p.name for p in removed) == sorted(old)
    assert sorted(p.name for p in tmp_path.iterdir()) == keep


def test_card_is_full_width_and_truncates():
    wids = [make_wid(f"WID-{i}") for i in range(10)]
    payload = build_payload(SUMMARY, wids, TeamsSettings(max_items=3, report_link="https://x/reports/"), "r.html")
    content = card_content(payload)
    assert content["msteams"] == {"width": "Full"}
    table = next(b for b in content["body"] if b["type"] == "Table")
    assert len(table["rows"]) == 1 + 3
    assert any("7 more not shown" in b.get("text", "") for b in content["body"])
    assert content["actions"][0]["url"] == "https://x/reports/r.html"


def test_card_matches_only_and_size_limit():
    big = "x" * 2000
    wids = [make_wid(f"WID-{i}", title=big, match_tags=[("g", "k")]) for i in range(40)]
    wids.append(make_wid("WID-nomatch"))
    payload = build_payload(SUMMARY, wids, TeamsSettings(send_mode="matches_only", max_items=40), "r.html")
    assert payload_size(payload) <= MAX_PAYLOAD_BYTES
    assert "WID-nomatch" not in json.dumps(payload)
    assert "not shown" in json.dumps(payload)


def test_failure_report(tmp_path):
    path = write_failure_report(tmp_path, SUMMARY.generated_at, "GET <feed> failed", SUMMARY.window_start, False)
    assert path.name == "report-2026-10-12-150005-failed.html"
    html = path.read_text(encoding="utf-8")
    assert "run failed" in html
    assert "GET &lt;feed&gt; failed" in html
    assert "--lookback HOURS" in html


def test_failure_card():
    payload = build_failure_payload(SUMMARY.generated_at, "boom", SUMMARY.window_start, "https://x/r.html")
    content = card_content(payload)
    assert content["msteams"] == {"width": "Full"}
    assert any("Error: boom" in b.get("text", "") for b in content["body"])
    assert content["actions"][0]["url"] == "https://x/r.html"


def test_matches_only_without_matches_skips_post(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.invalid/hook")
    monkeypatch.setattr(teams.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("posted")))
    assert not post_to_teams(SUMMARY, [make_wid()], TeamsSettings(send_mode="matches_only"), "r.html")


def test_new_status_is_highlighted():
    html = render_report(SUMMARY, [make_wid("WID-A", status="new"), make_wid("WID-B", status="updated")])
    assert '<dd><span class="status-new">New</span></dd>' in html
    assert "<dd>Updated</dd>" in html
