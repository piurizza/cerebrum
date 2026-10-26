"""The `Host` check `POST /api/auth/oidc/start` makes before building the
redirect URI from it. The provider's registered redirect URIs are the real
allowlist; this only refuses values that aren't a host at all, so nothing
odd is ever spliced into the URL. Kept apart from `test_oidc_routes.py`,
which is at the module-length limit."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.oidc_fake import FakeProvider

_START = "/api/auth/oidc/start"


@pytest.mark.parametrize(
    "host",
    [
        "evil.example/path@x",
        "evil.example?x=1",
        "evil example",
        "user@evil.example",
        "evil.example:port",
        "[::1",
    ],
)
def test_start_refuses_a_malformed_host(
    fake_provider: FakeProvider, client: TestClient, host: str
) -> None:
    response = client.post(_START, json={"intent": "login"}, headers={"Host": host})

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Invalid Host header"
    assert "set-cookie" not in response.headers
    assert not fake_provider.requests


@pytest.mark.parametrize(
    ("host", "redirect_uri"),
    [
        ("[::1]:7812", "http://[::1]:7812/api/auth/oidc/callback"),
        ("[fd7a:115c::1]", "http://[fd7a:115c::1]/api/auth/oidc/callback"),
        ("192.0.2.10:7811", "http://192.0.2.10:7811/api/auth/oidc/callback"),
    ],
)
@pytest.mark.usefixtures("fake_provider")
def test_start_accepts_ip_hosts(
    client: TestClient, host: str, redirect_uri: str
) -> None:
    response = client.post(_START, json={"intent": "login"}, headers={"Host": host})

    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert query["redirect_uri"] == [redirect_uri]
