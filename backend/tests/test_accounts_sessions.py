from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest

from cerebrum.accounts.service import User, register_account
from cerebrum.accounts.sessions import issue_session
from cerebrum.auth_db import connect
from cerebrum.settings import get_settings

VALID_PASSWORD = "correct horse battery staple"


@pytest.fixture
def auth_db(vault: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(vault / ".cerebrum" / "auth.sqlite3")
    yield conn
    conn.close()


def _bootstrap_admin(auth_db: sqlite3.Connection, username: str = "admin") -> User:
    return asyncio.run(
        register_account(
            username,
            VALID_PASSWORD,
            get_settings().auth_setup_token.get_secret_value(),
            auth_db,
        )
    )


def test_issue_session_returns_a_decodable_access_token_with_no_is_admin_claim(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)

    access_token, refresh_token = issue_session(user, auth_db)

    settings = get_settings()
    payload = jwt.decode(
        access_token, settings.auth_jwt_secret.get_secret_value(), algorithms=["HS256"]
    )
    assert payload["sub"] == str(user.id)
    assert "is_admin" not in payload
    assert isinstance(refresh_token, str)
    assert refresh_token


def test_issue_session_access_token_expires_at_configured_ttl(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)

    access_token, _ = issue_session(user, auth_db)

    settings = get_settings()
    payload = jwt.decode(
        access_token, settings.auth_jwt_secret.get_secret_value(), algorithms=["HS256"]
    )
    expected_exp = datetime.now(UTC) + timedelta(
        minutes=settings.auth_access_token_ttl_minutes
    )
    actual_exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    assert abs((actual_exp - expected_exp).total_seconds()) < 5


def test_issue_session_stores_only_the_refresh_token_hash(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)

    _, refresh_token = issue_session(user, auth_db)

    row = auth_db.execute(
        """
        SELECT token_hash, user_id, family_id, expires_at, revoked_at
        FROM refresh_tokens
        """
    ).fetchone()
    assert row is not None
    expected_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    assert row["token_hash"] == expected_hash
    assert row["user_id"] == user.id
    assert row["revoked_at"] is None
    assert row["family_id"]


def test_issue_session_refresh_token_expiry_matches_setting(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)

    issue_session(user, auth_db)

    row = auth_db.execute("SELECT expires_at FROM refresh_tokens").fetchone()
    settings = get_settings()
    expires_at = datetime.fromisoformat(row["expires_at"])
    expected = datetime.now(UTC) + timedelta(days=settings.auth_refresh_token_ttl_days)
    assert abs((expires_at - expected).total_seconds()) < 5


def test_issue_session_generates_distinct_refresh_tokens_and_families(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)

    _, refresh_token_1 = issue_session(user, auth_db)
    _, refresh_token_2 = issue_session(user, auth_db)

    assert refresh_token_1 != refresh_token_2

    rows = auth_db.execute("SELECT family_id FROM refresh_tokens").fetchall()
    assert len({row["family_id"] for row in rows}) == 2
