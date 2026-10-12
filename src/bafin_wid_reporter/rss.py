"""Fetch and parse the WID RSS feed, extract WID IDs within the lookback window."""

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser

from .api_client import PoliteClient

log = logging.getLogger(__name__)

WID_ID_PATTERN = re.compile(r"[?&]name=(WID-SEC-\d{4}-\d+)")
STATUS_PATTERN = re.compile(r"^\s*\[(NEU|UPDATE)\]", re.IGNORECASE)
STATUS_MAP = {"NEU": "new", "UPDATE": "updated"}


@dataclass
class FeedItem:
    wid_id: str
    title: str
    status: str  # new | updated | unknown
    risk: str
    published: datetime


def extract_wid_id(link: str) -> str | None:
    match = WID_ID_PATTERN.search(link or "")
    return match.group(1) if match else None


def extract_status(title: str) -> str:
    match = STATUS_PATTERN.match(title or "")
    return STATUS_MAP[match.group(1).upper()] if match else "unknown"


def entry_to_item(entry) -> FeedItem | None:
    wid_id = extract_wid_id(entry.get("link", ""))
    published = entry.get("published_parsed")
    if not wid_id or not published:
        log.warning("Skipping RSS entry without WID ID or pubDate: %s", entry.get("link"))
        return None
    return FeedItem(
        wid_id=wid_id,
        title=entry.get("title", ""),
        status=extract_status(entry.get("title", "")),
        risk=entry.get("category", ""),
        published=datetime.fromtimestamp(calendar.timegm(published), tz=timezone.utc),
    )


def parse_feed(content: bytes) -> list[FeedItem]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Could not parse RSS feed: {feed.bozo_exception}")
    items = [entry_to_item(entry) for entry in feed.entries]
    return [item for item in items if item is not None]


def filter_window(items: list[FeedItem], now: datetime, lookback_hours: float) -> list[FeedItem]:
    """Keep items published within the window, one per WID ID (most recent wins)."""
    since = now - timedelta(hours=lookback_hours)
    latest: dict[str, FeedItem] = {}
    for item in items:
        if item.published < since or item.published > now:
            continue
        current = latest.get(item.wid_id)
        if current is None or item.published > current.published:
            latest[item.wid_id] = item
    return sorted(latest.values(), key=lambda i: i.published, reverse=True)


def fetch_feed(client: PoliteClient, feed_url: str) -> list[FeedItem]:
    response = client.get(feed_url)
    items = parse_feed(response.content)
    log.info("RSS feed returned %d items", len(items))
    return items
