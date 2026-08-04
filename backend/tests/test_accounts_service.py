from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

from cerebrum.accounts.service import (
    InvalidCredentialError,
    InvalidTokenError,
    User,
    UsernameTakenError,
    WeakPasswordError,
    authenticate,
    register_account,
)
from cerebrum.settings import get_settings

VALID_PASSWORD = "correct horse battery staple"


def _setup_token() -> str:
    return get_settings().auth_setup_token.get_secret_value()


def _user_count(auth_db: sqlite3.Connection) -> int:
    (count,) = auth_db.execute("SELECT COUNT(*) FROM users").fetchone()
    return int(count)


def _bootstrap_admin(auth_db: sqlite3.Connection, username: str = "admin") -> User:
    return asyncio.run(
        register_account(username, VALID_PASSWORD, _setup_token(), auth_db)
    )


def _insert_invite(
    auth_db: sqlite3.Connection,
    token: str,
    created_by: int,
    *,
    expires_at: datetime | None = None,
    consumed: bool = False,
) -> None:
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=1)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with auth_db:
        auth_db.execute(
            """
            INSERT INTO invites
                (token_hash, created_by, expires_at, consumed_at, consumed_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                token_hash,
                created_by,
                expires_at.isoformat(),
                datetime.now(UTC).isoformat() if consumed else None,
                created_by if consumed else None,
            ),
        )


def _run_register_in_thread(
    credentials: tuple[str, str, str],
    auth_db: sqlite3.Connection,
    outcomes: list[tuple[str, object]],
    index: int,
) -> None:
    username, password, token = credentials
    try:
        user = asyncio.run(register_account(username, password, token, auth_db))
        outcomes[index] = ("ok", user)
    except Exception as exc:  # noqa: BLE001 -- captured for the test to inspect
        outcomes[index] = ("error", exc)


def test_first_registration_with_correct_setup_token_creates_admin(
    auth_db: sqlite3.Connection,
) -> None:
    user = _bootstrap_admin(auth_db, "alice")

    assert user.is_admin is True
    row = auth_db.execute(
        "SELECT is_admin FROM users WHERE username = 'alice'"
    ).fetchone()
    assert row["is_admin"] == 1


def test_first_registration_with_incorrect_setup_token_fails(
    auth_db: sqlite3.Connection,
) -> None:
    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("alice", VALID_PASSWORD, "wrong-token", auth_db))

    assert _user_count(auth_db) == 0


def test_concurrent_first_registration_only_one_succeeds(
    auth_db: sqlite3.Connection,
) -> None:
    outcomes: list[tuple[str, object]] = [("", None), ("", None)]
    threads = [
        threading.Thread(
            target=_run_register_in_thread,
            args=(("alice", VALID_PASSWORD, _setup_token()), auth_db, outcomes, 0),
        ),
        threading.Thread(
            target=_run_register_in_thread,
            args=(("bob", VALID_PASSWORD, _setup_token()), auth_db, outcomes, 1),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    statuses = [outcome[0] for outcome in outcomes]
    assert statuses.count("ok") == 1
    assert statuses.count("error") == 1
    (_, error) = next(outcome for outcome in outcomes if outcome[0] == "error")
    assert isinstance(error, InvalidTokenError)
    assert _user_count(auth_db) == 1

    (winner,) = [outcome[1] for outcome in outcomes if outcome[0] == "ok"]
    assert isinstance(winner, User)
    assert winner.is_admin is True


def test_setup_token_after_account_exists_fails(auth_db: sqlite3.Connection) -> None:
    _bootstrap_admin(auth_db)

    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("bob", VALID_PASSWORD, _setup_token(), auth_db))

    assert _user_count(auth_db) == 1


def test_registration_with_no_invite_token_fails(auth_db: sqlite3.Connection) -> None:
    _bootstrap_admin(auth_db)

    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("bob", VALID_PASSWORD, "", auth_db))

    assert _user_count(auth_db) == 1


def test_registration_with_unknown_invite_token_fails(
    auth_db: sqlite3.Connection,
) -> None:
    _bootstrap_admin(auth_db)

    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("bob", VALID_PASSWORD, "no-such-token", auth_db))

    assert _user_count(auth_db) == 1


def test_registration_with_expired_invite_fails(auth_db: sqlite3.Connection) -> None:
    admin = _bootstrap_admin(auth_db)
    _insert_invite(
        auth_db,
        "expired-token",
        admin.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("bob", VALID_PASSWORD, "expired-token", auth_db))

    assert _user_count(auth_db) == 1


def test_registration_with_already_consumed_invite_fails(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)
    _insert_invite(auth_db, "used-token", admin.id, consumed=True)

    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("bob", VALID_PASSWORD, "used-token", auth_db))

    assert _user_count(auth_db) == 1


def test_concurrent_registration_with_same_invite_only_one_succeeds(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)
    _insert_invite(auth_db, "shared-token", admin.id)

    outcomes: list[tuple[str, object]] = [("", None), ("", None)]
    threads = [
        threading.Thread(
            target=_run_register_in_thread,
            args=(("carol", VALID_PASSWORD, "shared-token"), auth_db, outcomes, 0),
        ),
        threading.Thread(
            target=_run_register_in_thread,
            args=(("dave", VALID_PASSWORD, "shared-token"), auth_db, outcomes, 1),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    statuses = [outcome[0] for outcome in outcomes]
    assert statuses.count("ok") == 1
    assert statuses.count("error") == 1
    (_, error) = next(outcome for outcome in outcomes if outcome[0] == "error")
    assert isinstance(error, InvalidTokenError)
    # admin + exactly one of carol/dave
    assert _user_count(auth_db) == 2


def test_invalid_token_with_taken_username_reports_invalid_token(
    auth_db: sqlite3.Connection,
) -> None:
    _bootstrap_admin(auth_db, "alice")

    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("alice", VALID_PASSWORD, "no-such-token", auth_db))


def test_valid_token_with_taken_username_fails_with_username_taken(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db, "alice")
    _insert_invite(auth_db, "invite-token", admin.id)

    with pytest.raises(UsernameTakenError):
        asyncio.run(register_account("alice", VALID_PASSWORD, "invite-token", auth_db))


def test_registration_with_short_password_fails(auth_db: sqlite3.Connection) -> None:
    with pytest.raises(WeakPasswordError):
        asyncio.run(register_account("alice", "short1pw", _setup_token(), auth_db))

    assert _user_count(auth_db) == 0


def test_authenticate_with_correct_credentials_returns_user(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db, "alice")

    user = asyncio.run(authenticate("alice", VALID_PASSWORD, auth_db))

    assert user.id == admin.id
    assert user.username == "alice"


def test_authenticate_with_wrong_password_fails(auth_db: sqlite3.Connection) -> None:
    _bootstrap_admin(auth_db, "alice")

    with pytest.raises(InvalidCredentialError):
        asyncio.run(authenticate("alice", "totally wrong password", auth_db))


def test_authenticate_with_nonexistent_username_fails(
    auth_db: sqlite3.Connection,
) -> None:
    with pytest.raises(InvalidCredentialError):
        asyncio.run(authenticate("no-such-user", VALID_PASSWORD, auth_db))


def test_authenticate_with_deactivated_account_fails(
    auth_db: sqlite3.Connection,
) -> None:
    _bootstrap_admin(auth_db, "alice")
    with auth_db:
        auth_db.execute("UPDATE users SET is_active = 0 WHERE username = 'alice'")

    with pytest.raises(InvalidCredentialError):
        asyncio.run(authenticate("alice", VALID_PASSWORD, auth_db))


def test_authenticate_locks_account_after_five_failed_attempts(
    auth_db: sqlite3.Connection,
) -> None:
    _bootstrap_admin(auth_db, "alice")

    for _ in range(5):
        with pytest.raises(InvalidCredentialError):
            asyncio.run(authenticate("alice", "wrong password", auth_db))

    # A sixth attempt, even with the correct password, still fails while
    # `locked_until` is in the future.
    with pytest.raises(InvalidCredentialError):
        asyncio.run(authenticate("alice", VALID_PASSWORD, auth_db))

    row = auth_db.execute(
        "SELECT locked_until FROM users WHERE username = 'alice'"
    ).fetchone()
    assert row["locked_until"] is not None


def test_authenticate_succeeds_after_lockout_cleared_and_resets_attempts(
    auth_db: sqlite3.Connection,
) -> None:
    _bootstrap_admin(auth_db, "alice")

    for _ in range(5):
        with pytest.raises(InvalidCredentialError):
            asyncio.run(authenticate("alice", "wrong password", auth_db))

    with auth_db:
        auth_db.execute("UPDATE users SET locked_until = NULL WHERE username = 'alice'")

    user = asyncio.run(authenticate("alice", VALID_PASSWORD, auth_db))

    assert user.username == "alice"
    row = auth_db.execute(
        "SELECT failed_login_attempts, locked_until FROM users WHERE username = 'alice'"
    ).fetchone()
    assert row["failed_login_attempts"] == 0
    assert row["locked_until"] is None


def test_authenticate_lockout_for_one_account_does_not_affect_another(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db, "alice")
    _insert_invite(auth_db, "invite-token", admin.id)
    asyncio.run(register_account("bob", VALID_PASSWORD, "invite-token", auth_db))

    for _ in range(5):
        with pytest.raises(InvalidCredentialError):
            asyncio.run(authenticate("alice", "wrong password", auth_db))

    with pytest.raises(InvalidCredentialError):
        asyncio.run(authenticate("alice", VALID_PASSWORD, auth_db))

    user = asyncio.run(authenticate("bob", VALID_PASSWORD, auth_db))
    assert user.username == "bob"
