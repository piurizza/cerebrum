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
