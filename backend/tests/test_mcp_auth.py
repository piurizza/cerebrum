from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.routing import BaseRoute, Mount, Route

from tests.mcp_test_support import (
    INITIALIZE_PAYLOAD,
    MCP_HEADERS,
    issue_test_access_token,
    mcp_test_client,
)


def _mcp_mount(app: FastAPI) -> Mount:
    for route in app.routes:
        if isinstance(route, Mount) and route.path == "/api/mcp":
            return route
    raise AssertionError("expected an /api/mcp mount on the app")


def _iter_routes(routes: list[BaseRoute], prefix: str = "") -> list[tuple[str, Route]]:
    """Recursively flatten a Starlette route table into (full_path, Route)
    pairs, descending into any nested `Mount`. A future FastMCP release
    could add a privileged endpoint inside a `Mount` (this library family
    already does so for other transports, e.g. SSE) rather than a bare
    `Route` -- the R9 route-enumeration guarantee must see it too, not just
    today's single top-level route."""
    found: list[tuple[str, Route]] = []
    for route in routes:
        if isinstance(route, Mount):
            sub_routes: Any = getattr(route.app, "routes", None)
            if sub_routes:
                found.extend(_iter_routes(sub_routes, prefix + route.path))
        elif isinstance(route, Route):
            found.append((prefix + route.path, route))
    return found


def test_request_with_no_credential_is_rejected(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mcp_test_client(vault, monkeypatch) as client:
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=MCP_HEADERS)
        assert response.status_code == 401


def test_valid_credential_accepted_when_gate_allowed(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mcp_test_client(vault, monkeypatch, allow_stub_auth=True) as client:
        token = issue_test_access_token(client)
        good_headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
        good_response = client.post(
            "/api/mcp", json=INITIALIZE_PAYLOAD, headers=good_headers
        )
        assert good_response.status_code == 200

        bad_headers = {**MCP_HEADERS, "Authorization": "Bearer wrong"}
        bad_response = client.post(
            "/api/mcp", json=INITIALIZE_PAYLOAD, headers=bad_headers
        )
        assert bad_response.status_code == 401


def test_credential_rejected_when_gate_not_allowed(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`mcp_allow_stub_auth` defaults `False` -- even a credential that
    would otherwise verify must be rejected at the app-level request path
    when this gate is off (fails closed end-to-end, not only inside
    `verify_credential()` itself)."""
    with mcp_test_client(vault, monkeypatch) as client:
        headers = {**MCP_HEADERS, "Authorization": "Bearer irrelevant-credential"}
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
        mcp_routes = _iter_routes(mount.app.routes)
        assert mcp_routes, "expected at least one route on the MCP mount"

        for full_path, _route in mcp_routes:
            suffix = "" if full_path == "/" else full_path
            response = client.post(
                f"/api/mcp{suffix}",
                json=INITIALIZE_PAYLOAD,
                headers=MCP_HEADERS,
            )
            assert response.status_code == 401, (
                f"route {full_path!r} did not reject an unauthenticated request"
            )
