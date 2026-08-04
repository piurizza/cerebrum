from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from cerebrum.accounts.service import ForbiddenError
from cerebrum.auth_db import auth_write_lock, hash_token

# How long an admin-generated invite stays redeemable. A few days is
# generous enough for the invited person to actually receive and act on
# it (this is a self-hosted, small-household deployment -- R8 -- not a
# same-second automated flow) while still bounding a leaked-but-unused
# invite's window of usefulness. Module-level constant, mirroring
# `service.py`'s `_FAILED_LOGIN_LOCKOUT_THRESHOLD`/`_LOCKOUT_DURATION`,
# rather than a magic literal inline below.
INVITE_TTL = timedelta(days=7)


def create_invite(admin_user_id: int, auth_db: sqlite3.Connection) -> str:
    """Generate a new invite, persist only its SHA-256 hash, and return the
    plaintext token exactly once -- same shape as `tokens.py`'s
    `create_api_token()`: the plaintext is never recoverable from the DB
    after this call returns.
    """
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    now = datetime.now(UTC)
    expires_at = now + INVITE_TTL

    # Single-row insert, still taken under `auth_write_lock` per this
    # codebase's established idiom for every write against `auth_db` (see
    # `auth_db.py`'s `auth_write_lock` docstring), not just multi-statement
    # ones.
    with auth_write_lock, auth_db:
        auth_db.execute(
            """
            INSERT INTO invites (token_hash, created_by, expires_at)
            VALUES (?, ?, ?)
            """,
            (token_hash, admin_user_id, expires_at.isoformat()),
        )

    return token


def deactivate_account(
    admin_user_id: int, target_user_id: int, auth_db: sqlite3.Connection
) -> None:
    """Deactivate `target_user_id` and immediately, atomically revoke every
    credential that account could otherwise keep using: its refresh-token
    sessions AND its personal API tokens.

    The self-deactivation check runs first and needs no DB access at all
    -- it's a plain id comparison -- so it's deliberately outside (before)
    the locked block below: raising `ForbiddenError` here can never leave
    partial state, unlike a failure mid-cascade would.

    The three UPDATEs that follow run inside exactly one
    `with auth_write_lock, auth_db:` block, not three separate locked
    calls, so a failure between any of them rolls the whole sequence back
    together -- an account can never end up inactive with a still-valid
    session or API token, or vice versa (deactivated in the users table
    but a mid-cascade crash leaves a token un-revoked).

    A nonexistent `target_user_id` is treated as a no-op, not an error:
    all three UPDATEs simply affect 0 rows. This is an admin-only,
    idempotent operation ("make sure this account is deactivated") where
    calling it twice, or against an id that's already gone, isn't a
    meaningfully different admin mistake from calling it once -- unlike
    `revoke_api_token()`'s `NotFoundError`, there's no per-caller
    ownership scoping here for a 404 to usefully disambiguate ("not yours"
    vs. "doesn't exist"), so the extra rowcount check isn't worth the
    complexity it would add.
    """
    if admin_user_id == target_user_id:
        raise ForbiddenError("an admin cannot deactivate their own account")

    now = datetime.now(UTC).isoformat()
    with auth_write_lock, auth_db:
        auth_db.execute(
            "UPDATE users SET is_active = 0 WHERE id = ?", (target_user_id,)
        )
        auth_db.execute(
            """
            UPDATE refresh_tokens SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (now, target_user_id),
        )
        auth_db.execute(
            """
            UPDATE api_tokens SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (now, target_user_id),
        )
