from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from cerebrum.accounts.service import NotFoundError
from cerebrum.accounts.tokens import (
    ApiTokenMeta,
    create_api_token,
    list_api_tokens,
    revoke_api_token,
)
from cerebrum.api.deps import get_auth_db, get_current_identity

router = APIRouter()


class CreateApiTokenRequest(BaseModel):
    name: str


class CreateApiTokenResponse(ApiTokenMeta):
    """`ApiTokenMeta` plus the plaintext token -- the only response in
    this module that ever includes it. Every other route (`GET /tokens`,
    and `ApiTokenMeta` itself) carries metadata only."""

    token: str


@router.post("/tokens", response_model=CreateApiTokenResponse, status_code=201)
def create_token(
    body: CreateApiTokenRequest,
    identity: str = Depends(get_current_identity),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> CreateApiTokenResponse:
    token, meta = create_api_token(int(identity), body.name, auth_db)
    return CreateApiTokenResponse(token=token, **meta.model_dump())


@router.get("/tokens", response_model=list[ApiTokenMeta])
def list_tokens(
    identity: str = Depends(get_current_identity),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> list[ApiTokenMeta]:
    return list_api_tokens(int(identity), auth_db)


@router.delete("/tokens/{token_id}", status_code=204)
def delete_token(
    token_id: int,
    identity: str = Depends(get_current_identity),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> Response:
    try:
        revoke_api_token(int(identity), token_id, auth_db)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Token not found") from exc
    return Response(status_code=204)
