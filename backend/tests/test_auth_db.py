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
        assert {
            "users",
            "refresh_tokens",
            "api_tokens",
            "invites",
            "oidc_identities",
        } <= tables
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


def _insert_identity(
    conn: sqlite3.Connection, issuer: str, subject: str, user_id: int
) -> None:
    conn.execute(
        "INSERT INTO oidc_identities (issuer, subject, user_id, created_at) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00')",
        (issuer, subject, user_id),
    )


def _insert_alice(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "INSERT INTO users (username, password_hash, created_at) "
        "VALUES ('alice', 'hash', '2026-01-01T00:00:00')"
    )
    return int(cursor.lastrowid or 0)


def test_connect_twice_keeps_oidc_identities(vault: Path) -> None:
    db_path = _auth_db_path(vault)
    conn = connect(db_path)
    user_id = _insert_alice(conn)
    _insert_identity(conn, "https://idp.example", "sub-1", user_id)
    conn.commit()
    conn.close()

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT issuer, subject, user_id, display_name FROM oidc_identities"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("https://idp.example", "sub-1", user_id, None)
        ]
    finally:
        conn.close()


def test_oidc_identity_with_unknown_user_id_fails_fk_constraint(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_identity(conn, "https://idp.example", "sub-1", 999)
    finally:
        conn.close()


def test_one_provider_subject_maps_to_one_account(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        user_id = _insert_alice(conn)
        bob_id = int(
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) "
                "VALUES ('bob', 'hash', '2026-01-01T00:00:00')"
            ).lastrowid
            or 0
        )
        _insert_identity(conn, "https://idp.example", "sub-1", user_id)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_identity(conn, "https://idp.example", "sub-1", bob_id)
    finally:
        conn.close()


def test_one_account_links_at_most_one_identity_per_issuer(vault: Path) -> None:
    conn = connect(_auth_db_path(vault))
    try:
        user_id = _insert_alice(conn)
        _insert_identity(conn, "https://idp.example", "sub-1", user_id)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_identity(conn, "https://idp.example", "sub-2", user_id)
        # A different issuer (after a provider switch) is a separate link.
        _insert_identity(conn, "https://other-idp.example", "sub-1", user_id)
    finally:
        conn.close()
