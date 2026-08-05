from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import jwt

from cerebrum.auth_db import auth_write_lock, hash_token
from cerebrum.settings import get_settings

# `_verify_api_token()` records `last_used_at` on every successful use, but
# not on every single request -- a token used every few seconds (e.g. an
# MCP client polling) doesn't need a fresh fsync'd write each time just to
# advance a display-only timestamp by a few seconds. Skipping the write
# when the existing value is already this recent keeps the metadata
# "recently used" accurate to well within human-observable granularity
# while cutting per-request write/lock volume for frequent callers.
_LAST_USED_AT_UPDATE_INTERVAL = timedelta(minutes=1)


class AuthenticationError(Exception):
    """Raised by `verify_credential()` when a credential fails verification."""


async def verify_credential(credential: str | None, auth_db: sqlite3.Connection) -> str:
    """Verify a bearer-token-style credential and return the identity
    (subject) it authenticates, or raise `AuthenticationError`.

    This is a backend-wide function (KTD4/KTD10), not MCP-scoped --
    positioned beside `api/deps.py` so REST routes can eventually depend
    on the exact same function rather than accumulating a second,
    divergent auth path. Async, since real credential verification needs
    to check state (here, a fresh `users.is_active` lookup) rather than
    pure computation.

    U3 (first real slice, KTD10): validates a session access token -- a
    JWT signed with `auth_jwt_secret`, HS256, subject = user id (see
    `accounts/sessions.py`'s `issue_session()`). Signature/expiry alone
    isn't enough: a signed JWT stays valid until its own TTL regardless of
    server-side state, so a deactivated account's still-unexpired token
    would otherwise keep authenticating for up to `auth_access_token_ttl_minutes`.
    The extra `users.is_active` lookup below closes that gap on every call
    rather than merely bounding it to the TTL window.

    U6: personal API tokens are the second credential shape this function
    verifies. A credential that fails JWT decoding (`except
    jwt.PyJWTError` below) is not immediately rejected -- it falls through
    to `_verify_api_token()`, an opaque-token hash lookup against
    `api_tokens` (see `accounts/tokens.py`'s `create_api_token()` for how
    those are minted). JWT decode failure is the right signal to try this
    second path on: a personal API token (`cbm_pat_...`, from
    `secrets.token_urlsafe`) is never valid base64url-JWT-with-dots shape
    by construction, so there's no ambiguity about which branch a given
    credential belongs to.

    Design note on the `auth_db` parameter (added in U3): this function
    previously took only `credential`, when it was a fixed-sentinel stub
    with no state to check. Real verification needs a live connection, so
    an explicit `auth_db: sqlite3.Connection` parameter was added -- the
    same explicit-connection-argument convention every other DB-touching
    function in this codebase already follows (`register_account()`,
    `authenticate()`, `issue_session()`), rather than reaching for a
    module-level global or a request-scoped contextvar this codebase has
    no other precedent for. The one existing call site, `mcp/auth.py`'s
    `SharedFunctionTokenVerifier`, is updated to supply it via the same
    `app.state.auth_db` REST routes already reach through `api/deps.py`'s
    `get_auth_db()` -- see `mcp/context.py`'s new `get_auth_db(app)` and
    `mcp/auth.py`'s updated constructor. A later unit's REST-side
    `get_current_identity(request)` dependency is expected to supply this
    the same way, via `Depends(get_auth_db)`.
    """
    if not credential:
        raise AuthenticationError("no credential presented")

    settings = get_settings()
    try:
        payload = jwt.decode(
            credential,
            settings.auth_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        # Not a valid/current/correctly-signed access-token JWT -- fall
        # through to the personal-API-token path instead of rejecting
        # outright (see this function's docstring). `_verify_api_token()`
        # raises its own `AuthenticationError` on failure, so nothing more
        # is needed in this branch.
        return _verify_api_token(credential, auth_db)

    user_id = payload.get("sub")
    # Locked even though it's a single read: sqlite3's Connection object is
    # not safe for concurrent statement execution from multiple threads --
    # see `auth_db.py`'s `auth_write_lock` docstring and
    # `accounts/service.py`'s `_is_first_account` for where this was
    # actually reproduced (a raw `sqlite3.InterfaceError`, not a clean
    # application-level exception).
    with auth_write_lock:
        row = auth_db.execute(
            "SELECT is_active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None or not row["is_active"]:
        raise AuthenticationError("invalid credential")

    return str(user_id)


def _verify_api_token(credential: str, auth_db: sqlite3.Connection) -> str:
    """The personal-API-token half of `verify_credential()` (U6): hash
    `credential` and look it up against `api_tokens`, joined to `users` so
    a deactivated account's tokens stop working immediately (R4) rather
    than staying valid until some separate expiry -- API tokens have no
    expiry column at all (they're long-lived by design, R6), so this
    `is_active` check is the *only* thing that can invalidate one short of
    an explicit revoke.

    Two separate locked sections, not one: checking validity and recording
    `last_used_at` have no atomicity requirement between them (unlike
    `accounts/sessions.py`'s refresh-token rotation, which genuinely needs
    one atomic statement to prevent a fork) -- a `last_used_at` update
    that's a few requests stale under concurrent use is harmless. The
    write itself is skipped entirely when the existing value is already
    within `_LAST_USED_AT_UPDATE_INTERVAL`, so a token used every few
    seconds (e.g. a polling MCP client) doesn't pay a fresh fsync'd write
    on every single request just to advance a display-only timestamp.
    """
    token_hash = hash_token(credential)
    with auth_write_lock:
        row = auth_db.execute(
            """
            SELECT api_tokens.id AS token_id, api_tokens.user_id AS user_id,
                   api_tokens.last_used_at AS last_used_at,
                   users.is_active AS is_active
            FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            WHERE api_tokens.token_hash = ? AND api_tokens.revoked_at IS NULL
            """,
            (token_hash,),
        ).fetchone()

    if row is None or not row["is_active"]:
        raise AuthenticationError("invalid credential")

    now = datetime.now(UTC)
    last_used_at = row["last_used_at"]
    stale = (
        last_used_at is None
        or now - datetime.fromisoformat(last_used_at) >= _LAST_USED_AT_UPDATE_INTERVAL
    )
    if stale:
        with auth_write_lock, auth_db:
            auth_db.execute(
                "UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
                (now.isoformat(), row["token_id"]),
            )

    return str(row["user_id"])
