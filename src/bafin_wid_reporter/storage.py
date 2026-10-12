"""DuckDB storage: WID history, dedupe of already seen revisions, cleanup."""

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from .parser import Wid

log = logging.getLogger(__name__)

# Another process (e.g. an hourly --sync) may hold the write lock for a moment
LOCK_RETRIES = 10
LOCK_RETRY_SECONDS = 3

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


LOAD_COLUMNS = """
    id_kuerzel, uuid, title, risiko, remotely_exploitable, description, productdescription,
    import_status, damage, wid_advisory_liste, cve_ids, product_names, latest_revision,
    current_release_date, rss_status
"""


def open_with_retry(db_path: Path, read_only: bool) -> duckdb.DuckDBPyConnection:
    for attempt in range(1, LOCK_RETRIES + 1):
        try:
            return duckdb.connect(str(db_path), read_only=read_only)
        except duckdb.IOException as exc:
            if "lock" not in str(exc).lower() or attempt == LOCK_RETRIES:
                raise
            log.info("Database is locked by another process, retrying in %ds", LOCK_RETRY_SECONDS)
            time.sleep(LOCK_RETRY_SECONDS)
    raise AssertionError("unreachable")


def connect(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the DB. Read-only on a missing file gives an empty in-memory DB."""
    if read_only and not db_path.exists():
        con = duckdb.connect(":memory:")
    elif read_only:
        return open_with_retry(db_path, read_only=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = open_with_retry(db_path, read_only=False)
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


def row_to_wid(row: tuple) -> Wid:
    (wid_id, uuid, title, risk, remotely_exploitable, description, productdescription,
     import_status, damage, wid_advisory_liste, cve_ids, product_names, latest_revision,
     current_release_date, rss_status) = row
    return Wid(
        wid_id=wid_id, uuid=uuid or "", title=title or "", risk=risk or "",
        remotely_exploitable=remotely_exploitable, description=description or "",
        productdescription=productdescription or "", import_status=import_status or "",
        damage=damage or "", wid_advisory_liste=wid_advisory_liste, cve_ids=cve_ids or "",
        product_names=product_names.split(", ") if product_names else [],
        latest_revision=latest_revision or "", current_release_date=current_release_date or "",
        status=rss_status or "unknown",
    )


def load_changed_since(con: duckdb.DuckDBPyConnection, since: datetime) -> list[Wid]:
    """WIDs first stored or given a new revision at or after `since`. Match tags are not loaded."""
    rows = con.execute(
        f"SELECT {LOAD_COLUMNS} FROM wids WHERE last_changed_at >= ? ORDER BY id_kuerzel",
        [to_db_time(since)],
    ).fetchall()
    return [row_to_wid(row) for row in rows]


def cleanup_db(con: duckdb.DuckDBPyConnection, older_than_days: int, now: datetime) -> int:
    cutoff = to_db_time(now) - timedelta(days=older_than_days)
    count = con.execute("SELECT count(*) FROM wids WHERE last_seen_at < ?", [cutoff]).fetchone()[0]
    con.execute("DELETE FROM wids WHERE last_seen_at < ?", [cutoff])
    log.info("Removed %d WIDs not seen since %s", count, cutoff.isoformat(timespec="seconds"))
    return count
