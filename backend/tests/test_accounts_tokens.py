from __future__ import annotations

import asyncio
import sqlite3

import pytest

from cerebrum.accounts.service import NotFoundError, User, register_account
from cerebrum.accounts.tokens import create_api_token, list_api_tokens, revoke_api_token
from cerebrum.settings import get_settings

VALID_PASSWORD = "correct horse battery staple"


def _register(auth_db: sqlite3.Connection, username: str) -> User:
    """Bootstraps a fresh vault's very first (admin) account via the setup
    token. A *second* distinct account, which this file also needs for its
    cross-account isolation tests, can't go through this same path --
    registration past the first account requires a real invite, which
    isn't wired up until a later unit -- so `_insert_second_user()` below
    inserts directly instead."""
    setup_token = get_settings().auth_setup_token.get_secret_value()
    return asyncio.run(register_account(username, VALID_PASSWORD, setup_token, auth_db))


def _insert_second_user(auth_db: sqlite3.Connection, username: str) -> int:
    with auth_db:
        cursor = auth_db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, is_active, created_at)
            VALUES (?, 'unused-hash', 0, 1, datetime('now'))
            """,
            (username,),
        )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def test_create_api_token_returns_plaintext_once_and_stores_only_a_hash(
    auth_db: sqlite3.Connection,
) -> None:
    user = _register(auth_db, "alice")

    token, meta = create_api_token(user.id, "laptop", auth_db)

    row = auth_db.execute(
        "SELECT token_hash, name, user_id FROM api_tokens WHERE id = ?", (meta.id,)
    ).fetchone()
    assert row is not None
    assert row["token_hash"] != token
    assert row["name"] == "laptop"
    assert row["user_id"] == user.id
    # No column anywhere on the row stores the plaintext.
    assert set(row.keys()) == {"token_hash", "name", "user_id"}


def test_create_api_token_metadata_has_no_hash_or_plaintext_field(
    auth_db: sqlite3.Connection,
) -> None:
    user = _register(auth_db, "alice")

    _, meta = create_api_token(user.id, "laptop", auth_db)

    dumped = meta.model_dump()
    assert "token" not in dumped
    assert "token_hash" not in dumped
    assert dumped["revoked"] is False
    assert dumped["last_used_at"] is None


def test_list_api_tokens_returns_only_the_calling_users_own_tokens(
    auth_db: sqlite3.Connection,
) -> None:
    alice = _register(auth_db, "alice")
    bob_id = _insert_second_user(auth_db, "bob")
    create_api_token(alice.id, "alice-token-1", auth_db)
    create_api_token(alice.id, "alice-token-2", auth_db)
    create_api_token(bob_id, "bob-token", auth_db)

    alice_tokens = list_api_tokens(alice.id, auth_db)
    bob_tokens = list_api_tokens(bob_id, auth_db)

    assert {t.name for t in alice_tokens} == {"alice-token-1", "alice-token-2"}
    assert {t.name for t in bob_tokens} == {"bob-token"}
    for meta in (*alice_tokens, *bob_tokens):
        assert not hasattr(meta, "token_hash")
        assert not hasattr(meta, "token")


def test_revoke_api_token_marks_it_revoked_in_the_listing(
    auth_db: sqlite3.Connection,
) -> None:
    alice = _register(auth_db, "alice")
    _, meta = create_api_token(alice.id, "laptop", auth_db)

    revoke_api_token(alice.id, meta.id, auth_db)

    [listed] = list_api_tokens(alice.id, auth_db)
    assert listed.revoked is True


def test_revoke_api_token_raises_not_found_for_unknown_id(
    auth_db: sqlite3.Connection,
) -> None:
    alice = _register(auth_db, "alice")

    with pytest.raises(NotFoundError):
        revoke_api_token(alice.id, 999999, auth_db)


def test_revoke_api_token_raises_not_found_for_someone_elses_token(
    auth_db: sqlite3.Connection,
) -> None:
    alice = _register(auth_db, "alice")
    bob_id = _insert_second_user(auth_db, "bob")
    _, bob_meta = create_api_token(bob_id, "bobs-token", auth_db)

    with pytest.raises(NotFoundError):
        revoke_api_token(alice.id, bob_meta.id, auth_db)

    # Bob's token is untouched by Alice's failed attempt.
    [listed] = list_api_tokens(bob_id, auth_db)
    assert listed.revoked is False
