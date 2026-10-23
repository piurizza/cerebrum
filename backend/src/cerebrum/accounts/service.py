from __future__ import annotations

import contextlib
import secrets
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import anyio
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
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

# Stored in `users.password_hash` (which stays NOT NULL) for an account
# created through the OpenID Connect provider, which has no password. Not
# an Argon2 hash, and no `PasswordHasher.hash()` output can ever equal it,
# so no typed password matches it -- `_verify_password_or_dummy` refuses
# it outright rather than relying on Argon2 to reject it.
NO_PASSWORD_HASH = "!no-password"


def has_password(password_hash: str) -> bool:
    """Whether an account has a password at all, i.e. isn't one created
    through the provider. Not whether password login is open to it -- that
    also depends on `auth_password_login` and the account's links."""
    return password_hash != NO_PASSWORD_HASH


def other_admin_has_password(auth_db: sqlite3.Connection, user_id: int) -> bool:
    """Whether an active admin other than `user_id` has a password. Admins
    can always sign in with theirs (break-glass for a provider outage), so
    the last such admin is never demoted by the provider's admin group nor
    deactivated. The caller holds `auth_write_lock`."""
    row = auth_db.execute(
        """
        SELECT 1 FROM users
        WHERE is_admin = 1 AND is_active = 1 AND id != ? AND password_hash != ?
        LIMIT 1
        """,
        (user_id, NO_PASSWORD_HASH),
    ).fetchone()
    return row is not None


class InvalidCredentialError(Exception):
    """Wrong username/password, or a deactivated account, at login. One
    class covers both causes so the API layer cannot leak which one
    occurred. Also raised by `change_password()` for a wrong current
    password or a locked/inactive account."""


class InvalidTokenError(Exception):
    """A registration token (invite or setup) that doesn't exist, is
    expired, or is already consumed; also used for an unknown/expired
    refresh token and an invalid/already-consumed invite at
    generation-adjacent checks."""


class UsernameTakenError(Exception):
    """Registration with an existing username."""


class PasswordRegistrationClosedError(Exception):
    """Registration with an invite while `AUTH_PASSWORD_LOGIN` is off: new
    people sign up through the provider instead (KTD11). The setup-token
    bootstrap of the first account is never refused."""


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


def is_first_account(auth_db: sqlite3.Connection) -> bool:
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


def find_valid_invite_token_hash(auth_db: sqlite3.Connection, token: str) -> str | None:
    """The hash of `token` when it names an invite that is unexpired and
    not yet consumed, else None. Also used by the OpenID Connect sign-up
    (`api/oidc.py`), which checks the invite before sending the browser to
    the provider and consumes it, by hash, in the callback."""
    token_hash = hash_token(token)
    now = datetime.now(UTC).isoformat()
    # Locked for the same reason as `is_first_account` above.
    with auth_write_lock:
        valid = invite_hash_is_valid(auth_db, token_hash, now)
    return token_hash if valid else None


