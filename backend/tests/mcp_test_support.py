from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cerebrum.main import create_app
from cerebrum.settings import get_settings

INITIALIZE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}

# Matches `mcp_test_client()`'s own `AUTH_SETUP_TOKEN` env var below.
_SETUP_TOKEN = "y" * 32
_PASSWORD = "correct horse battery staple"


@contextmanager
def mcp_test_client(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Build a `create_app()` instance pointed at `vault`, wrapped in a
    `TestClient`, with `get_settings()`'s cache cleared on both sides --
    shared by `test_mcp_mount.py` and `test_mcp_auth.py`, which otherwise
    repeat this same setup for each of the app-level MCP request tests."""
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    # See conftest.py's `client` fixture -- these two are required
    # settings with no default, so app construction fails without them.
    monkeypatch.setenv("AUTH_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AUTH_SETUP_TOKEN", "y" * 32)
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            yield client
    finally:
        get_settings.cache_clear()


def issue_test_access_token(
    client: TestClient, username: str = "mcp-test-user", password: str = _PASSWORD
) -> str:
    """Register and log in for real, returning a live access-token JWT to
    send as `Authorization: Bearer <token>` -- real end-to-end credential
    issuance now that `verify_credential()` performs real JWT
    verification and MCP auth is unconditionally on.

    `mcp_test_client()` reuses the same `vault` (and therefore the same
    persisted `auth.sqlite3`) across repeated `create_app()` calls within
    one test -- see `test_mcp_mount.py`'s state-leakage test -- so a
    second call would otherwise fail: `_SETUP_TOKEN` only bootstraps the
    very first account in a given `auth.sqlite3`, and `register_account()`
    validates the token *before* checking username availability (U2), so
    a second registration attempt fails as an invalid token (400), never
    as a username collision (409). Handle that by falling back to a plain
    login on that 400, rather than requiring every caller to track
    whether it's the first call against this particular vault.
    """
    register_response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "token": _SETUP_TOKEN},
    )
    if register_response.status_code not in (201, 400):
        raise AssertionError(
            f"unexpected /api/auth/register response: {register_response.text}"
        )

    login_response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    if login_response.status_code != 200:
        raise AssertionError(
            f"unexpected /api/auth/login response: {login_response.text}"
        )
    return str(login_response.json()["access_token"])


def issue_test_api_token(
    client: TestClient, username: str = "mcp-test-user", password: str = _PASSWORD
) -> str:
    """Register/log in for real (via `issue_test_access_token()`), then
    mint a real personal API token through `POST /api/tokens` and return
    its plaintext -- for tests that need to prove the PAT credential
    shape specifically works end-to-end (e.g. through the live `/api/mcp`
    mount), not just the session-JWT shape `issue_test_access_token()`
    already covers."""
    access_token = issue_test_access_token(client, username, password)
    response = client.post(
        "/api/tokens",
        json={"name": "mcp-client"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code != 201:
        raise AssertionError(f"unexpected POST /api/tokens response: {response.text}")
    return str(response.json()["token"])
