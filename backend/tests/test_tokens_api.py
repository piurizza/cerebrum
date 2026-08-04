from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from tests.mcp_test_support import issue_test_access_token

_PASSWORD = "correct horse battery staple"

# A second `PasswordHasher` instance purely for test setup (inserting a
# second account directly, bypassing `/api/auth/register`'s invite-token
# requirement -- invite generation isn't wired up until a later unit),
# mirroring `test_auth_api.py`'s own `_insert_user()`/`_password_hasher`.
_password_hasher = PasswordHasher()


def _create_token(client: TestClient, name: str = "laptop") -> dict[str, object]:
    response = client.post("/api/tokens", json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json())


def _issue_token_for_a_second_user(client: TestClient, username: str) -> str:
    """`issue_test_access_token()` (`mcp_test_support.py`) only works for
    *reusing* one username against a given vault -- past the very first
    account, `/api/auth/register` requires a real invite (not wired up
    until a later unit), so a second, genuinely distinct username 400s at
    registration. Insert the second account directly (mirroring
    `test_auth_api.py`'s `_insert_user()`), then log in for real to get a
    live access token."""
    auth_db: sqlite3.Connection = client.app.state.auth_db
    with auth_db:
        auth_db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, is_active, created_at)
            VALUES (?, ?, 0, 1, ?)
            """,
            (username, _password_hasher.hash(_PASSWORD), datetime.now(UTC).isoformat()),
        )
    login_response = client.post(
        "/api/auth/login", json={"username": username, "password": _PASSWORD}
    )
    assert login_response.status_code == 200, login_response.text
    return str(login_response.json()["access_token"])


def test_post_tokens_returns_plaintext_once_with_metadata(
    authenticated_client: TestClient,
) -> None:
    body = _create_token(authenticated_client, "laptop")

    assert isinstance(body["token"], str) and body["token"]
    assert body["name"] == "laptop"
    assert body["revoked"] is False
    assert body["last_used_at"] is None
    assert isinstance(body["id"], int)


def test_created_token_authenticates_against_a_protected_route(
    authenticated_client: TestClient,
) -> None:
    body = _create_token(authenticated_client)
    plaintext = body["token"]

    response = authenticated_client.get(
        "/api/notes", headers={"Authorization": f"Bearer {plaintext}"}
    )

    assert response.status_code == 200


def test_get_tokens_lists_only_the_calling_accounts_own_tokens(
    client: TestClient,
) -> None:
    alice_token = issue_test_access_token(client, username="alice")
    _create_token(_with_bearer(client, alice_token), "alice-token")

    bob_token = _issue_token_for_a_second_user(client, "bob")
    _create_token(_with_bearer(client, bob_token), "bob-token")

    response = client.get(
        "/api/tokens", headers={"Authorization": f"Bearer {bob_token}"}
    )
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert names == {"bob-token"}


def test_get_tokens_response_has_no_hash_or_plaintext_field(
    authenticated_client: TestClient,
) -> None:
    _create_token(authenticated_client)

    response = authenticated_client.get("/api/tokens")

    assert response.status_code == 200
    [row] = response.json()
    assert "token" not in row
    assert "token_hash" not in row


def test_delete_token_returns_204_and_invalidates_it_immediately(
    authenticated_client: TestClient,
) -> None:
    body = _create_token(authenticated_client)
    plaintext = body["token"]
    token_id = body["id"]

    delete_response = authenticated_client.delete(f"/api/tokens/{token_id}")
    assert delete_response.status_code == 204

    reuse_response = authenticated_client.get(
        "/api/notes", headers={"Authorization": f"Bearer {plaintext}"}
    )
    assert reuse_response.status_code == 401


def test_delete_token_belonging_to_another_account_returns_404(
    client: TestClient,
) -> None:
    alice_token = issue_test_access_token(client, username="alice")
    alice_body = _create_token(_with_bearer(client, alice_token), "alice-token")

    bob_token = _issue_token_for_a_second_user(client, "bob")
    response = client.delete(
        f"/api/tokens/{alice_body['id']}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )

    assert response.status_code == 404

    # Alice's token is unaffected by Bob's failed attempt.
    still_works = client.get(
        "/api/notes", headers={"Authorization": f"Bearer {alice_body['token']}"}
    )
    assert still_works.status_code == 200


def test_post_tokens_rejects_missing_credential(client: TestClient) -> None:
    response = client.post("/api/tokens", json={"name": "laptop"})
    assert response.status_code == 401


def test_get_tokens_rejects_missing_credential(client: TestClient) -> None:
    response = client.get("/api/tokens")
    assert response.status_code == 401


def test_delete_tokens_rejects_missing_credential(client: TestClient) -> None:
    response = client.delete("/api/tokens/1")
    assert response.status_code == 401


def test_last_used_at_updated_after_a_successful_authenticated_request(
    authenticated_client: TestClient,
) -> None:
    body = _create_token(authenticated_client)
    plaintext = body["token"]
    token_id = body["id"]

    authenticated_client.get(
        "/api/notes", headers={"Authorization": f"Bearer {plaintext}"}
    )

    auth_db: sqlite3.Connection = authenticated_client.app.state.auth_db
    row = auth_db.execute(
        "SELECT last_used_at FROM api_tokens WHERE id = ?", (token_id,)
    ).fetchone()
    assert row["last_used_at"] is not None


def _with_bearer(client: TestClient, token: str) -> TestClient:
    """`client`'s default `Authorization` header is swapped for `token`'s,
    for the duration of the caller's own request -- used where a single
    `client` needs to act as two distinct accounts in one test (unlike
    `authenticated_client`, which is pinned to one account for the whole
    test), mirroring `conftest.py`'s `authenticated_client` fixture's own
    approach of setting the header directly on `client.headers`."""
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
