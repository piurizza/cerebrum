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
from cerebrum.accounts.oidc import use_transport  # noqa: E402
from cerebrum.auth_db import connect as connect_auth_db  # noqa: E402
from cerebrum.index.db import connect  # noqa: E402
from cerebrum.index.indexer import PendingRenameCache  # noqa: E402
from cerebrum.main import create_app  # noqa: E402
from cerebrum.settings import get_settings  # noqa: E402
from tests.mcp_test_support import issue_test_access_token  # noqa: E402
from tests.oidc_fake import FakeProvider, configure_oidc_env  # noqa: E402

# pylint: enable=wrong-import-position


@pytest.fixture(autouse=True)
def _state_paths_inside_test_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the index and accounts database to their in-vault defaults for
    every test. A blank variable outranks backend/.env, so a developer's
    CEREBRUM_AUTH_DB_PATH (or one in the shell) can never point the suite at
    a real accounts database. Tests that need other paths set them again.
    Read-only mode is pinned off for the same reason; `read_only_env` turns
    it back on."""
    monkeypatch.setenv("CEREBRUM_INDEX_PATH", "")
    monkeypatch.setenv("CEREBRUM_AUTH_DB_PATH", "")
    monkeypatch.setenv("CEREBRUM_VAULT_READ_ONLY", "false")


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
def pending_renames() -> PendingRenameCache:
    """A fresh, isolated cross-window rename cache per test -- mirrors
    the `vault`/`db` fixture pattern rather than a module-level global,
    so tests never leak pending state into one another."""
    return PendingRenameCache(window_seconds=30)


@pytest.fixture
def auth_db(vault: Path) -> Iterator[sqlite3.Connection]:
    conn = connect_auth_db(vault / ".cerebrum" / "auth.sqlite3")
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
def read_only_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Turn on read-only vault mode, with the index and accounts database
    under `tmp_path/state/` -- read-only mode refuses to start with either
    inside the vault. Yields that state folder."""
    state_dir = tmp_path / "state"
    monkeypatch.setenv("CEREBRUM_VAULT_READ_ONLY", "true")
    monkeypatch.setenv("CEREBRUM_INDEX_PATH", str(state_dir / "index.sqlite3"))
    monkeypatch.setenv("CEREBRUM_AUTH_DB_PATH", str(state_dir / "auth.sqlite3"))
    get_settings.cache_clear()
    yield state_dir
    get_settings.cache_clear()


@pytest.fixture
def read_only_client(read_only_env: Path, client: TestClient) -> TestClient:
    """`client` on a read-only vault. `read_only_env` is listed first so
    its variables are set before `client` builds the app."""
    del read_only_env
    return client


@pytest.fixture
def authenticated_read_only_client(read_only_client: TestClient) -> TestClient:
    """`authenticated_client` on a read-only vault: signing in writes only
    the accounts database, which lives outside the vault."""
    token = issue_test_access_token(read_only_client)
    read_only_client.headers.update({"Authorization": f"Bearer {token}"})
    return read_only_client


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


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProvider]:
    """A fresh in-process OpenID Connect provider (`tests/oidc_fake.py`):
    the OIDC settings point at it, and every request `accounts/oidc.py`
    makes is routed to it instead of the network. Request it before
    `client` so the app is built with the provider configured."""
    configure_oidc_env(monkeypatch)
    provider = FakeProvider()
    use_transport(provider.transport)
    yield provider
    use_transport(None)
    get_settings.cache_clear()
