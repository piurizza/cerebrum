from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import jwt
import pytest

from cerebrum.accounts.service import (
    InvalidTokenError,
    TokenReuseDetectedError,
    User,
    register_account,
)
from cerebrum.accounts.sessions import issue_session, refresh_session
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


def _insert_expired_refresh_token(
    auth_db: sqlite3.Connection, user_id: int, token: str
) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(UTC) - timedelta(days=1)
    with auth_db:
        auth_db.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at)
            VALUES (?, ?, 'family-1', ?)
            """,
            (user_id, token_hash, expires_at.isoformat()),
        )


def test_refresh_session_with_valid_token_returns_new_access_and_refresh_tokens(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)
    _, refresh_token = issue_session(user, auth_db)

    new_access_token, new_refresh_token = refresh_session(refresh_token, auth_db)

    settings = get_settings()
    payload = jwt.decode(
        new_access_token,
        settings.auth_jwt_secret.get_secret_value(),
        algorithms=["HS256"],
    )
    assert payload["sub"] == str(user.id)
    assert new_refresh_token != refresh_token


def test_refresh_session_rotation_persists_new_token_under_same_family(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)
    _, refresh_token = issue_session(user, auth_db)
    original_row = auth_db.execute("SELECT family_id FROM refresh_tokens").fetchone()

    _, new_refresh_token = refresh_session(refresh_token, auth_db)

    new_token_hash = hashlib.sha256(new_refresh_token.encode("utf-8")).hexdigest()
    new_row = auth_db.execute(
        """
        SELECT user_id, family_id, revoked_at FROM refresh_tokens
        WHERE token_hash = ?
        """,
        (new_token_hash,),
    ).fetchone()
    assert new_row is not None
    assert new_row["user_id"] == user.id
    assert new_row["family_id"] == original_row["family_id"]
    assert new_row["revoked_at"] is None


def test_refresh_session_reusing_the_old_token_after_rotation_fails(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)
    _, refresh_token = issue_session(user, auth_db)

    refresh_session(refresh_token, auth_db)

    with pytest.raises(TokenReuseDetectedError):
        refresh_session(refresh_token, auth_db)


def test_refresh_session_reuse_revokes_the_entire_family_including_the_rotated_token(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)
    _, refresh_token = issue_session(user, auth_db)

    _, rotated_refresh_token = refresh_session(refresh_token, auth_db)

    # Reusing the now-dead original token detects theft and burns every
    # still-valid token in the family -- including the one issued by the
    # legitimate rotation above.
    with pytest.raises(TokenReuseDetectedError):
        refresh_session(refresh_token, auth_db)

    with pytest.raises((InvalidTokenError, TokenReuseDetectedError)):
        refresh_session(rotated_refresh_token, auth_db)


def test_concurrent_refresh_with_the_same_token_only_one_succeeds(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)
    _, refresh_token = issue_session(user, auth_db)

    outcomes: list[tuple[str, object]] = [("", None), ("", None)]

    def _run(index: int) -> None:
        try:
            result = refresh_session(refresh_token, auth_db)
            outcomes[index] = ("ok", result)
        except Exception as exc:  # noqa: BLE001 -- captured for inspection
            outcomes[index] = ("error", exc)

    threads = [
        threading.Thread(target=_run, args=(0,)),
        threading.Thread(target=_run, args=(1,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    statuses = [outcome[0] for outcome in outcomes]
    assert statuses.count("ok") == 1
    assert statuses.count("error") == 1
    (_, error) = next(outcome for outcome in outcomes if outcome[0] == "error")
    assert isinstance(error, TokenReuseDetectedError)

    # Not two independently-issued sibling tokens: the loser's failure
    # revoked the whole family, including the winner's freshly-rotated
    # token.
    (_, winner_result) = next(outcome for outcome in outcomes if outcome[0] == "ok")
    _, winner_refresh_token = cast("tuple[str, str]", winner_result)
    with pytest.raises((InvalidTokenError, TokenReuseDetectedError)):
        refresh_session(winner_refresh_token, auth_db)


def _refresh_token_count(auth_db: sqlite3.Connection) -> int:
    row = auth_db.execute("SELECT COUNT(*) AS n FROM refresh_tokens").fetchone()
    return cast(int, row["n"])


def test_refresh_session_with_expired_token_fails_and_issues_nothing(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db)
    _insert_expired_refresh_token(auth_db, user.id, "expired-token")
    tokens_before = _refresh_token_count(auth_db)

    with pytest.raises(InvalidTokenError):
        refresh_session("expired-token", auth_db)

    assert _refresh_token_count(auth_db) == tokens_before


def test_refresh_session_with_unknown_token_fails(
    auth_db: sqlite3.Connection,
) -> None:
    _bootstrap_admin(auth_db)

    with pytest.raises(InvalidTokenError):
        refresh_session("no-such-token-ever-issued", auth_db)
