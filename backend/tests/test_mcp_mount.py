from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cerebrum.auth import STUB_VALID_CREDENTIAL
from cerebrum.main import create_app
from cerebrum.settings import get_settings
from tests.mcp_test_support import INITIALIZE_PAYLOAD, MCP_HEADERS, mcp_test_client

_AUTHED_MCP_HEADERS = {
    **MCP_HEADERS,
    "Authorization": f"Bearer {STUB_VALID_CREDENTIAL}",
}


def test_mcp_mount_responds_to_handshake(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Auth (U5) now gates this mount; stub-auth is opted in here since this
    # test's own concern is the mount/handshake, not auth (see test_mcp_auth.py).
    with mcp_test_client(vault, monkeypatch, allow_stub_auth=True) as client:
        response = client.post(
            "/api/mcp", json=INITIALIZE_PAYLOAD, headers=_AUTHED_MCP_HEADERS
        )
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
    """If startup fails partway through (e.g. `rebuild_index()` raises), both
    the db connection and the FastMCP session manager must be torn down
    cleanly -- exercises the shared `AsyncExitStack`'s unwind, not just the
    happy path (KTD3)."""
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("cerebrum.main.rebuild_index", _boom)
    app = create_app()
    try:
        with pytest.raises(RuntimeError, match="boom"), TestClient(app):
            pass
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
            response = client.post(
                "/api/mcp", json=INITIALIZE_PAYLOAD, headers=_AUTHED_MCP_HEADERS
            )
            assert response.status_code == 200
