from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import cast

import anyio
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from pydantic import BaseModel

from cerebrum.auth_db import auth_write_lock, hash_token
from cerebrum.settings import get_settings

# Below this, a compromised/guessed password is cheap to brute-force even
# behind Argon2 hashing; this is a floor, not a full strength policy.
_MIN_PASSWORD_LENGTH = 12

# Module-level singleton (like `write_lock`/`auth_write_lock` in the db
# modules): argon2-cffi's PasswordHasher is stateless configuration, safe
# to share across threads/requests, and constructing it fresh per call
# would just repeat the same default-parameter work every time.
_password_hasher = PasswordHasher()

# U3 (login throttling): a coarse per-account lockout appropriate for R8's
# small trusted-household threat model, not a distributed rate limiter.
_FAILED_LOGIN_LOCKOUT_THRESHOLD = 5
_LOCKOUT_DURATION = timedelta(minutes=15)

# A real Argon2 hash of a fixed, never-used password, computed once at
# import time. `authenticate()` verifies against this for a username that
# doesn't exist at all, so a nonexistent-username response pays the same
# Argon2 cost a wrong-password response does -- otherwise the two cases
# would be distinguishable by response latency alone, letting an attacker
# enumerate valid usernames against `/api/auth/login` despite the
# identical error message and status code.
_DUMMY_PASSWORD_HASH = _password_hasher.hash("dummy-password-for-timing-parity")


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
    # Locked even though it's a single read: sqlite3's Connection object is
    # not safe for concurrent statement execution from multiple threads --
    # an unlocked read here can race a concurrent thread's locked write
    # block on this same shared connection and surface as a raw
    # `sqlite3.InterfaceError`, not a clean application-level exception
    # (reproduced directly: two threads racing register_account() with one
    # side reading here while the other held the lock mid-write). Every
    # statement against `auth_db`, not just multi-statement writes, must
    # take this lock -- see `auth_db.py`'s `auth_write_lock` docstring.
    with auth_write_lock:
        return auth_db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None


def _find_valid_invite_token_hash(
    auth_db: sqlite3.Connection, token: str
) -> str | None:
    token_hash = hash_token(token)
    now = datetime.now(UTC).isoformat()
    # Locked for the same reason as `_is_first_account` above.
    with auth_write_lock:
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


def _verify_password_or_dummy(password_hash: str, password: str) -> bool:
    """Run one Argon2 verify, off the event loop via the caller's
    `anyio.to_thread.run_sync`. Used for both the real hash (an existing
    user) and `_DUMMY_PASSWORD_HASH` (no such user) so both paths pay the
    identical CPU cost -- see `_DUMMY_PASSWORD_HASH`'s docstring."""
    try:
        _password_hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


def _record_failed_login(
    auth_db: sqlite3.Connection, user_id: int, failed_attempts: int
) -> None:
    new_count = failed_attempts + 1
    locked_until = None
    if new_count >= _FAILED_LOGIN_LOCKOUT_THRESHOLD:
        locked_until = (datetime.now(UTC) + _LOCKOUT_DURATION).isoformat()
    with auth_write_lock, auth_db:
        auth_db.execute(
            "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?",
            (new_count, locked_until, user_id),
        )


def _record_successful_login(auth_db: sqlite3.Connection, user_id: int) -> None:
    with auth_write_lock, auth_db:
        auth_db.execute(
            """
            UPDATE users SET failed_login_attempts = 0, locked_until = NULL
            WHERE id = ?
            """,
            (user_id,),
        )


async def authenticate(
    username: str, password: str, auth_db: sqlite3.Connection
) -> User:
    """Verify a username/password login, returning the `User` on success.

    Raises `InvalidCredentialError` for every failure case -- wrong
    username, wrong password, a deactivated account, or a currently
    locked-out account -- deliberately one exception type for all four, so
    the API layer has no distinguishable cause to leak by mapping them
    differently (see `InvalidCredentialError`'s own docstring).
    """
    # Locked for the same reason as `_is_first_account`/
    # `_find_valid_invite_token_hash` above -- a read against the shared
    # `auth_db` connection is not safe to run unlocked while another thread
    # may be mid-write against it.
    with auth_write_lock:
        row = auth_db.execute(
            """
            SELECT id, username, password_hash, is_admin, is_active, created_at,
                   failed_login_attempts, locked_until
            FROM users WHERE username = ?
            """,
            (username,),
        ).fetchone()

    if row is None:
        # Timing parity: pay the same Argon2 cost a real lookup would, so
        # this branch isn't distinguishable from a wrong-password response
        # by latency alone.
        await anyio.to_thread.run_sync(
            _verify_password_or_dummy, _DUMMY_PASSWORD_HASH, password
        )
        raise InvalidCredentialError("invalid username or password")

    now = datetime.now(UTC)
    locked_until = row["locked_until"]
    if locked_until is not None and datetime.fromisoformat(locked_until) > now:
        # Locked out -- reject without paying the Argon2 cost at all; a
        # locked account shouldn't get a hash-verify attempt on every try.
        raise InvalidCredentialError("account temporarily locked")

    password_ok = await anyio.to_thread.run_sync(
        _verify_password_or_dummy, row["password_hash"], password
    )

    if not password_ok or not row["is_active"]:
        _record_failed_login(auth_db, row["id"], row["failed_login_attempts"])
        raise InvalidCredentialError("invalid username or password")

    _record_successful_login(auth_db, row["id"])

    return User(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )
