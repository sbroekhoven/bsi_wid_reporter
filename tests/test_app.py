"""End-to-end run against a mocked HTTP transport."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from bafin_wid_reporter import api_client, app, teams

from conftest import FIXTURES

CONFIG_DIR = Path(__file__).parent.parent / "config"


FEED_DOWN = {"value": False}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if FEED_DOWN["value"]:
        return httpx.Response(404)
    if path.endswith("/securityAdvisory/rss"):
        return httpx.Response(200, content=(FIXTURES / "feed.xml").read_bytes())
    if "kurzinfo-uuid-by-name/WID-SEC-2026-2272" in path:
        return httpx.Response(200, text='"uuid-2272"')
    if path.endswith("/content/uuid-2272"):
        return httpx.Response(200, json=json.loads((FIXTURES / "record.json").read_text(encoding="utf-8")))
    return httpx.Response(404)


@pytest.fixture
def project(tmp_path, monkeypatch):
    shutil.copytree(CONFIG_DIR, tmp_path / "config")
    config_file = tmp_path / "config" / "config.yaml"
    config_file.write_text(config_file.read_text().replace("request_delay_seconds: 0.5", "request_delay_seconds: 0")
                           .replace("max_retries: 3", "max_retries: 0"))
    original_init = api_client.PoliteClient.__init__

    def init_with_mock(self, settings, transport=None):
        original_init(self, settings, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(api_client.PoliteClient, "__init__", init_with_mock)
    monkeypatch.setattr(app, "datetime", FrozenDatetime)
    monkeypatch.setitem(FEED_DOWN, "value", False)
    return tmp_path


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc).astimezone(tz)


# Filenames use the local time of the run, which differs between machines and CI
LOCAL_STAMP = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d-%H%M%S")


def run(project, *flags):
    return app.main(["--config-dir", str(project / "config"), *flags])


def latest_report(project) -> str:
    return sorted((project / "output").glob("report-*.html"))[-1].read_text(encoding="utf-8")


def test_full_run_then_dedupe(project, monkeypatch):
    assert run(project) == 0
    report = latest_report(project)
    assert "WID-SEC-2026-2272" in report
    assert "Failed to fetch: 1" in report  # WID-SEC-2026-3872 returns 404
    assert (project / "data" / "wids.duckdb").exists()

    monkeypatch.setattr(FrozenDatetime, "now", classmethod(
        lambda cls, tz=None: datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc).astimezone(tz)))
    assert run(project) == 0
    assert len(list((project / "output").iterdir())) == 2
    report = latest_report(project)
    assert "Already reported in an earlier run: 1" in report
    assert "No advisories qualified" in report


def test_dry_run_writes_nothing_but_report(project):
    assert run(project, "--dry-run") == 0
    assert not (project / "data").exists()
    assert [p.name for p in (project / "output").iterdir()] == [f"report-{LOCAL_STAMP}-dryrun.html"]


def test_cleanup_exits_without_fetching(project):
    assert run(project, "--cleanup", "--older-than", "1", "--cleanup-reports") == 0
    assert not (project / "output").exists() or not any((project / "output").iterdir())


def test_feed_failure_writes_report_and_notifies_teams(project, monkeypatch):
    config_file = project / "config" / "config.yaml"
    config_file.write_text(config_file.read_text().replace("enabled: false", "enabled: true"))
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.invalid/hook")
    monkeypatch.setitem(FEED_DOWN, "value", True)
    posted = []
    monkeypatch.setattr(teams.httpx, "post", lambda url, json, timeout: posted.append(json) or
                        httpx.Response(200, request=httpx.Request("POST", url)))

    assert run(project) == 1
    names = [p.name for p in (project / "output").iterdir()]
    assert names == [f"report-{LOCAL_STAMP}-failed.html"]
    assert "HTTP 404" in latest_report(project)
    assert len(posted) == 1
    assert "run failed" in json.dumps(posted[0])
    assert not (project / "data").exists()


def enable_teams(project, monkeypatch) -> list:
    config_file = project / "config" / "config.yaml"
    config_file.write_text(config_file.read_text().replace("enabled: false", "enabled: true"))
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.invalid/hook")
    posted = []
    monkeypatch.setattr(teams.httpx, "post", lambda url, json, timeout: posted.append(json) or
                        httpx.Response(200, request=httpx.Request("POST", url)))
    return posted


def test_sync_then_report_from_db(project, monkeypatch):
    posted = enable_teams(project, monkeypatch)
    assert run(project, "--sync") == 0
    assert (project / "data" / "wids.duckdb").exists()
    assert not (project / "output").exists()
    assert posted == []

    # A repeated report shows the same WIDs: the window decides, not earlier reports
    for _ in range(2):
        assert run(project, "--report") == 0
        report = latest_report(project)
        assert "WID-SEC-2026-2272" in report
        assert "WIDs new or changed in the database in window: 1" in report
        assert "Failed to fetch" not in report
    assert len(posted) == 2

    monkeypatch.setattr(FrozenDatetime, "now", classmethod(
        lambda cls, tz=None: datetime(2026, 10, 12, 17, 0, tzinfo=timezone.utc).astimezone(tz)))
    assert run(project, "--report", "--lookback", "1") == 0
    assert "No advisories qualified" in latest_report(project)


def test_report_recomputes_match_tags(project):
    assert run(project, "--sync") == 0
    matchlists = project / "config" / "matchlists.yaml"
    matchlists.write_text("match_lists:\n  python_stack:\n    - cpython\n")
    assert run(project, "--report") == 0
    assert "[MATCH: python_stack / cpython]" in latest_report(project)


def test_sync_dry_run_stores_nothing(project):
    assert run(project, "--sync", "--dry-run") == 0
    assert not (project / "data").exists()
    assert not (project / "output").exists()


def test_report_without_db_is_empty(project):
    assert run(project, "--report") == 0
    assert "No advisories qualified" in latest_report(project)
    assert not (project / "data").exists()


def test_sync_and_report_are_exclusive(project):
    with pytest.raises(SystemExit):
        run(project, "--sync", "--report")
