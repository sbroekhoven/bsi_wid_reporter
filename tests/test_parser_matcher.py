from bafin_wid_reporter.matcher import find_matches, passes_filter
from bafin_wid_reporter.parser import parse_record

from conftest import make_wid

MATCH_LISTS = {
    "virtualization": ["vmware", "esxi"],
    "java_frameworks": ["spring boot"],
}
ALL_FIELDS = ["title", "description", "productdescription", "product_names"]


def test_parse_record(record):
    wid = parse_record(record, "the-uuid", status="updated")
    assert wid.wid_id == "WID-SEC-2026-2272"
    assert wid.uuid == "the-uuid"
    assert wid.title == "CPython: Schwachstelle ermöglicht Denial of Service"
    assert wid.risk == "hoch"
    assert wid.remotely_exploitable is True
    assert wid.wid_advisory_liste is False
    assert wid.damage == "3"
    assert wid.import_status == "update"
    assert wid.cve_ids == "CVE-2026-15308"
    assert wid.product_names == ["IBM AIX 7.3", "IBM VIOS 4.1", "Google Container-Optimized OS"]
    assert wid.latest_revision == "41"
    assert wid.current_release_date == "2026-10-11T22:00:00.000+00:00"
    assert wid.status == "updated"


def test_parse_record_title_fallback_and_missing_lists():
    record = {"properties": {"title": "Fallback", "idKuerzel": "WID-SEC-2026-1"}, "children": []}
    wid = parse_record(record, "u")
    assert wid.title == "Fallback"
    assert wid.cve_ids == ""
    assert wid.product_names == []


def test_find_matches_is_case_insensitive_substring():
    wid = make_wid(title="VMware ESXi: Mehrere Schwachstellen")
    assert find_matches(wid, MATCH_LISTS, ALL_FIELDS) == [("virtualization", "vmware"), ("virtualization", "esxi")]


def test_find_matches_in_product_names_only_when_configured():
    wid = make_wid(product_names=["Spring Boot 3.2"])
    assert find_matches(wid, MATCH_LISTS, ALL_FIELDS) == [("java_frameworks", "spring boot")]
    assert find_matches(wid, MATCH_LISTS, ["title"]) == []


def test_passes_filter():
    levels = ["KRITISCH", "HOCH"]
    assert passes_filter(make_wid(risk="hoch"), levels, False)
    assert not passes_filter(make_wid(risk="mittel"), levels, False)
    matched = make_wid(risk="mittel", match_tags=[("virtualization", "vmware")])
    assert not passes_filter(matched, levels, False)
    assert passes_filter(matched, levels, True)
