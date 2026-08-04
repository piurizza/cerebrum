from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from cerebrum.accounts.service import (
    InvalidCredentialError,
    InvalidTokenError,
    User,
    UsernameTakenError,
    WeakPasswordError,
    authenticate,
    register_account,
)
from cerebrum.accounts.sessions import issue_session
from cerebrum.api.deps import get_auth_db
from cerebrum.settings import get_settings

# No auth dependency on this router by design -- registration and login
# (and, once a later unit adds it, refresh) must be reachable by a caller
# who does not yet hold any credential. Mounted directly on `app` in
# main.py, not through `api_router`, so it can never accidentally pick up
# an auth-requiring dependency added to `api_router` later.
unauthenticated_router = APIRouter()


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

    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=settings.auth_cookie_secure,
        # Scoped to the refresh endpoint only (U4) -- the browser never
        # sends this cookie on any other request, including the login
        # request itself.
        path="/api/auth/refresh",
        max_age=settings.auth_refresh_token_ttl_days * 24 * 60 * 60,
    )
    return LoginResponse(access_token=access_token)
