"""Load and validate config.yaml and matchlists.yaml."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ALLOWED_MATCH_FIELDS = {"title", "description", "productdescription", "product_names"}
ALLOWED_SEND_MODES = {"all", "matches_only"}


class ConfigError(Exception):
    pass


@dataclass
class HttpSettings:
    timeout_seconds: float = 20.0
    request_delay_seconds: float = 0.5
    max_retries: int = 3
    user_agent: str = "Mozilla/5.0 (compatible; bafin-wid-reporter/0.1; daily CERT-Bund WID monitor)"


@dataclass
class TeamsSettings:
    enabled: bool = False
    webhook_url_env: str = "TEAMS_WEBHOOK_URL"
    send_mode: str = "all"
    max_items: int = 25
    report_link: str = ""


@dataclass
class Config:
    feed_url: str
    api_base_url: str
    risk_levels: list[str]
    lookback_hours: float
    match_overrides_risk_filter: bool
    match_fields: list[str]
    db_path: Path
    output_dir: Path
    db_retention_days: int
    report_retention_days: int
    http: HttpSettings
    teams: TeamsSettings
    match_lists: dict[str, list[str]] = field(default_factory=dict)


def read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Top level of {path} must be a mapping")
    return data


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def validate_match_lists(raw: dict) -> dict[str, list[str]]:
    groups = raw.get("match_lists") or {}
    if not isinstance(groups, dict):
        raise ConfigError("match_lists must be a mapping of group name to keyword list")
    result = {}
    for group, keywords in groups.items():
        if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
            raise ConfigError(f"match_lists.{group} must be a list of strings")
        result[str(group)] = [k.strip() for k in keywords if k.strip()]
    return result


def build_teams_settings(raw: dict) -> TeamsSettings:
    teams = TeamsSettings(**(raw.get("teams") or {}))
    if teams.send_mode not in ALLOWED_SEND_MODES:
        raise ConfigError(f"teams.send_mode must be one of {sorted(ALLOWED_SEND_MODES)}")
    if teams.max_items < 1:
        raise ConfigError("teams.max_items must be at least 1")
    return teams


def load_config(config_dir: Path) -> Config:
    config_dir = config_dir.resolve()
    raw = read_yaml(config_dir / "config.yaml")
    match_raw = read_yaml(config_dir / "matchlists.yaml")
    project_root = config_dir.parent

    match_fields = list(raw.get("match_fields") or sorted(ALLOWED_MATCH_FIELDS))
    unknown = set(match_fields) - ALLOWED_MATCH_FIELDS
    if unknown:
        raise ConfigError(f"Unknown match_fields: {sorted(unknown)}")

    paths = raw.get("paths") or {}
    retention = raw.get("retention") or {}
    try:
        config = Config(
            feed_url=raw["feed_url"],
            api_base_url=raw.get("api_base_url", "https://wid.cert-bund.de/content/public").rstrip("/"),
            risk_levels=[str(r).upper() for r in raw.get("risk_levels") or ["KRITISCH", "HOCH"]],
            lookback_hours=float(raw.get("lookback_hours", 24)),
            match_overrides_risk_filter=bool(raw.get("match_overrides_risk_filter", True)),
            match_fields=match_fields,
            db_path=resolve_path(project_root, paths.get("db", "data/wids.duckdb")),
            output_dir=resolve_path(project_root, paths.get("output", "output")),
            db_retention_days=int(retention.get("db_days", 365)),
            report_retention_days=int(retention.get("report_days", 90)),
            http=HttpSettings(**(raw.get("http") or {})),
            teams=build_teams_settings(raw),
            match_lists=validate_match_lists(match_raw),
        )
    except KeyError as exc:
        raise ConfigError(f"Missing required config key: {exc}") from exc
    except TypeError as exc:
        raise ConfigError(f"Invalid config: {exc}") from exc

    log.debug("Loaded config from %s", config_dir)
    return config
