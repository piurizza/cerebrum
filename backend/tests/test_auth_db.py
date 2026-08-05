from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrum.auth_db import connect


def _auth_db_path(vault: Path) -> Path:
    return vault / ".cerebrum" / "auth.sqlite3"


def test_connect_creates_db_file_and_all_tables(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        assert _auth_db_path(vault).exists()
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"users", "refresh_tokens", "api_tokens", "invites"} <= tables
    finally:
        conn.close()


def test_connect_enables_foreign_keys(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        (enabled,) = conn.execute("PRAGMA foreign_keys").fetchone()
        assert enabled == 1
    finally:
        conn.close()


def test_connect_twice_is_idempotent_and_preserves_rows(vault: Path) -> None:
    db_path = _auth_db_path(vault)
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO users (username, password_hash, created_at) "
        "VALUES ('alice', 'hash', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT username FROM users").fetchall()
        assert [row["username"] for row in rows] == ["alice"]
    finally:
        conn.close()


def test_refresh_token_with_unknown_user_id_fails_fk_constraint(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO refresh_tokens "
                "(user_id, token_hash, family_id, expires_at) "
                "VALUES (999, 'hash', 'family', '2026-01-01T00:00:00')"
            )
    finally:
        conn.close()


def test_api_token_with_unknown_user_id_fails_fk_constraint(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO api_tokens (user_id, name, token_hash, created_at) "
                "VALUES (999, 'token', 'hash', '2026-01-01T00:00:00')"
            )
    finally:
        conn.close()


def test_invite_with_unknown_created_by_fails_fk_constraint(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO invites (token_hash, created_by, expires_at) "
                "VALUES ('hash', 999, '2026-01-01T00:00:00')"
            )
    finally:
        conn.close()