def invite_hash_is_valid(
    auth_db: sqlite3.Connection, token_hash: str, now: str
) -> bool:
    """Whether `token_hash` names an invite that is unexpired at `now` and
    not yet consumed. Lock-free: the caller holds `auth_write_lock` -- the
    OpenID Connect sign-up re-checks the invite inside the transaction that
    consumes it (`accounts/oidc_accounts.py`)."""
    row = auth_db.execute(
        """
        SELECT 1 FROM invites
        WHERE token_hash = ? AND consumed_at IS NULL AND expires_at > ?
        """,
        (token_hash, now),
    ).fetchone()
    return row is not None


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

    With `AUTH_PASSWORD_LOGIN` off, every registration but the bootstrap
    raises `PasswordRegistrationClosedError`, before the invite is even
    looked at.
    """
    settings = get_settings()
    bootstrapping = is_first_account(auth_db)

    invite_token_hash: str | None = None
    if bootstrapping:
        if not secrets.compare_digest(
            token.encode("utf-8"),
            settings.auth_setup_token.get_secret_value().encode("utf-8"),
        ):
            raise InvalidTokenError("invalid setup token")
    elif not settings.auth_password_login:
        raise PasswordRegistrationClosedError("password registration is turned off")
    else:
        invite_token_hash = find_valid_invite_token_hash(auth_db, token)
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
        is_admin=bootstrapping,
        is_active=True,
        created_at=created_at,
    )


def _verify_password_or_dummy(password_hash: str, password: str) -> bool:
    """Run one Argon2 verify, off the event loop via the caller's
    `anyio.to_thread.run_sync`. Used for both the real hash (an existing
    user) and `_DUMMY_PASSWORD_HASH` (no such user) so both paths pay the
    identical CPU cost -- see `_DUMMY_PASSWORD_HASH`'s docstring.

    A password-less account (`NO_PASSWORD_HASH`) and a stored value Argon2
    can't even parse are both a mismatch, after verifying against the dummy
    hash instead: neither may answer faster than a wrong password does, and
    a corrupt row must fail login like one rather than surface as a 500."""
    if has_password(password_hash):
        try:
            _password_hasher.verify(password_hash, password)
            return True
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError, UnicodeEncodeError):
            # Corrupt or truncated hash; `VerificationError` is argon2's
            # "Decoding failed" for a hash that looks Argon2 but isn't.
            pass
    with contextlib.suppress(VerifyMismatchError):
        _password_hasher.verify(_DUMMY_PASSWORD_HASH, password)
    return False


def _record_failed_login(auth_db: sqlite3.Connection, user_id: int) -> None:
    """Increment `failed_login_attempts` atomically -- `failed_login_attempts
    = failed_login_attempts + 1` inside the UPDATE itself, not a value read
    by the caller before this call and written back here. `authenticate()`
    reads the row, then awaits an Argon2 verify (tens-hundreds of ms) before
    ever calling this; a value captured before that await is stale by the
    time it would be written, so concurrent failed attempts against the same
    account would each overwrite the same pre-verify count instead of
    accumulating -- silently defeating the lockout threshold under exactly
    the concurrent-guessing pattern it exists to catch. Deriving
    `locked_until` from this statement's own `RETURNING` value, in the same
    locked block, is what keeps the whole read-increment-decide sequence
    atomic against that race.
    """
    with auth_write_lock, auth_db:
        row = auth_db.execute(
            """
            UPDATE users SET failed_login_attempts = failed_login_attempts + 1
            WHERE id = ?
            RETURNING failed_login_attempts
            """,
            (user_id,),
        ).fetchone()
        new_count = row["failed_login_attempts"]
        if new_count >= _FAILED_LOGIN_LOCKOUT_THRESHOLD:
            locked_until = (datetime.now(UTC) + _LOCKOUT_DURATION).isoformat()
            auth_db.execute(
                "UPDATE users SET locked_until = ? WHERE id = ?",
                (locked_until, user_id),
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
    username: str,
    password: str,
    auth_db: sqlite3.Connection,
    *,
    password_login_open: Callable[[User], bool] | None = None,
) -> User:
    """Verify a username/password login, returning the `User` on success.

    Raises `InvalidCredentialError` for every failure case -- wrong
    username, wrong password, a deactivated account, or a currently
    locked-out account -- deliberately one exception type for all four, so
    the API layer has no distinguishable cause to leak by mapping them
    differently (see `InvalidCredentialError`'s own docstring).

    `password_login_open`, when given, is asked whether password login is
    open to the account (KTD11). A refusal is the same
    `InvalidCredentialError`, and is decided only once the password has
    been verified, so it reveals nothing about the account to someone who
    doesn't know the password. It is not a successful login, so it leaves
    the lockout count alone; nor a failed one, since the password was
    right.
    """
    # Locked for the same reason as `is_first_account`/
    # `find_valid_invite_token_hash` above -- a read against the shared
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
        # Locked out. Still pays the dummy-hash Argon2 cost -- skipping it
        # here would make a locked-out account's response measurably
        # faster than a wrong-password response for an unlocked account,
        # reopening by timing exactly the account-existence signal the
        # nonexistent-username dummy-hash path above was built to close
        # (a locked account is, definitionally, one that exists).
        await anyio.to_thread.run_sync(
            _verify_password_or_dummy, _DUMMY_PASSWORD_HASH, password
        )
        raise InvalidCredentialError("account temporarily locked")

    password_ok = await anyio.to_thread.run_sync(
        _verify_password_or_dummy, row["password_hash"], password
    )

    if not password_ok or not row["is_active"]:
        _record_failed_login(auth_db, row["id"])
        raise InvalidCredentialError("invalid username or password")

    user = User(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )
    if password_login_open is not None and not password_login_open(user):
        raise InvalidCredentialError("password login is closed to this account")

    _record_successful_login(auth_db, row["id"])
    return user


async def change_password(
    user_id: int,
    current_password: str,
    new_password: str,
    auth_db: sqlite3.Connection,
) -> User:
    """Replace an authenticated account's password, after re-checking the
    current one.

    The current password is re-checked by `confirm_current_password()`, so
    a wrong one counts toward the login lockout, and a locked account is
    refused.

    On success, every refresh token the account holds is revoked in the
    same transaction as the hash update. Rotating a password is most often a
    response to it having leaked, and leaving existing sessions alive would
    keep anyone who logged in with the old password signed in. The route
    issues the caller a fresh session afterwards so they stay logged in on
    the device they changed it from. Personal API tokens are deliberately
    left alone: they're separate, individually revocable credentials (often
    wired into MCP clients), listed in Settings for review.

    Raises `WeakPasswordError` if `new_password` is too short, and
    `InvalidCredentialError` for a wrong current password, a locked-out
    account, or an account that no longer exists or is inactive.
    """
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be at least {_MIN_PASSWORD_LENGTH} characters"
        )

    user = await confirm_current_password(user_id, current_password, auth_db)

    new_hash = await anyio.to_thread.run_sync(_password_hasher.hash, new_password)
    now_iso = datetime.now(UTC).isoformat()
    with auth_write_lock, auth_db:
        auth_db.execute(
            """
            UPDATE users
            SET password_hash = ?, failed_login_attempts = 0, locked_until = NULL
            WHERE id = ?
            """,
            (new_hash, user_id),
        )
        auth_db.execute(
            """
            UPDATE refresh_tokens SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (now_iso, user_id),
        )

    return user


