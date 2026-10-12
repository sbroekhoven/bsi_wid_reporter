"""Extract report fields from a WID content JSON record."""

from dataclasses import dataclass, field


@dataclass
class Wid:
    wid_id: str
    uuid: str
    title: str
    risk: str
    remotely_exploitable: bool | None
    description: str
    productdescription: str
    import_status: str
    damage: str
    wid_advisory_liste: bool | None
    cve_ids: str
    product_names: list[str]
    latest_revision: str
    current_release_date: str
    status: str = "unknown"  # from RSS: new | updated | unknown
    match_tags: list[tuple[str, str]] = field(default_factory=list)

    @property
    def match_tags_text(self) -> str:
        return ", ".join(f"{group} / {keyword}" for group, keyword in self.match_tags)


def find_child(record: dict, name: str) -> dict | None:
    for child in record.get("children") or []:
        if isinstance(child, dict) and child.get("name") == name:
            return child
    return None


def child_property_values(record: dict, list_name: str, prop: str) -> list[str]:
    """Collect properties[prop] from the children of the named list node, keeping order, no dupes."""
    node = find_child(record, list_name)
    values: list[str] = []
    for item in (node or {}).get("children") or []:
        value = ((item or {}).get("properties") or {}).get(prop)
        if value and str(value) not in values:
            values.append(str(value))
    return values


def text(value) -> str:
    return "" if value is None else str(value)


def parse_record(record: dict, uuid: str, status: str = "unknown") -> Wid:
    props = record.get("properties") or {}
    return Wid(
        wid_id=text(props.get("idKuerzel") or record.get("name")),
        uuid=uuid,
        title=text(props.get("documenttitle") or props.get("title")),
        risk=text(props.get("risiko")),
        remotely_exploitable=props.get("remotelyExploitable"),
        description=text(props.get("description")),
        productdescription=text(props.get("productdescription")),
        import_status=text(props.get("importStatus")),
        damage=text(props.get("damage")),
        wid_advisory_liste=props.get("widAdvisoryListe"),
        cve_ids=", ".join(child_property_values(record, "cveIdListe", "cveId")),
        product_names=child_property_values(record, "productReferenceListe", "name"),
        latest_revision=text(props.get("latestrevision")),
        current_release_date=text(props.get("currentreleasedate")),
        status=status,
    )
