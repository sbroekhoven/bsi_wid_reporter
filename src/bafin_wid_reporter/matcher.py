"""Match list checking and risk filtering."""

from .parser import Wid


def searchable_text(wid: Wid, fields: list[str]) -> str:
    parts = []
    for name in fields:
        if name == "product_names":
            parts.extend(wid.product_names)
        else:
            parts.append(getattr(wid, name, ""))
    return "\n".join(parts).lower()


def find_matches(wid: Wid, match_lists: dict[str, list[str]], fields: list[str]) -> list[tuple[str, str]]:
    """Return (group, keyword) pairs for every keyword found as case-insensitive substring."""
    haystack = searchable_text(wid, fields)
    return [
        (group, keyword)
        for group, keywords in match_lists.items()
        for keyword in keywords
        if keyword.lower() in haystack
    ]


def passes_filter(wid: Wid, risk_levels: list[str], match_overrides_risk_filter: bool) -> bool:
    if wid.risk.upper() in risk_levels:
        return True
    return match_overrides_risk_filter and bool(wid.match_tags)
