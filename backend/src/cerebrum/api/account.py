from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from cerebrum.accounts.service import (
    InvalidCredentialError,
    WeakPasswordError,
    change_password,
)
from cerebrum.accounts.sessions import issue_session
from cerebrum.api.auth import LoginResponse, set_refresh_cookie
from cerebrum.api.deps import get_auth_db, get_current_identity

router = APIRouter()


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/account/password", response_model=LoginResponse)
async def change_own_password(
    body: ChangePasswordRequest,
    response: Response,
    identity: str = Depends(get_current_identity),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> LoginResponse:
    """Change the caller's own password.

    `change_password()` revokes every refresh token the account holds, which
    includes the caller's own -- so this issues a fresh session and returns
    it the same way `/api/auth/login` does, keeping the caller signed in on
    this device while every other session is signed out.

    A wrong current password is a 403, not a 401: the caller *is*
    authenticated, and a 401 here would send the frontend's
    refresh-and-retry path (`fetchWithRetry()` in `client.ts`) through a
    pointless token refresh before surfacing the error.
    """
    try:
        user = await change_password(
            int(identity), body.current_password, body.new_password, auth_db
        )
    except WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidCredentialError as exc:
        raise HTTPException(
            status_code=403, detail="Current password is incorrect"
        ) from exc

    access_token, refresh_token = issue_session(user, auth_db)
    set_refresh_cookie(response, refresh_token)
    return LoginResponse(access_token=access_token)
