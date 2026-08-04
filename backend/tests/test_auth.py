from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import jwt
import pytest
from fastapi import FastAPI

from cerebrum.accounts.tokens import create_api_token
from cerebrum.auth import AuthenticationError, verify_credential
from cerebrum.auth_db import connect
from cerebrum.mcp.auth import SharedFunctionTokenVerifier
from cerebrum.settings import get_settings


@pytest.fixture
def auth_db(vault: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(vault / ".cerebrum" / "auth.sqlite3")
    yield conn
    conn.close()


@pytest.fixture
def app(auth_db: sqlite3.Connection) -> FastAPI:
    # `SharedFunctionTokenVerifier` only ever reads `app.state.auth_db`
    # (via `mcp/context.py`'s `get_auth_db()`) -- a bare `FastAPI()` with
    # that one attribute set is enough, no need for the full `create_app()`.
    fastapi_app = FastAPI()
    fastapi_app.state.auth_db = auth_db
    return fastapi_app


def _insert_user(auth_db: sqlite3.Connection, *, is_active: bool = True) -> int:
    with auth_db:
        cursor = auth_db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, is_active, created_at)
            VALUES (?, ?, 0, ?, ?)
            """,
            ("carol", "unused-hash", int(is_active), datetime.now(UTC).isoformat()),
        )
    return cast(int, cursor.lastrowid)


def _mint_jwt(user_id: int, *, expires_delta: timedelta = timedelta(minutes=10)) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + expires_delta},
        get_settings().auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def test_verify_credential_rejects_missing_credential(
    auth_db: sqlite3.Connection,
) -> None:
    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(None, auth_db))


def test_verify_credential_rejects_empty_credential(
    auth_db: sqlite3.Connection,
) -> None:
    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential("", auth_db))


def test_verify_credential_rejects_garbage_credential(
    auth_db: sqlite3.Connection,
) -> None:
    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential("not-a-jwt", auth_db))


def test_verify_credential_accepts_valid_token_for_active_user(
    auth_db: sqlite3.Connection,
) -> None:
    user_id = _insert_user(auth_db)
    token = _mint_jwt(user_id)

    subject = asyncio.run(verify_credential(token, auth_db))

    assert subject == str(user_id)


def test_verify_credential_rejects_token_for_deactivated_user(
    auth_db: sqlite3.Connection,
) -> None:
    user_id = _insert_user(auth_db, is_active=False)
    token = _mint_jwt(user_id)

    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(token, auth_db))


def test_verify_credential_rejects_token_for_unknown_user(
    auth_db: sqlite3.Connection,
) -> None:
    token = _mint_jwt(999999)

    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(token, auth_db))


def test_verify_credential_rejects_expired_token(auth_db: sqlite3.Connection) -> None:
    user_id = _insert_user(auth_db)
    token = _mint_jwt(user_id, expires_delta=timedelta(minutes=-1))

    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(token, auth_db))


def test_verify_credential_accepts_valid_api_token(
    auth_db: sqlite3.Connection,
) -> None:
    user_id = _insert_user(auth_db)
    token, _meta = create_api_token(user_id, "laptop", auth_db)

    subject = asyncio.run(verify_credential(token, auth_db))

    assert subject == str(user_id)


def test_verify_credential_rejects_revoked_api_token(
    auth_db: sqlite3.Connection,
) -> None:
    user_id = _insert_user(auth_db)
    token, meta = create_api_token(user_id, "laptop", auth_db)
    with auth_db:
        auth_db.execute(
            "UPDATE api_tokens SET revoked_at = datetime('now') WHERE id = ?",
            (meta.id,),
        )

    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(token, auth_db))


def test_verify_credential_rejects_api_token_for_deactivated_user(
    auth_db: sqlite3.Connection,
) -> None:
    user_id = _insert_user(auth_db, is_active=False)
    token, _meta = create_api_token(user_id, "laptop", auth_db)

    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(token, auth_db))


def test_verify_credential_updates_last_used_at_on_api_token_success(
    auth_db: sqlite3.Connection,
) -> None:
    user_id = _insert_user(auth_db)
    token, meta = create_api_token(user_id, "laptop", auth_db)

    before = auth_db.execute(
        "SELECT last_used_at FROM api_tokens WHERE id = ?", (meta.id,)
    ).fetchone()
    assert before["last_used_at"] is None

    asyncio.run(verify_credential(token, auth_db))

    after = auth_db.execute(
        "SELECT last_used_at FROM api_tokens WHERE id = ?", (meta.id,)
    ).fetchone()
    assert after["last_used_at"] is not None


def test_token_verifier_accepts_valid_credential(
    app: FastAPI, auth_db: sqlite3.Connection
) -> None:
    user_id = _insert_user(auth_db)
    token = _mint_jwt(user_id)
    verifier = SharedFunctionTokenVerifier(app=app)

    result = asyncio.run(verifier.verify_token(token))

    assert result is not None
    assert result.client_id == str(user_id)


def test_token_verifier_rejects_wrong_credential(
    app: FastAPI,
) -> None:
    verifier = SharedFunctionTokenVerifier(app=app)

    result = asyncio.run(verifier.verify_token("wrong"))

    assert result is None
