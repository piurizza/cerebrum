from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from cerebrum.accounts.admin import (
    AccountSummary,
    create_invite,
    deactivate_account,
    list_accounts,
)
from cerebrum.accounts.service import ForbiddenError
from cerebrum.api.deps import get_auth_db, require_admin

router = APIRouter()


@router.get("/accounts", response_model=list[AccountSummary])
def list_accounts_route(
    _identity: str = Depends(require_admin),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> list[AccountSummary]:
    return list_accounts(auth_db)


class CreateInviteResponse(BaseModel):
    """The plaintext invite token -- shown exactly once, same treatment
    `api/tokens.py`'s `CreateApiTokenResponse` gives a freshly minted
    personal API token."""

    token: str


@router.post("/invites", response_model=CreateInviteResponse, status_code=201)
def create_invite_route(
    identity: str = Depends(require_admin),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> CreateInviteResponse:
    token = create_invite(int(identity), auth_db)
    return CreateInviteResponse(token=token)


@router.post("/accounts/{account_id}/deactivate", status_code=204)
def deactivate_account_route(
    account_id: int,
    identity: str = Depends(require_admin),
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> Response:
    try:
        deactivate_account(int(identity), account_id, auth_db)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(status_code=204)
