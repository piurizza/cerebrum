from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import cast

import anyio
from argon2 import PasswordHasher
from pydantic import BaseModel

from cerebrum.auth_db import auth_write_lock
from cerebrum.settings import get_settings

# Below this, a compromised/guessed password is cheap to brute-force even
# behind Argon2 hashing; this is a floor, not a full strength policy.
_MIN_PASSWORD_LENGTH = 12

# Module-level singleton (like `write_lock`/`auth_write_lock` in the db
# modules): argon2-cffi's PasswordHasher is stateless configuration, safe
# to share across threads/requests, and constructing it fresh per call
# would just repeat the same default-parameter work every time.
_password_hasher = PasswordHasher()


class InvalidCredentialError(Exception):
    """Wrong username/password, or a deactivated account, at login. One
    class covers both causes so the API layer cannot leak which one
    occurred."""


class InvalidTokenError(Exception):
    """A registration token (invite or setup) that doesn't exist, is
    expired, or is already consumed; also used for an unknown/expired
    refresh token and an invalid/already-consumed invite at
    generation-adjacent checks."""


class UsernameTakenError(Exception):
    """Registration with an existing username."""


class TokenReuseDetectedError(Exception):
    """A refresh token presented after it was already rotated away."""


class NotFoundError(Exception):
    """Resource doesn't exist for the caller's own scope (e.g. a token id
    that isn't theirs looks identical to one that doesn't exist) -> 404."""


class ForbiddenError(Exception):
    """Resource exists but the action is disallowed (e.g. non-admin
    hitting an admin-only route, or self-deactivation) -> 403."""


class WeakPasswordError(Exception):
    """Password shorter than the minimum allowed length."""


class User(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    created_at: str


def _is_first_account(auth_db: sqlite3.Connection) -> bool:
    return auth_db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None


def _find_valid_invite_token_hash(
    auth_db: sqlite3.Connection, token: str
) -> str | None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(UTC).isoformat()
    row = auth_db.execute(
        """
        SELECT token_hash FROM invites
        WHERE token_hash = ? AND consumed_at IS NULL AND expires_at > ?
        """,
        (token_hash, now),
    ).fetchone()
    return token_hash if row is not None else None


def _bootstrap_first_admin(
    auth_db: sqlite3.Connection, username: str, password_hash: str, created_at: str
) -> int:
    # WHERE NOT EXISTS makes this INSERT atomic against a second, concurrent
    # bootstrap attempt: at most one of two racing callers can observe zero
    # rows and land its insert -- the loser gets rowcount 0, not a
    # half-applied row or a duplicate admin.
    with auth_write_lock, auth_db:
        cursor = auth_db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, is_active, created_at)
            SELECT ?, ?, 1, 1, ?
            WHERE NOT EXISTS (SELECT 1 FROM users)
            """,
            (username, password_hash, created_at),
        )
        if cursor.rowcount != 1:
            raise InvalidTokenError("setup token already used to bootstrap an account")
        return cast(int, cursor.lastrowid)


def _register_with_invite(
    auth_db: sqlite3.Connection,
    username: str,
    password_hash: str,
    created_at: str,
    invite_token_hash: str,
) -> int:
    # Insert the user before consuming the invite (rather than the other
    # order) because `invites.consumed_by` is a foreign key into `users`
    # -- it can only be set to an id that already exists. Atomicity against
    # a second caller redeeming the same invite still holds: both
    # statements share one `with auth_db:` transaction, so if the
    # consumption UPDATE below loses the race (rowcount 0) and raises,
    # sqlite3 rolls back the whole block, including this INSERT -- no
    # orphaned user is left behind.
    with auth_write_lock, auth_db:
        insert_cursor = auth_db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, is_active, created_at)
            VALUES (?, ?, 0, 1, ?)
            """,
            (username, password_hash, created_at),
        )
        user_id = cast(int, insert_cursor.lastrowid)

        update_cursor = auth_db.execute(
            """
            UPDATE invites SET consumed_at = ?, consumed_by = ?
            WHERE token_hash = ? AND consumed_at IS NULL
            """,
            (created_at, user_id, invite_token_hash),
        )
        if update_cursor.rowcount != 1:
            raise InvalidTokenError("invite token already consumed")
        return user_id


async def register_account(
    username: str, password: str, token: str, auth_db: sqlite3.Connection
) -> User:
    """Create a new account, gated by a registration token.

    The very first account in an empty `users` table bootstraps via the
    server-configured setup token (`settings.auth_setup_token`) and is
    granted admin; every subsequent registration must present a valid,
    unconsumed invite instead.

    Token validity is always checked before username availability -- an
    unauthenticated caller must not be able to learn whether a username is
    taken by presenting no token, or a bad one, and comparing error
    messages (see `InvalidTokenError` vs `UsernameTakenError` below).
    """
    settings = get_settings()
    is_first_account = _is_first_account(auth_db)

    invite_token_hash: str | None = None
    if is_first_account:
        if not secrets.compare_digest(
            token.encode("utf-8"),
            settings.auth_setup_token.get_secret_value().encode("utf-8"),
        ):
            raise InvalidTokenError("invalid setup token")
    else:
        invite_token_hash = _find_valid_invite_token_hash(auth_db, token)
        if invite_token_hash is None:
            raise InvalidTokenError(
                "invalid, expired, or already-consumed invite token"
            )

    if len(password) < _MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be at least {_MIN_PASSWORD_LENGTH} characters"
        )

    # Argon2 is deliberately CPU-heavy; running it inline on the event loop
    # would block every other in-flight request for the duration of each
    # registration, so it's offloaded to a worker thread.
    password_hash = await anyio.to_thread.run_sync(_password_hasher.hash, password)
    created_at = datetime.now(UTC).isoformat()

    try:
        if invite_token_hash is not None:
            user_id = _register_with_invite(
                auth_db, username, password_hash, created_at, invite_token_hash
            )
        else:
            user_id = _bootstrap_first_admin(
                auth_db, username, password_hash, created_at
            )
    except sqlite3.IntegrityError as exc:
        # Not pre-checked with a SELECT (that would be its own race window)
        # -- the UNIQUE constraint on users.username is the sole arbiter.
        raise UsernameTakenError(username) from exc

    return User(
        id=user_id,
        username=username,
        is_admin=is_first_account,
        is_active=True,
        created_at=created_at,
    )
