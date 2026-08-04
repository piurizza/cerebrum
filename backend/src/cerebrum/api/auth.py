from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from cerebrum.accounts.service import (
    InvalidCredentialError,
    InvalidTokenError,
    TokenReuseDetectedError,
    User,
    UsernameTakenError,
    WeakPasswordError,
    authenticate,
    register_account,
)
from cerebrum.accounts.sessions import issue_session, refresh_session
from cerebrum.api.deps import get_auth_db
from cerebrum.settings import get_settings

# No auth dependency on this router by design -- registration, login, and
# refresh must be reachable by a caller who does not yet hold any valid
# access token (refresh authenticates via its own cookie, not a bearer
# credential). Mounted directly on `app` in main.py, not through
# `api_router`, so it can never accidentally pick up an auth-requiring
# dependency added to `api_router` later.
unauthenticated_router = APIRouter()


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Shared by `login()` and `refresh()` -- both hand the caller a fresh
    refresh token under identical cookie flags."""
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=settings.auth_cookie_secure,
        # Scoped to the refresh endpoint only -- the browser never sends
        # this cookie on any other request, including the login request
        # itself.
        path="/api/auth/refresh",
        max_age=settings.auth_refresh_token_ttl_days * 24 * 60 * 60,
    )


class RegisterRequest(BaseModel):
    username: str
    password: str
    token: str


@unauthenticated_router.post("/register", response_model=User, status_code=201)
async def register(
    body: RegisterRequest, auth_db: sqlite3.Connection = Depends(get_auth_db)
) -> User:
    try:
        return await register_account(body.username, body.password, body.token, auth_db)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid registration token"
        ) from exc
    except WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UsernameTakenError as exc:
        raise HTTPException(status_code=409, detail="Username already taken") from exc


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str


@unauthenticated_router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> LoginResponse:
    try:
        user = await authenticate(body.username, body.password, auth_db)
    except InvalidCredentialError as exc:
        raise HTTPException(
            status_code=401, detail="Invalid username or password"
        ) from exc

    access_token, refresh_token = issue_session(user, auth_db)
    _set_refresh_cookie(response, refresh_token)
    return LoginResponse(access_token=access_token)


@unauthenticated_router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    response: Response,
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> LoginResponse:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token is None:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    try:
        access_token, new_refresh_token = refresh_session(refresh_token, auth_db)
    except (InvalidTokenError, TokenReuseDetectedError) as exc:
        # One generic message for both causes -- an unknown/expired token
        # and an already-rotated (stolen) one must not be distinguishable
        # to the caller, same rationale as `InvalidCredentialError` at
        # login.
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

    _set_refresh_cookie(response, new_refresh_token)
    return LoginResponse(access_token=access_token)
