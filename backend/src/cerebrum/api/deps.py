from __future__ import annotations

import sqlite3
from typing import cast

from fastapi import Depends, HTTPException, Request

from cerebrum.auth import AuthenticationError, verify_credential


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
