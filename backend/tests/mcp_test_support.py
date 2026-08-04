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


@contextmanager
def mcp_test_client(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_stub_auth: bool = False,
) -> Iterator[TestClient]:
    """Build a `create_app()` instance pointed at `vault`, wrapped in a
    `TestClient`, with `get_settings()`'s cache cleared on both sides --
    shared by `test_mcp_mount.py` and `test_mcp_auth.py`, which otherwise
    repeat this same setup for each of the app-level MCP request tests."""
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    if allow_stub_auth:
        monkeypatch.setenv("MCP_ALLOW_STUB_AUTH", "true")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            yield client
    finally:
        get_settings.cache_clear()
