from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from cerebrum.accounts.oidc_accounts import (
    UnusablePasswordError,
    identity_status,
    unlink_identity,
)
from cerebrum.accounts.service import (
    InvalidCredentialError,
    WeakPasswordError,
    change_password,
)
from cerebrum.accounts.sessions import issue_session
from cerebrum.api.auth import LoginResponse, set_refresh_cookie
from cerebrum.api.deps import get_auth_db, get_current_identity
from cerebrum.settings import get_settings

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

    So is an account whose password doesn't sign it in (KTD8): one with no
    password, or a linked non-admin's while password login is switched off
    (KTD11). Checked first, so such an account's guesses at its own
    password never reach the lockout count.
    """
    if not identity_status(auth_db, int(identity)).password_usable:
        raise HTTPException(
            status_code=403,
            detail="Your password does not sign you in, so it cannot be changed",
        )
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


class AccountIdentityResponse(BaseModel):
    linked: bool
    # Null when no provider is configured.
    provider_name: str | None
    # The preferred username or email the provider gave at link time.
    display_name: str | None
    has_password: bool
    # Whether the password signs in: with password login switched off, a
    # linked non-admin's password no longer does (KTD8).
    password_usable: bool


@router.get("/account/identity", response_model=AccountIdentityResponse)
async def get_own_identity(
    identity: str = Depends(get_current_identity),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> AccountIdentityResponse:
    """The caller's link to the configured sign-in provider, for Settings."""
    settings = get_settings()
    status = identity_status(auth_db, int(identity))
    return AccountIdentityResponse(
        linked=status.linked,
        provider_name=settings.oidc_provider_name if settings.oidc_enabled else None,
        display_name=status.display_name,
        has_password=status.has_password,
        password_usable=status.password_usable,
    )


@router.delete("/account/identity", status_code=204)
async def unlink_own_identity(
    identity: str = Depends(get_current_identity),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> Response:
    """Unlink the caller's provider identity (R9). 204 when nothing is
    linked. 409 when the account would be left with no password it can
    sign in with."""
    try:
        unlink_identity(auth_db, int(identity))
    except UnusablePasswordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)
