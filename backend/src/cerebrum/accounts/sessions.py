from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

import jwt

from cerebrum.accounts.service import User
from cerebrum.auth_db import auth_write_lock
from cerebrum.settings import get_settings


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

    # Subject is the user id only -- no `is_admin` claim. A later unit's
    # `require_admin` does its own fresh DB lookup for authorization,
    # deliberately not trusting a JWT claim that can't be invalidated
    # before its own expiry.
    access_token = jwt.encode(
        {
            "sub": str(user.id),
            "exp": now + timedelta(minutes=settings.auth_access_token_ttl_minutes),
        },
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )

    refresh_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
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
