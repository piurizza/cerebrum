from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# `cerebrum.main` builds a module-level `app = create_app()` at import time
# (so uvicorn can resolve the "cerebrum.main:app" string target) -- so the
# `from cerebrum.main import create_app` below already runs settings
# validation before any fixture, or even pytest's collection, gets a
# chance to run. setdefault (a real, process-wide env var, not the
# per-test `monkeypatch.setenv` the `client` fixture below uses) exists
# purely to satisfy that early construction; individual tests still
# override/unset these via monkeypatch as needed, which shadows this
# default for the duration of the test and restores it after.
os.environ.setdefault("AUTH_JWT_SECRET", "x" * 32)
os.environ.setdefault("AUTH_SETUP_TOKEN", "y" * 32)

# pylint: disable=wrong-import-position
from cerebrum.index.db import connect  # noqa: E402
from cerebrum.main import create_app  # noqa: E402
from cerebrum.settings import get_settings  # noqa: E402
from tests.mcp_test_support import issue_test_access_token  # noqa: E402

# pylint: enable=wrong-import-position


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    return vault_dir


@pytest.fixture
def db(vault: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(vault / ".cerebrum" / "index.sqlite3")
    yield conn
    conn.close()


@pytest.fixture
def client(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    # auth_jwt_secret/auth_setup_token are required settings (see
    # settings.py) with no default -- app construction fails without them.
    # 32 "x"s / "y"s clear settings.py's minimum-length bar with room to
    # spare; the two differ so a test that leaks one into the other is
    # obvious rather than silently passing.
    monkeypatch.setenv("AUTH_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AUTH_SETUP_TOKEN", "y" * 32)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def authenticated_client(client: TestClient) -> TestClient:
    """Same `client` fixture, but with a real, live access token attached
    as a default `Authorization: Bearer <token>` header -- for REST tests
    that exercise routes now protected by `api_router`'s default auth
    dependency (U5) rather than the auth mechanism itself (see
    `test_rest_auth.py` for the latter).

    Bootstraps the one account this fixture needs via a real
    register-then-login round trip against this same `client`, reusing
    `mcp_test_support.issue_test_access_token()` (already written for the
    equivalent MCP-test need) rather than duplicating that dance here.
    `client`'s `AUTH_SETUP_TOKEN` env var (set by the `client` fixture
    above) is what lets that registration call succeed against an
    otherwise-empty `auth.sqlite3`.

    Setting the header on `client.headers` (an `httpx.Client` default,
    applied to every request `client` makes from here on) rather than
    threading `headers=...` through every call site is what lets the three
    REST test files below switch fixtures with a mechanical rename instead
    of rewriting every request.
    """
    token = issue_test_access_token(client)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
