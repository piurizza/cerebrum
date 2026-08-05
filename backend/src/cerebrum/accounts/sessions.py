from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

import jwt

from cerebrum.accounts.service import InvalidTokenError, TokenReuseDetectedError, User
from cerebrum.auth_db import auth_write_lock, hash_token
from cerebrum.settings import get_settings


def _mint_access_token(user_id: int, now: datetime) -> str:
    """Shared by `issue_session()` and `refresh_session()` -- both need
    the exact same "JWT for this user id, expiring at the configured TTL"
    logic, and only the caller's notion of `user_id`/`now` differs.

    Subject is the user id only -- no `is_admin` claim. A later unit's
    `require_admin` does its own fresh DB lookup for authorization,
    deliberately not trusting a JWT claim that can't be invalidated
    before its own expiry.
    """
    settings = get_settings()
    return jwt.encode(
        {
            "sub": str(user_id),
            "exp": now + timedelta(minutes=settings.auth_access_token_ttl_minutes),
        },
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def issue_session(user: User, auth_db: sqlite3.Connection) -> tuple[str, str]:
    """Mint a new browser session for `user`: a short-lived JWT access
    token plus a DB-backed, single-use-until-rotated opaque refresh token
    (KTD3). Split from `service.py` into its own sibling module -- session
    issuance is its own concern from account creation/authentication,
    mirroring `mcp/notes_tools.py` vs `mcp/graph_tools.py`'s existing
    split-by-sub-domain convention in this codebase.

    Returns `(access_token, refresh_token)`. The refresh token's plaintext
    is returned exactly once, here -- only its SHA-256 hash is ever
    persisted, the same fast-hash-at-rest treatment personal API tokens
    get (KTD4): unlike a password, it's already a high-entropy random
    value, so slow/memory-hard hashing would add latency with no security
    benefit.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    access_token = _mint_access_token(user.id, now)

    refresh_token = secrets.token_urlsafe(32)
    token_hash = hash_token(refresh_token)
    family_id = secrets.token_hex(16)
    expires_at = now + timedelta(days=settings.auth_refresh_token_ttl_days)

    # Single-row insert, but still taken under `auth_write_lock` per this
    # codebase's established idiom for any write against `auth_db` (see
    # `index/indexer.py`), not just multi-statement ones.
    with auth_write_lock, auth_db:
        auth_db.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (user.id, token_hash, family_id, expires_at.isoformat()),
        )

    return access_token, refresh_token


def _insert_rotated_refresh_token(
    auth_db: sqlite3.Connection, user_id: int, family_id: str, now: datetime
) -> str:
    """Insert a rotation's replacement row -- same shape as the persisted
    half of `issue_session()`, except `family_id` is carried over from the
    token being rotated rather than freshly minted, which is what makes
    it a rotation instead of a brand-new login. Returns the new refresh
    token's plaintext (only its hash is persisted, same as
    `issue_session()`)."""
    settings = get_settings()
    new_refresh_token = secrets.token_urlsafe(32)
    new_token_hash = hash_token(new_refresh_token)
    expires_at = now + timedelta(days=settings.auth_refresh_token_ttl_days)
    auth_db.execute(
        """
        INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, new_token_hash, family_id, expires_at.isoformat()),
    )
    return new_refresh_token


def refresh_session(refresh_token: str, auth_db: sqlite3.Connection) -> tuple[str, str]:
    """Rotate a refresh token: consume `refresh_token`, mint and persist
    its replacement (same `family_id`, new value), and issue a fresh JWT
    access token for the token's owner.

    Rotation is one atomic conditional `UPDATE`, not a read-then-write --
    two threads racing the same `refresh_token` must not both observe it
    as valid and each mint an independent replacement (a real sibling-token
    fork, indistinguishable from theft after the fact). Only one `UPDATE`
    can flip a given row's `revoked_at` from NULL, so at most one caller
    ever proceeds to rotation; the other lands in the reuse-detection path
    below in the same call, not a later one.

    Raises `InvalidTokenError` if `refresh_token` is unknown or expired,
    or `TokenReuseDetectedError` if it was already rotated/consumed by an
    earlier call -- in the latter case, every other still-valid token in
    the same `family_id` is revoked too (KTD3's theft response: reusing a
    rotated-away token means *some* holder of that family is an attacker,
    so the whole lineage is burned rather than guessing which branch was
    legitimate).
    """
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    token_hash = hash_token(refresh_token)

    # One locked block spans the atomic UPDATE attempt and, when it misses,
    # the diagnostic follow-up SELECT/UPDATE that distinguishes reuse from
    # an unknown/expired token -- per `auth_db.py`'s `auth_write_lock`
    # docstring, this whole sequence must run as one uninterrupted unit
    # against the shared connection, not as separate locked/unlocked steps
    # a second thread could interleave between.
    #
    # Deliberately never `raise` from inside `with auth_write_lock, auth_db:`
    # below: `sqlite3.Connection`'s context manager rolls the transaction
    # back, not commits it, when an exception propagates out of the block --
    # so the reuse branch's family-revocation `UPDATE` records its outcome
    # in a local flag and raises only after the block has exited (and
    # committed) normally.
    reuse_detected = False
    with auth_write_lock, auth_db:
        # RETURNING avoids a separate follow-up SELECT for the row this
        # same statement just updated -- both the update and the read of
        # its result happen in one round trip against the connection.
        rotate_cursor = auth_db.execute(
            """
            UPDATE refresh_tokens SET revoked_at = ?
            WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?
            RETURNING user_id, family_id
            """,
            (now_iso, token_hash, now_iso),
        )
        owner_row = rotate_cursor.fetchone()

        if owner_row is not None:
            new_refresh_token = _insert_rotated_refresh_token(
                auth_db, owner_row["user_id"], owner_row["family_id"], now
            )
            return _mint_access_token(owner_row["user_id"], now), new_refresh_token

        # The atomic UPDATE didn't touch a row -- either this token_hash
        # doesn't exist, is expired, or was already rotated away. One more
        # SELECT (no WHERE on revoked_at/expires_at) tells which.
        existing_row = auth_db.execute(
            "SELECT family_id, revoked_at FROM refresh_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()

        if existing_row is not None and existing_row["revoked_at"] is not None:
            # Already consumed by an earlier rotation -- this presentation
            # is a reuse of a dead token. Burn the whole family: every
            # token descended from the same original login, not just this
            # one.
            auth_db.execute(
                """
                UPDATE refresh_tokens SET revoked_at = ?
                WHERE family_id = ? AND revoked_at IS NULL
                """,
                (now_iso, existing_row["family_id"]),
            )
            reuse_detected = True

    if reuse_detected:
        raise TokenReuseDetectedError("refresh token already used")

    raise InvalidTokenError("unknown or expired refresh token")
