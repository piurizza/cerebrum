from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.routing import Mount, Route

from cerebrum.auth import STUB_VALID_CREDENTIAL
from tests.mcp_test_support import INITIALIZE_PAYLOAD, MCP_HEADERS, mcp_test_client


def _mcp_mount(app: FastAPI) -> Mount:
    for route in app.routes:
        if isinstance(route, Mount) and route.path == "/api/mcp":
            return route
    raise AssertionError("expected an /api/mcp mount on the app")


def test_request_with_no_credential_is_rejected(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mcp_test_client(vault, monkeypatch) as client:
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=MCP_HEADERS)
        assert response.status_code == 401


def test_valid_stubbed_credential_accepted_when_stub_auth_allowed(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mcp_test_client(vault, monkeypatch, allow_stub_auth=True) as client:
        good_headers = {
            **MCP_HEADERS,
            "Authorization": f"Bearer {STUB_VALID_CREDENTIAL}",
        }
        good_response = client.post(
            "/api/mcp", json=INITIALIZE_PAYLOAD, headers=good_headers
        )
        assert good_response.status_code == 200

        bad_headers = {**MCP_HEADERS, "Authorization": "Bearer wrong"}
        bad_response = client.post(
            "/api/mcp", json=INITIALIZE_PAYLOAD, headers=bad_headers
        )
        assert bad_response.status_code == 401


def test_stub_sentinel_rejected_when_stub_auth_not_allowed(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`mcp_allow_stub_auth` defaults `False` -- even the stub's own "valid"
    sentinel must be rejected at the app-level request path, not just
    inside `verify_credential()` itself (fails closed end-to-end, not only
    at the stub function's own default-deny)."""
    with mcp_test_client(vault, monkeypatch) as client:
        headers = {
            **MCP_HEADERS,
            "Authorization": f"Bearer {STUB_VALID_CREDENTIAL}",
        }
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=headers)
        assert response.status_code == 401


def test_route_enumeration_every_mcp_route_rejects_unauthenticated_request(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9: verified by walking the actual mounted ASGI route table at test
    time, not a hand-maintained list of known endpoints -- motivated by
    CVE-2026-33032 ("MCPwn"), where a second endpoint serving the same
    privileged tools bypassed auth via an allowlist that defaulted open.
    Must be re-run whenever the FastMCP dependency version changes."""
    with mcp_test_client(vault, monkeypatch) as client:
        mount = _mcp_mount(client.app)
        mcp_routes = [route for route in mount.app.routes if isinstance(route, Route)]
        assert mcp_routes, "expected at least one route on the MCP mount"

        for route in mcp_routes:
            suffix = "" if route.path == "/" else route.path
            response = client.post(
                f"/api/mcp{suffix}",
                json=INITIALIZE_PAYLOAD,
                headers=MCP_HEADERS,
            )
            assert response.status_code == 401, (
                f"route {route.path!r} did not reject an unauthenticated request"
            )
