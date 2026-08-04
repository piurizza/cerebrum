from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel

from cerebrum.accounts.service import NotFoundError
from cerebrum.auth_db import auth_write_lock

# Cosmetic only, for log/identification purposes (e.g. spotting a leaked
# token shape in a log line) -- NOT a security boundary. The token's
# entropy comes entirely from the `secrets.token_urlsafe(32)` suffix; the
# prefix is hashed along with the rest of the string below, same as every
# other character.
_TOKEN_PREFIX = "cbm_pat_"


class ApiTokenMeta(BaseModel):
    """Token metadata safe to hand back to a caller -- deliberately never
    includes the plaintext token or its hash. `create_api_token()` returns
    the plaintext exactly once, separately from this model."""

    id: int
    name: str
    created_at: str
    last_used_at: str | None
    revoked: bool


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_api_token(
    user_id: int, name: str, auth_db: sqlite3.Connection
) -> tuple[str, ApiTokenMeta]:
    """Generate a new personal API token for `user_id`, persist only its
    SHA-256 hash, and return `(plaintext_token, metadata)`.

    SHA-256, not Argon2: unlike a password, this is already a high-entropy
    random value (`secrets.token_urlsafe(32)`), so slow/memory-hard
    hashing would only add latency with no security benefit -- the same
    rationale `accounts/sessions.py`'s refresh-token hashing documents
    (KTD4).

    Returns the metadata alongside the plaintext (rather than the bare
    `str` an earlier sketch of this function's signature had) because the
    caller (the `POST /tokens` endpoint) needs `id`/`created_at`/etc. for
    its 201 response body, and every value needed to build that metadata
    is already local to this function (the row it just inserted) -- a
    second round-trip back to the DB just to re-read what was just written
    would be redundant.
    """
    token = f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    token_hash = _hash_token(token)
    created_at = datetime.now(UTC).isoformat()

    # Single-row insert, still taken under `auth_write_lock` per this
    # codebase's established idiom for every write against `auth_db` (see
    # `auth_db.py`'s `auth_write_lock` docstring), not just multi-statement
    # ones.
    with auth_write_lock, auth_db:
        cursor = auth_db.execute(
            """
            INSERT INTO api_tokens (user_id, name, token_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name, token_hash, created_at),
        )
        token_id = cast(int, cursor.lastrowid)

    meta = ApiTokenMeta(
        id=token_id,
        name=name,
        created_at=created_at,
        last_used_at=None,
        revoked=False,
    )
    return token, meta


def list_api_tokens(user_id: int, auth_db: sqlite3.Connection) -> list[ApiTokenMeta]:
    """Metadata only, for every token belonging to `user_id`, newest first."""
    # Locked even though it's a single read -- see `auth_db.py`'s
    # `auth_write_lock` docstring: an unlocked read can race a concurrent
    # thread's locked write against this same shared connection.
    with auth_write_lock:
        rows = auth_db.execute(
            """
            SELECT id, name, created_at, last_used_at, revoked_at
            FROM api_tokens
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()

    return [
        ApiTokenMeta(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            revoked=row["revoked_at"] is not None,
        )
        for row in rows
    ]


def revoke_api_token(user_id: int, token_id: int, auth_db: sqlite3.Connection) -> None:
    """Revoke `token_id`, scoped to tokens owned by `user_id`.

    `WHERE id = ? AND user_id = ?` means a caller can never affect a token
    that isn't their own no matter what id they pass -- and a rowcount of 0
    is deliberately indistinguishable between "no such token" and "exists,
    but belongs to someone else": both raise `NotFoundError`, so the
    caller can't use this endpoint to probe which token ids exist.
    """
    with auth_write_lock, auth_db:
        cursor = auth_db.execute(
            """
            UPDATE api_tokens SET revoked_at = ?
            WHERE id = ? AND user_id = ? AND revoked_at IS NULL
            """,
            (datetime.now(UTC).isoformat(), token_id, user_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no api token {token_id} for this account")
