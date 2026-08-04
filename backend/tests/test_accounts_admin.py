from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from typing import Any

import pytest

from cerebrum.accounts.admin import create_invite, deactivate_account
from cerebrum.accounts.service import (
    ForbiddenError,
    InvalidTokenError,
    User,
    register_account,
)
from cerebrum.accounts.sessions import issue_session
from cerebrum.accounts.tokens import create_api_token
from cerebrum.auth import AuthenticationError, verify_credential
from cerebrum.settings import get_settings

VALID_PASSWORD = "correct horse battery staple"


def _bootstrap_admin(auth_db: sqlite3.Connection, username: str = "admin") -> User:
    setup_token = get_settings().auth_setup_token.get_secret_value()
    return asyncio.run(register_account(username, VALID_PASSWORD, setup_token, auth_db))


def _register_via_invite(
    auth_db: sqlite3.Connection, admin: User, username: str
) -> User:
    """Registers a genuinely non-admin account through the real
    admin-generated-invite path this unit adds -- `create_invite()`
    followed by `register_account()`, rather than inserting a row
    directly (as older test files do, since invite generation didn't
    exist for them yet)."""
    token = create_invite(admin.id, auth_db)
    return asyncio.run(register_account(username, VALID_PASSWORD, token, auth_db))


class _FailAfterNCalls:
    """Wraps a real `auth_db` connection so a test can inject a failure
    partway through a multi-statement locked block, without needing to
    monkeypatch `sqlite3.Connection` itself -- that's a C extension type
    that refuses both instance-attribute assignment
    (`'sqlite3.Connection' object attribute 'execute' is read-only`) and
    class-level patching (`cannot set 'execute' attribute of immutable
    type 'sqlite3.Connection'`), so neither `monkeypatch.setattr` route
    works here.

    `execute()` is the only method overridden -- every call through this
    proxy still lands on the real connection's real transaction, so
    `__enter__`/`__exit__` forwarding to the real connection's own context
    manager still triggers a genuine SQLite rollback when an exception
    propagates out of the `with` block, exactly as it would for the real
    `sqlite3.Connection` object `deactivate_account()` is normally called
    with.
    """

    def __init__(self, real: sqlite3.Connection, fail_on_call: int) -> None:
        self._real = real
        self._fail_on_call = fail_on_call
        self._call_count = 0

    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        self._call_count += 1
        if self._call_count == self._fail_on_call:
            raise RuntimeError("simulated failure mid-cascade")
        return self._real.execute(*args, **kwargs)

    def __enter__(self) -> _FailAfterNCalls:
        self._real.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return self._real.__exit__(exc_type, exc, tb)


def test_create_invite_returns_plaintext_and_stores_only_a_hash(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)

    token = create_invite(admin.id, auth_db)

    row = auth_db.execute(
        "SELECT token_hash, created_by, consumed_at FROM invites"
    ).fetchone()
    assert row is not None
    assert row["token_hash"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert row["token_hash"] != token
    assert row["created_by"] == admin.id
    assert row["consumed_at"] is None


def test_admin_generated_invite_is_usable_exactly_once_for_registration(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)
    token = create_invite(admin.id, auth_db)

    user = asyncio.run(register_account("carol", VALID_PASSWORD, token, auth_db))
    assert user.username == "carol"
    assert user.is_admin is False

    with pytest.raises(InvalidTokenError):
        asyncio.run(register_account("dave", VALID_PASSWORD, token, auth_db))


def test_deactivate_account_revokes_session_and_api_tokens_on_next_use(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)
    target = _register_via_invite(auth_db, admin, "target")
    access_token, _ = issue_session(target, auth_db)
    api_token_1, _ = create_api_token(target.id, "phone", auth_db)
    api_token_2, _ = create_api_token(target.id, "laptop", auth_db)

    deactivate_account(admin.id, target.id, auth_db)

    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(access_token, auth_db))
    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(api_token_1, auth_db))
    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(api_token_2, auth_db))

    refresh_row = auth_db.execute(
        "SELECT revoked_at FROM refresh_tokens WHERE user_id = ?", (target.id,)
    ).fetchone()
    assert refresh_row["revoked_at"] is not None
    api_token_rows = auth_db.execute(
        "SELECT revoked_at FROM api_tokens WHERE user_id = ?", (target.id,)
    ).fetchall()
    assert len(api_token_rows) == 2
    assert all(row["revoked_at"] is not None for row in api_token_rows)


