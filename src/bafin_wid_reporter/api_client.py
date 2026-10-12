"""HTTP access to the WID portal: polite GETs, UUID lookup and full content fetch."""

import logging
import time

import httpx

from .config_loader import HttpSettings

log = logging.getLogger(__name__)

RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


class PoliteClient:
    """httpx client with timeouts, a delay between requests and retry with backoff."""

    def __init__(self, settings: HttpSettings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.client = httpx.Client(
            timeout=settings.timeout_seconds,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
            transport=transport,
        )
        self.last_request_at = 0.0

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def wait_for_slot(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        remaining = self.settings.request_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_at = time.monotonic()

    def get(self, url: str) -> httpx.Response:
        attempts = self.settings.max_retries + 1
        for attempt in range(1, attempts + 1):
            self.wait_for_slot()
            try:
                response = self.client.get(url)
            except httpx.TransportError as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                if response.is_success:
                    return response
                if response.status_code not in RETRY_STATUS_CODES:
                    raise FetchError(f"GET {url} returned HTTP {response.status_code}")
                error = f"HTTP {response.status_code}"
            if attempt < attempts:
                backoff = 2 ** (attempt - 1)
                log.warning("GET %s failed (%s), retry %d/%d in %ss",
                            url, error, attempt, attempts - 1, backoff)
                time.sleep(backoff)
        raise FetchError(f"GET {url} failed after {attempts} attempts: {error}")


def lookup_uuid(client: PoliteClient, api_base_url: str, wid_id: str) -> str:
    url = f"{api_base_url}/securityAdvisory/kurzinfo-uuid-by-name/{wid_id}"
    uuid = client.get(url).text.strip().strip('"')
    if not uuid:
        raise FetchError(f"Empty UUID returned for {wid_id}")
    return uuid


def fetch_content(client: PoliteClient, api_base_url: str, uuid: str) -> dict:
    url = f"{api_base_url}/content/{uuid}"
    try:
        return client.get(url).json()
    except ValueError as exc:
        raise FetchError(f"Invalid JSON from {url}") from exc


def fetch_wid_record(client: PoliteClient, api_base_url: str, wid_id: str) -> tuple[str, dict]:
    """Return (uuid, full JSON record) for a WID ID."""
    uuid = lookup_uuid(client, api_base_url, wid_id)
    return uuid, fetch_content(client, api_base_url, uuid)
