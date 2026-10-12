"""DuckDB storage: WID history, dedupe of already seen revisions, cleanup."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from .parser import Wid

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS wids (
    id_kuerzel VARCHAR PRIMARY KEY,
    uuid VARCHAR,
    title VARCHAR,
    risiko VARCHAR,
    remotely_exploitable BOOLEAN,
    description VARCHAR,
    productdescription VARCHAR,
    import_status VARCHAR,
    damage VARCHAR,
    wid_advisory_liste BOOLEAN,
    cve_ids VARCHAR,
    product_names VARCHAR,
    match_tags VARCHAR,
    rss_status VARCHAR,
    latest_revision VARCHAR,
    current_release_date VARCHAR,
    first_seen_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    last_changed_at TIMESTAMP
)
"""

UPSERT = """
INSERT INTO wids VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (id_kuerzel) DO UPDATE SET
    uuid = excluded.uuid,
    title = excluded.title,
    risiko = excluded.risiko,
    remotely_exploitable = excluded.remotely_exploitable,
    description = excluded.description,
    productdescription = excluded.productdescription,
    import_status = excluded.import_status,
    damage = excluded.damage,
    wid_advisory_liste = excluded.wid_advisory_liste,
    cve_ids = excluded.cve_ids,
    product_names = excluded.product_names,
    match_tags = excluded.match_tags,
    rss_status = excluded.rss_status,
    last_changed_at = CASE
        WHEN wids.latest_revision IS DISTINCT FROM excluded.latest_revision
          OR wids.current_release_date IS DISTINCT FROM excluded.current_release_date
        THEN excluded.last_changed_at ELSE wids.last_changed_at END,
    latest_revision = excluded.latest_revision,
    current_release_date = excluded.current_release_date,
    last_seen_at = excluded.last_seen_at
"""


def connect(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the DB. Read-only on a missing file gives an empty in-memory DB (dry runs)."""
    if read_only and not db_path.exists():
        con = duckdb.connect(":memory:")
    elif read_only:
        return duckdb.connect(str(db_path), read_only=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)
    return con


def to_db_time(moment: datetime) -> datetime:
    """Store timestamps as naive UTC."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def is_already_seen(con: duckdb.DuckDBPyConnection, wid: Wid) -> bool:
    """True if this WID is stored with the same revision and release date."""
    row = con.execute(
        "SELECT latest_revision, current_release_date FROM wids WHERE id_kuerzel = ?",
        [wid.wid_id],
    ).fetchone()
    return row is not None and row == (wid.latest_revision, wid.current_release_date)


def upsert_wid(con: duckdb.DuckDBPyConnection, wid: Wid, now: datetime) -> None:
    con.execute(UPSERT, [
        wid.wid_id, wid.uuid, wid.title, wid.risk, wid.remotely_exploitable,
        wid.description, wid.productdescription, wid.import_status, wid.damage,
        wid.wid_advisory_liste, wid.cve_ids, ", ".join(wid.product_names),
        wid.match_tags_text, wid.status, wid.latest_revision, wid.current_release_date,
        to_db_time(now), to_db_time(now), to_db_time(now),
    ])


def save_wids(con: duckdb.DuckDBPyConnection, wids: list[Wid], now: datetime) -> None:
    con.execute("BEGIN TRANSACTION")
    for wid in wids:
        upsert_wid(con, wid, now)
    con.execute("COMMIT")
    log.info("Stored %d WIDs in the database", len(wids))


def cleanup_db(con: duckdb.DuckDBPyConnection, older_than_days: int, now: datetime) -> int:
    cutoff = to_db_time(now) - timedelta(days=older_than_days)
    count = con.execute("SELECT count(*) FROM wids WHERE last_seen_at < ?", [cutoff]).fetchone()[0]
    con.execute("DELETE FROM wids WHERE last_seen_at < ?", [cutoff])
    log.info("Removed %d WIDs not seen since %s", count, cutoff.isoformat(timespec="seconds"))
    return count
