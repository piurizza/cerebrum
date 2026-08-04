from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cerebrum.main import create_app
from cerebrum.settings import get_settings
from tests.mcp_test_support import (
    INITIALIZE_PAYLOAD,
    MCP_HEADERS,
    issue_test_access_token,
    mcp_test_client,
)


def test_mcp_mount_responds_to_handshake(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Auth (U5) now gates this mount; stub-auth is opted in here since this
    # test's own concern is the mount/handshake, not auth (see test_mcp_auth.py).
    with mcp_test_client(vault, monkeypatch, allow_stub_auth=True) as client:
        token = issue_test_access_token(client)
        headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=headers)
        assert response.status_code == 200


def test_existing_rest_routes_unaffected_by_mcp_mount(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mcp_test_client(vault, monkeypatch) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/notes").status_code == 200


def test_mcp_mount_absent_when_disabled(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_ENABLED", "false")
    with mcp_test_client(vault, monkeypatch) as client:
        response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=MCP_HEADERS)
        assert response.status_code == 404
        assert client.get("/api/health").status_code == 200


def test_lifespan_teardown_on_startup_failure(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If startup fails partway through (`rebuild_index()` raises, which
    `main.py` deliberately runs after the MCP session manager is entered --
    see the ordering comment there), both the db connection and the FastMCP
    session manager must be torn down cleanly -- exercises the shared
    `AsyncExitStack`'s unwind through an already-entered MCP context, not
    just the happy path (KTD3). Asserted concretely: a closed
    `sqlite3.Connection` raises on any further use, so a successful raise
    here proves `db.close()` actually ran, not just that the exception
    propagated."""
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    # See conftest.py's `client` fixture -- these two are required
    # settings with no default, so app construction fails without them.
    monkeypatch.setenv("AUTH_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AUTH_SETUP_TOKEN", "y" * 32)
    get_settings.cache_clear()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("cerebrum.main.rebuild_index", _boom)
    app = create_app()
    try:
        # Once the MCP session manager is entered, its own anyio task group
        # wraps a startup failure in an ExceptionGroup rather than letting
        # the plain RuntimeError propagate -- itself confirmation that this
        # failure now occurs inside that context, not before it.
        with pytest.raises((RuntimeError, ExceptionGroup)) as exc_info, TestClient(app):
            pass
        raised = exc_info.value
        if isinstance(raised, ExceptionGroup):
            assert any("boom" in str(exc) for exc in raised.exceptions)
        else:
            assert "boom" in str(raised)
        with pytest.raises(sqlite3.ProgrammingError):
            app.state.db.execute("SELECT 1")
    finally:
        get_settings.cache_clear()


def test_repeated_create_app_construction_has_no_state_leakage(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`create_mcp_server()`/`create_app()` are rebuilt fresh per test; this
    constructs and tears down several instances back-to-back within one
    process, exercising the mount/lifecycle quirks KTD3 cites from upstream
    FastMCP issues under repeated-construction load a full suite run
    actually produces."""
    for _ in range(3):
        with mcp_test_client(vault, monkeypatch, allow_stub_auth=True) as client:
            token = issue_test_access_token(client)
            headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
            response = client.post("/api/mcp", json=INITIALIZE_PAYLOAD, headers=headers)
            assert response.status_code == 200
