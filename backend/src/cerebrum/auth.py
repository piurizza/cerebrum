from __future__ import annotations

import sqlite3

import jwt

from cerebrum.auth_db import auth_write_lock
from cerebrum.settings import get_settings


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

    Personal API tokens (a second credential shape meant to share this
    same interface, hashed and looked up against the `api_tokens` table)
    are not wired up yet -- that's a later unit. For now, any credential
    that doesn't verify as a live, active-user JWT falls straight through
    to `AuthenticationError` below rather than attempting an api_tokens
    lookup; the early `return` on JWT success leaves room for a later unit
    to add an `else` branch here cleanly instead of restructuring this
    function.

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
    except jwt.PyJWTError as exc:
        # Not a valid/current/correctly-signed access-token JWT. A later
        # unit adds a second branch here (an `else`, not a rewrite of this
        # one) that falls through to a personal-API-token hash lookup
        # against `api_tokens` instead of rejecting outright -- that
        # table has no wiring for authentication yet, so this unit does
        # not attempt it.
        raise AuthenticationError("invalid credential") from exc

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
