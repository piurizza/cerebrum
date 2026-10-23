from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrum.auth_db import connect
from tests.mcp_test_support import issue_test_access_token, mcp_test_client


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


def test_app_keeps_accounts_where_cerebrum_auth_db_path_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    accounts_db = tmp_path / "state" / "auth.sqlite3"
    monkeypatch.setenv("CEREBRUM_AUTH_DB_PATH", str(accounts_db))

    with mcp_test_client(vault, monkeypatch) as client:
        token = issue_test_access_token(client)
        authed = client.get(
            "/api/vault-settings", headers={"Authorization": f"Bearer {token}"}
        )

    assert authed.status_code == 200
    assert accounts_db.is_file()
    assert not _auth_db_path(vault).exists()


def test_app_refuses_to_start_when_accounts_db_was_not_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The variable was set before the file was moved: starting would create
    # an empty accounts database and re-arm the setup token.
    vault = tmp_path / "vault"
    connect(_auth_db_path(vault)).close()
    monkeypatch.setenv(
        "CEREBRUM_AUTH_DB_PATH", str(tmp_path / "state" / "auth.sqlite3")
    )

    with (
        pytest.raises(RuntimeError, match="still at"),
        mcp_test_client(vault, monkeypatch),
    ):
        pass

    assert not (tmp_path / "state" / "auth.sqlite3").exists()


def test_refusal_explains_how_to_start_a_second_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The in-vault database may belong to another instance serving the same
    # vault (a read-only second instance): the message must not only say
    # "move it", which would empty that instance's accounts.
    vault = tmp_path / "vault"
    connect(_auth_db_path(vault)).close()
    monkeypatch.setenv(
        "CEREBRUM_AUTH_DB_PATH", str(tmp_path / "state" / "auth.sqlite3")
    )

    with (
        pytest.raises(RuntimeError, match="another Cerebrum") as refused,
        mcp_test_client(vault, monkeypatch),
    ):
        pass

    assert "empty file" in str(refused.value)


def test_read_only_second_instance_starts_with_an_empty_accounts_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The documented second instance: the main instance keeps its accounts
    # in the vault; this one gets its own, created as an empty file first.
    vault = tmp_path / "vault"
    main_accounts = _auth_db_path(vault)
    connect(main_accounts).close()
    main_before = main_accounts.read_bytes()
    state = tmp_path / "state"
    state.mkdir()
    (state / "auth.sqlite3").touch()
    monkeypatch.setenv("CEREBRUM_VAULT_READ_ONLY", "true")
    monkeypatch.setenv("CEREBRUM_INDEX_PATH", str(state / "index.sqlite3"))
    monkeypatch.setenv("CEREBRUM_AUTH_DB_PATH", str(state / "auth.sqlite3"))

    with mcp_test_client(vault, monkeypatch) as client:
        token = issue_test_access_token(client)
        assert (
            client.get(
                "/api/vault-settings", headers={"Authorization": f"Bearer {token}"}
            ).json()["read_only"]
            is True
        )

    assert main_accounts.read_bytes() == main_before


def test_app_starts_once_the_accounts_db_was_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    moved = tmp_path / "state" / "auth.sqlite3"
    connect(moved).close()
    connect(_auth_db_path(vault)).close()  # a leftover copy is fine
    monkeypatch.setenv("CEREBRUM_AUTH_DB_PATH", str(moved))

    with mcp_test_client(vault, monkeypatch) as client:
        assert client.get("/api/health").status_code == 200
