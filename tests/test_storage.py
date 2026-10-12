from datetime import datetime, timedelta, timezone

from bafin_wid_reporter import storage

from conftest import make_wid

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def row(con, wid_id):
    return con.execute(
        "SELECT latest_revision, first_seen_at, last_seen_at, last_changed_at FROM wids WHERE id_kuerzel = ?",
        [wid_id],
    ).fetchone()


def test_seen_detection_and_upsert(tmp_path):
    con = storage.connect(tmp_path / "wids.duckdb")
    wid = make_wid()
    assert not storage.is_already_seen(con, wid)

    storage.save_wids(con, [wid], NOW)
    assert storage.is_already_seen(con, wid)

    later = NOW + timedelta(days=1)
    storage.save_wids(con, [wid], later)
    revision, first_seen, last_seen, last_changed = row(con, wid.wid_id)
    assert first_seen == NOW.replace(tzinfo=None)
    assert last_seen == later.replace(tzinfo=None)
    assert last_changed == NOW.replace(tzinfo=None)

    changed = make_wid(latest_revision="2")
    assert not storage.is_already_seen(con, changed)
    storage.save_wids(con, [changed], later + timedelta(days=1))
    revision, _, _, last_changed = row(con, wid.wid_id)
    assert revision == "2"
    assert last_changed == (later + timedelta(days=1)).replace(tzinfo=None)


def test_read_only_on_missing_db_is_empty(tmp_path):
    path = tmp_path / "missing.duckdb"
    con = storage.connect(path, read_only=True)
    assert not storage.is_already_seen(con, make_wid())
    assert not path.exists()


def test_cleanup_uses_last_seen(tmp_path):
    con = storage.connect(tmp_path / "wids.duckdb")
    storage.save_wids(con, [make_wid("WID-OLD")], NOW - timedelta(days=400))
    storage.save_wids(con, [make_wid("WID-NEW")], NOW - timedelta(days=10))
    assert storage.cleanup_db(con, 365, NOW) == 1
    assert con.execute("SELECT id_kuerzel FROM wids").fetchall() == [("WID-NEW",)]


def test_load_changed_since_round_trip(tmp_path):
    con = storage.connect(tmp_path / "wids.duckdb")
    wid = make_wid("WID-A", status="updated", product_names=["Product A", "Product B"],
                   match_tags=[("g", "k")])
    storage.save_wids(con, [wid], NOW)
    storage.save_wids(con, [make_wid("WID-OLD")], NOW - timedelta(days=2))
    # Seen again without a new revision: last_changed_at stays old
    storage.save_wids(con, [make_wid("WID-OLD")], NOW)

    loaded = storage.load_changed_since(con, NOW - timedelta(hours=1))
    assert [w.wid_id for w in loaded] == ["WID-A"]
    expected = make_wid("WID-A", status="updated", product_names=["Product A", "Product B"])
    assert loaded[0] == expected
