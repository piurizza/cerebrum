from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cerebrum.accounts.service import (
    InvalidTokenError,
    User,
    UsernameTakenError,
    WeakPasswordError,
    register_account,
)
from cerebrum.api.deps import get_auth_db

# No auth dependency on this router by design -- registration (and, once
# later units add them, login/refresh) must be reachable by a caller who
# does not yet hold any credential. Mounted directly on `app` in main.py,
# not through `api_router`, so it can never accidentally pick up an
# auth-requiring dependency added to `api_router` later.
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
