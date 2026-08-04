from __future__ import annotations

import sqlite3
from typing import cast

from fastapi import Depends, HTTPException, Request

from cerebrum.auth import AuthenticationError, verify_credential
from cerebrum.auth_db import auth_write_lock


def get_db(request: Request) -> sqlite3.Connection:
    return cast(sqlite3.Connection, request.app.state.db)


def get_auth_db(request: Request) -> sqlite3.Connection:
    return cast(sqlite3.Connection, request.app.state.auth_db)


async def get_current_identity(
    request: Request,
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> str:
    """`api_router`'s default dependency (see `router.py`) -- every REST
    route included into that router requires this to succeed. Reads only
    the `Authorization: Bearer <token>` header, never a cookie: the
    refresh-token cookie is a structurally separate credential that
    `accounts/sessions.py`'s `refresh_session()` reads directly, never
    through this dependency (see `api/auth.py`'s `unauthenticated_router`,
    which is mounted outside `api_router` precisely so it never picks up
    this dependency).
    """
    auth_header = request.headers.get("Authorization")
    credential = None
    if auth_header and auth_header.startswith("Bearer "):
        credential = auth_header.removeprefix("Bearer ")
    try:
        return await verify_credential(credential, auth_db)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="Not authenticated") from exc


def require_admin(
    identity: str = Depends(get_current_identity),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> str:
    """Layers on top of `get_current_identity` (which already ran and
    proved `identity` is a currently-active account) to additionally
    require `is_admin`. Routes that depend on this end up doubly gated:
    `api_router`'s default `Depends(get_current_identity)` runs first as
    always, then this dependency's own `Depends(get_current_identity)`
    resolves to the same cached result within the request and layers the
    admin check on top.

    Always a fresh `SELECT` against `is_admin`, never a JWT claim --
    `accounts/sessions.py`'s `_mint_access_token()` deliberately excludes
    one (see its docstring, KTD3): a claim baked into the token at login
    time couldn't be revoked before the token's own expiry if an admin
    were later demoted, whereas this lookup reflects the current row on
    every call.

    A missing row (the identity's account was deleted out from under an
    otherwise-valid token -- not expected in practice, since
    `get_current_identity` already confirmed the account exists and is
    active moments ago, but not impossible under a race) is treated the
    same as "not admin": 403, not a 500. There's nothing actionable a
    caller could do differently for "doesn't exist" vs. "exists but isn't
    admin" here, and a 500 would leak that distinction for no benefit.
    """
    # Locked even though it's a single read -- see `auth_db.py`'s
    # `auth_write_lock` docstring: an unlocked read can race a concurrent
    # thread's locked write against this same shared connection.
    with auth_write_lock:
        row = auth_db.execute(
            "SELECT is_admin FROM users WHERE id = ?", (identity,)
        ).fetchone()

    if row is None or not row["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    return identity
