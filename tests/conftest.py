import json
from pathlib import Path

import pytest

from bafin_wid_reporter.parser import Wid

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def record() -> dict:
    return json.loads((FIXTURES / "record.json").read_text(encoding="utf-8"))


@pytest.fixture
def feed_bytes() -> bytes:
    return (FIXTURES / "feed.xml").read_bytes()


def make_wid(wid_id="WID-SEC-2026-0001", risk="hoch", status="new", title="Test advisory",
             match_tags=None, latest_revision="1", **overrides) -> Wid:
    values = dict(
        wid_id=wid_id, uuid="uuid-1", title=title, risk=risk, remotely_exploitable=True,
        description="desc", productdescription="product desc", import_status="new",
        damage="3", wid_advisory_liste=False, cve_ids="CVE-2026-0001",
        product_names=["Some Product"], latest_revision=latest_revision,
        current_release_date="2026-10-11T22:00:00.000+00:00", status=status,
        match_tags=match_tags or [],
    )
    values.update(overrides)
    return Wid(**values)
