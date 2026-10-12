from datetime import datetime, timezone

from bsi_wid_reporter.rss import extract_status, extract_wid_id, filter_window, parse_feed

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)


def test_extract_wid_id():
    link = "https://wid.cert-bund.de/portal/wid/securityadvisory?name=WID-SEC-2026-2025"
    assert extract_wid_id(link) == "WID-SEC-2026-2025"
    assert extract_wid_id("https://example.org/") is None


def test_extract_status():
    assert extract_status("[NEU] [hoch] Foo") == "new"
    assert extract_status("[UPDATE] [hoch] Foo") == "updated"
    assert extract_status("Foo") == "unknown"


def test_parse_feed_skips_items_without_wid(feed_bytes):
    items = parse_feed(feed_bytes)
    assert [i.wid_id for i in items] == ["WID-SEC-2026-2272", "WID-SEC-2026-3872", "WID-SEC-2026-0001"]
    assert items[0].status == "updated"
    assert items[1].status == "new"
    assert items[1].risk == "kritisch"
    assert items[0].published == datetime(2026, 10, 12, 11, 54, 13, tzinfo=timezone.utc)


def test_filter_window_uses_lookback(feed_bytes):
    items = parse_feed(feed_bytes)
    assert {i.wid_id for i in filter_window(items, NOW, 24)} == {"WID-SEC-2026-2272", "WID-SEC-2026-3872"}
    assert [i.wid_id for i in filter_window(items, NOW, 7)] == ["WID-SEC-2026-2272"]


def test_filter_window_dedupes_wid_ids(feed_bytes):
    items = parse_feed(feed_bytes)
    duplicate = parse_feed(feed_bytes)[0]
    duplicate.published = duplicate.published.replace(hour=8)
    window = filter_window(items + [duplicate], NOW, 24)
    assert len(window) == 2
    assert window[0].published.hour == 11
