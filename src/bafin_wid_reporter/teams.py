"""Adaptive Card building and posting to a Teams Workflows webhook."""

import json
import logging
import os
from datetime import datetime

import httpx

from .config_loader import TeamsSettings
from .parser import Wid
from .report import RunSummary, counts, report_title, sort_key

log = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 28_000


def text_block(text: str, **extra) -> dict:
    return {"type": "TextBlock", "text": text, "wrap": True, **extra}


def table_row(cells: list[str], header: bool = False) -> dict:
    return {
        "type": "TableRow",
        "style": "accent" if header else "default",
        "cells": [
            {"type": "TableCell", "items": [text_block(c, weight="Bolder" if header else "Default", size="Small")]}
            for c in cells
        ],
    }


def wid_table(wids: list[Wid]) -> dict:
    rows = [table_row(["Title", "WID", "Risk", "CVEs", "Matches"], header=True)]
    rows += [
        table_row([w.title, w.wid_id, w.risk, w.cve_ids or "-", w.match_tags_text or "-"])
        for w in wids
    ]
    return {
        "type": "Table",
        "gridStyle": "accent",
        "firstRowAsHeaders": True,
        "columns": [{"width": 4}, {"width": 2}, {"width": 1}, {"width": 3}, {"width": 2}],
        "rows": rows,
    }


def build_card(summary: RunSummary, wids: list[Wid], shown: list[Wid], omitted: int,
               report_url: str) -> dict:
    c = counts(wids)
    body = [
        text_block(report_title(summary.generated_at), size="Large", weight="Bolder"),
        {"type": "FactSet", "facts": [
            {"title": "Total", "value": str(c["total"])},
            {"title": "New", "value": str(c["new"])},
            {"title": "Updated", "value": str(c["updated"])},
            {"title": "Match hits", "value": str(c["matches"])},
        ]},
    ]
    if shown:
        body.append(wid_table(shown))
    else:
        body.append(text_block("No advisories to list."))
    if omitted:
        body.append(text_block(f"{omitted} more not shown, see the full report.", isSubtle=True))
    return wrap_card(body, report_url)


def wrap_card(body: list[dict], report_url: str) -> dict:
    content = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "msteams": {"width": "Full"},
        "body": body,
    }
    if report_url:
        content["actions"] = [{"type": "Action.OpenUrl", "title": "Open full report", "url": report_url}]
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "contentUrl": None,
            "content": content,
        }],
    }


def build_failure_payload(generated_at: datetime, error: str, window_start: datetime,
                          report_url: str) -> dict:
    rerun_from = window_start.strftime("%Y-%m-%d %H:%M %Z")
    body = [
        text_block(f"{report_title(generated_at)}: run failed", size="Large", weight="Bolder",
                   color="Attention"),
        text_block(f"Error: {error}"),
        text_block(f"Nothing was processed. Rerun with `uv run run.py --lookback HOURS`, "
                   f"where HOURS reaches back to at least {rerun_from}."),
    ]
    return wrap_card(body, report_url)


def report_url_for(settings: TeamsSettings, report_filename: str) -> str:
    return f"{settings.report_link.rstrip('/')}/{report_filename}" if settings.report_link else ""


def payload_size(payload: dict) -> int:
    return len(json.dumps(payload).encode("utf-8"))


def select_items(wids: list[Wid], send_mode: str) -> list[Wid]:
    selected = [w for w in wids if w.match_tags] if send_mode == "matches_only" else wids
    return sorted(selected, key=lambda w: (not w.match_tags, *sort_key(w)))


def build_payload(summary: RunSummary, wids: list[Wid], settings: TeamsSettings,
                  report_filename: str) -> dict:
    """Build the card, capped at max_items and shrunk further until it fits the size limit."""
    items = select_items(wids, settings.send_mode)
    report_url = report_url_for(settings, report_filename)
    shown_count = min(len(items), settings.max_items)
    while True:
        payload = build_card(summary, wids, items[:shown_count], len(items) - shown_count, report_url)
        if payload_size(payload) <= MAX_PAYLOAD_BYTES or shown_count == 0:
            return payload
        shown_count -= 1


def send_payload(payload: dict, settings: TeamsSettings, timeout: float) -> bool:
    """Post a payload to the webhook. Never raises; returns True on success."""
    webhook_url = os.environ.get(settings.webhook_url_env, "").strip()
    if not webhook_url:
        log.error("Teams enabled but environment variable %s is not set", settings.webhook_url_env)
        return False
    try:
        response = httpx.post(webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # The webhook URL carries a secret signature, so it is never logged
        log.error("Teams post failed: HTTP %s", exc.response.status_code)
        return False
    except httpx.HTTPError as exc:
        log.error("Teams post failed: %s", type(exc).__name__)
        return False
    log.info("Posted to Teams (%d bytes)", payload_size(payload))
    return True


def post_to_teams(summary: RunSummary, wids: list[Wid], settings: TeamsSettings,
                  report_filename: str, timeout: float = 20.0) -> bool:
    if settings.send_mode == "matches_only" and not any(w.match_tags for w in wids):
        log.info("No match hits, skipping Teams post (send_mode: matches_only)")
        return False
    return send_payload(build_payload(summary, wids, settings, report_filename), settings, timeout)


def post_failure_to_teams(generated_at: datetime, error: str, window_start: datetime,
                          settings: TeamsSettings, report_filename: str, timeout: float = 20.0) -> bool:
    payload = build_failure_payload(generated_at, error, window_start,
                                    report_url_for(settings, report_filename))
    return send_payload(payload, settings, timeout)