def test_deactivate_account_failure_mid_cascade_leaves_no_partial_state(
    auth_db: sqlite3.Connection,
) -> None:
    """A broken (non-atomic) implementation -- e.g. three separate
    `with auth_write_lock, auth_db:` blocks instead of one -- would have
    already committed the `users.is_active = 0` update, and possibly the
    `refresh_tokens` revocation too, by the time a failure hits the third
    statement: those earlier statements would each have been in their own
    already-committed transaction. This test fails that broken version
    (`is_active` would read back `0`, and the refresh token would already
    be revoked) and passes only for an implementation that wraps all three
    statements in one transaction, so a failure on the third rolls the
    first two back with it.
    """
    admin = _bootstrap_admin(auth_db)
    target = _register_via_invite(auth_db, admin, "target")
    issue_session(target, auth_db)
    create_api_token(target.id, "phone", auth_db)

    # Fails on the 3rd `execute()` call inside `deactivate_account` --
    # i.e. after the `users` and `refresh_tokens` UPDATEs have already run
    # (but not yet committed), right before the `api_tokens` UPDATE.
    proxy = _FailAfterNCalls(auth_db, fail_on_call=3)

    with pytest.raises(RuntimeError, match="simulated failure mid-cascade"):
        deactivate_account(admin.id, target.id, proxy)  # type: ignore[arg-type]

    user_row = auth_db.execute(
        "SELECT is_active FROM users WHERE id = ?", (target.id,)
    ).fetchone()
    assert user_row["is_active"] == 1, "users.is_active must roll back too"

    refresh_row = auth_db.execute(
        "SELECT revoked_at FROM refresh_tokens WHERE user_id = ?", (target.id,)
    ).fetchone()
    assert refresh_row["revoked_at"] is None, "refresh token revocation must roll back"

    api_token_row = auth_db.execute(
        "SELECT revoked_at FROM api_tokens WHERE user_id = ?", (target.id,)
    ).fetchone()
    assert api_token_row["revoked_at"] is None


def test_deactivating_one_account_does_not_affect_another(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)
    target = _register_via_invite(auth_db, admin, "target")
    bystander = _register_via_invite(auth_db, admin, "bystander")
    bystander_access_token, _ = issue_session(bystander, auth_db)
    bystander_api_token, _ = create_api_token(bystander.id, "phone", auth_db)

    deactivate_account(admin.id, target.id, auth_db)

    assert asyncio.run(verify_credential(bystander_access_token, auth_db)) == str(
        bystander.id
    )
    assert asyncio.run(verify_credential(bystander_api_token, auth_db)) == str(
        bystander.id
    )
    bystander_row = auth_db.execute(
        "SELECT is_active FROM users WHERE id = ?", (bystander.id,)
    ).fetchone()
    assert bystander_row["is_active"] == 1


def test_admin_cannot_deactivate_their_own_account(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)

    with pytest.raises(ForbiddenError):
        deactivate_account(admin.id, admin.id, auth_db)

    row = auth_db.execute(
        "SELECT is_active FROM users WHERE id = ?", (admin.id,)
    ).fetchone()
    assert row["is_active"] == 1


def test_deactivate_nonexistent_account_is_a_noop(
    auth_db: sqlite3.Connection,
) -> None:
    admin = _bootstrap_admin(auth_db)

    deactivate_account(admin.id, 999999, auth_db)

    row = auth_db.execute(
        "SELECT is_active FROM users WHERE id = ?", (admin.id,)
    ).fetchone()
    assert row["is_active"] == 1