async def confirm_current_password(
    user_id: int, password: str, auth_db: sqlite3.Connection
) -> User:
    """Re-check a signed-in account's password before a sensitive change
    (changing it, linking a sign-in provider), returning the account.

    The caller is already authenticated, so this is not a login: there is
    no username to enumerate and no timing-parity work to do. But a wrong
    password still counts toward the same lockout `authenticate()`
    enforces, and a locked account is refused here too -- otherwise a
    stolen access token could brute-force the password through these
    endpoints without ever tripping the lockout login has. A success does
    not reset the failure count: only a real login or a password change
    does.

    Raises `InvalidCredentialError` for a wrong password, a locked-out
    account, or an account that no longer exists or is inactive.
    """
    with auth_write_lock:
        row = auth_db.execute(
            """
            SELECT id, username, password_hash, is_admin, is_active, created_at,
                   locked_until
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    if row is None or not row["is_active"]:
        raise InvalidCredentialError("account not found or inactive")

    locked_until = row["locked_until"]
    if locked_until is not None and datetime.fromisoformat(locked_until) > datetime.now(
        UTC
    ):
        raise InvalidCredentialError("account temporarily locked")

    password_ok = await anyio.to_thread.run_sync(
        _verify_password_or_dummy, row["password_hash"], password
    )
    if not password_ok:
        _record_failed_login(auth_db, user_id)
        raise InvalidCredentialError("current password is incorrect")

    return User(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )
