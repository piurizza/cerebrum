from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.routing import BaseRoute, Mount, Route

from tests.mcp_test_support import (
    INITIALIZE_PAYLOAD,
    MCP_HEADERS,
    issue_test_access_token,
    issue_test_api_token,
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


def test_valid_credential_accepted_and_wrong_credential_rejected(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP auth is unconditionally on: a real, live access token is
    accepted and an invalid one is rejected, both going through
    `verify_credential()` for real."""
    with mcp_test_client(vault, monkeypatch) as client:
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


def test_invalid_credential_rejection_includes_discoverability_hint(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9: a *presented* credential that fails verification gets a
    rejection body naming where to generate a personal API token --
    `DiscoverabilityHintMiddleware` rewriting FastMCP's own hardcoded
    `RequireAuthMiddleware` message, not a bare 401. Confirmed at the HTTP
    layer, not just that `verify_token()` was called -- this is the
    response an MCP client actually receives, and FastMCP's own auth
    middleware fully owns and previously overwrote it."""
    with mcp_test_client(vault, monkeypatch) as client:
        bad_headers = {**MCP_HEADERS, "Authorization": "Bearer wrong"}
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=bad_headers)

        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "invalid_token"
        assert "personal API token" in body["error_description"]
        assert "settings page" in body["error_description"]
        # The rewrite must not silently disclose vault or account data --
        # only the fixed hint text is appended to FastMCP's own message.
        assert "vault" not in body["error_description"].lower()


def test_missing_credential_rejection_stays_rfc_6750_compliant(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-`Authorization`-header case is deliberately NOT rewritten:
    RFC 6750 §3.1 forbids an `error` attribute on this specific response
    shape (it exists so an MCP client can tell "no credential presented
    yet" apart from "credential rejected" during OAuth discovery), and
    `DiscoverabilityHintMiddleware` only touches the `invalid_token` shape
    -- this pins that the empty-body response is untouched, not silently
    broken by the rewrite."""
    with mcp_test_client(vault, monkeypatch) as client:
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=MCP_HEADERS)

        assert response.status_code == 401
        assert response.content == b""


def test_personal_api_token_authenticates_through_the_live_mcp_mount(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Personal API tokens are the credential this feature is meant to make
    MCP clients use day-to-day (R6/R9), but every other MCP test in this
    file authenticates with a session JWT via `issue_test_access_token()`.
    `SharedFunctionTokenVerifier` has no credential-type branching of its
    own -- both shapes flow through the identical `verify_credential()`
    call -- but this proves the PAT shape specifically against the real
    `/api/mcp` POST, not just unit-level in `test_auth.py`."""
    with mcp_test_client(vault, monkeypatch) as client:
        token = issue_test_api_token(client)
        headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=headers)
        assert response.status_code == 200


def test_deactivated_accounts_open_connection_rejected_on_next_call(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercises the "no caching" behavior of `TokenVerifier.verify_token()`
    (FastMCP calls it fresh on every request): a token issued while the
    account was active is accepted, then rejected on the very next call
    once that account is deactivated -- even though the JWT itself hasn't
    expired and the client never reconnected."""
    with mcp_test_client(vault, monkeypatch) as client:
        token = issue_test_access_token(client)
        headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}

        first_response = client.post(
            "/api/mcp", json=INITIALIZE_PAYLOAD, headers=headers
        )
        assert first_response.status_code == 200

        auth_db: sqlite3.Connection = client.app.state.auth_db
        with auth_db:
            auth_db.execute("UPDATE users SET is_active = 0")

        second_response = client.post(
            "/api/mcp", json=INITIALIZE_PAYLOAD, headers=headers
        )
        assert second_response.status_code == 401


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
