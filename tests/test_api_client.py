import httpx
import pytest

from bsi_wid_reporter import api_client
from bsi_wid_reporter.api_client import FetchError, PoliteClient, lookup_uuid
from bsi_wid_reporter.config_loader import HttpSettings

SETTINGS = HttpSettings(request_delay_seconds=0, max_retries=2)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(api_client.time, "sleep", lambda seconds: None)


def client_with(responses: list[httpx.Response]) -> PoliteClient:
    queue = iter(responses)
    return PoliteClient(SETTINGS, transport=httpx.MockTransport(lambda request: next(queue)))


def test_retries_transient_errors_then_succeeds():
    client = client_with([httpx.Response(503), httpx.Response(429), httpx.Response(200, text='"abc"')])
    assert lookup_uuid(client, "https://x", "WID-SEC-2026-1") == "abc"


def test_gives_up_after_max_retries():
    client = client_with([httpx.Response(503)] * 3)
    with pytest.raises(FetchError, match="after 3 attempts"):
        client.get("https://x/y")


def test_client_error_is_not_retried():
    client = client_with([httpx.Response(404)])
    with pytest.raises(FetchError, match="HTTP 404"):
        client.get("https://x/y")


def test_sends_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200)

    PoliteClient(SETTINGS, transport=httpx.MockTransport(handler)).get("https://x/y")
    assert seen["ua"].startswith("Mozilla/5.0 ")
    assert "bsi-wid-reporter/" in seen["ua"]
