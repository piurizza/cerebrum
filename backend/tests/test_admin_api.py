from __future__ import annotations

from fastapi.testclient import TestClient

from tests.mcp_test_support import issue_test_access_token

_PASSWORD = "correct horse battery staple"


def _create_invite(client: TestClient, admin_token: str) -> str:
    response = client.post(
        "/api/invites", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


def _register_via_invite(
    client: TestClient, invite_token: str, username: str
) -> dict[str, object]:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": _PASSWORD, "token": invite_token},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": _PASSWORD}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _register_and_log_in_second_account(
    client: TestClient, admin_token: str, username: str = "second-user"
) -> tuple[dict[str, object], str]:
    """Registers a genuinely non-admin second account through the real
    admin-invite HTTP path this unit adds, then logs it in. Returns the
    `register` response body (which includes the new account's `id`) and
    a live access token for it."""
    invite_token = _create_invite(client, admin_token)
    account = _register_via_invite(client, invite_token, username)
    access_token = _login(client, username)
    return account, access_token


def test_non_admin_cannot_create_invite(client: TestClient) -> None:
    admin_token = issue_test_access_token(client)
    _, non_admin_token = _register_and_log_in_second_account(client, admin_token)

    response = client.post(
        "/api/invites", headers={"Authorization": f"Bearer {non_admin_token}"}
    )

    assert response.status_code == 403


def test_non_admin_cannot_deactivate_an_account(client: TestClient) -> None:
    admin_token = issue_test_access_token(client)
    target_account, non_admin_token = _register_and_log_in_second_account(
        client, admin_token
    )

    response = client.post(
        f"/api/accounts/{target_account['id']}/deactivate",
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )

    assert response.status_code == 403


def test_admin_generated_invite_registers_an_account_and_is_single_use(
    client: TestClient,
) -> None:
    admin_token = issue_test_access_token(client)
    invite_token = _create_invite(client, admin_token)

    first = client.post(
        "/api/auth/register",
        json={
            "username": "invited-once",
            "password": _PASSWORD,
            "token": invite_token,
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["is_admin"] is False

    second = client.post(
        "/api/auth/register",
        json={
            "username": "invited-twice",
            "password": _PASSWORD,
            "token": invite_token,
        },
    )
    assert second.status_code == 400


def test_deactivate_invalidates_session_and_api_tokens_on_their_next_use(
    client: TestClient,
) -> None:
    admin_token = issue_test_access_token(client)
    target_account, target_token = _register_and_log_in_second_account(
        client, admin_token
    )
    target_headers = {"Authorization": f"Bearer {target_token}"}
    assert client.get("/api/notes", headers=target_headers).status_code == 200

    api_token_1 = client.post(
        "/api/tokens", json={"name": "phone"}, headers=target_headers
    ).json()["token"]
    api_token_2 = client.post(
        "/api/tokens", json={"name": "laptop"}, headers=target_headers
    ).json()["token"]

    deactivate_response = client.post(
        f"/api/accounts/{target_account['id']}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deactivate_response.status_code == 204

    assert client.get("/api/notes", headers=target_headers).status_code == 401
    assert (
        client.get(
            "/api/notes", headers={"Authorization": f"Bearer {api_token_1}"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/notes", headers={"Authorization": f"Bearer {api_token_2}"}
        ).status_code
        == 401
    )


def test_admin_cannot_deactivate_their_own_account_via_http(
    client: TestClient,
) -> None:
    admin_token = issue_test_access_token(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    # `issue_test_access_token()` doesn't return the account id -- read it
    # straight from the just-created row rather than adding a new
    # "whoami" endpoint just for this test.
    auth_db = client.app.state.auth_db
    admin_id = auth_db.execute(
        "SELECT id FROM users WHERE username = 'mcp-test-user'"
    ).fetchone()["id"]

    response = client.post(
        f"/api/accounts/{admin_id}/deactivate", headers=admin_headers
    )

    assert response.status_code == 403
    assert client.get("/api/notes", headers=admin_headers).status_code == 200


def test_post_invites_rejects_missing_credential(client: TestClient) -> None:
    response = client.post("/api/invites")
    assert response.status_code == 401


def test_post_deactivate_rejects_missing_credential(client: TestClient) -> None:
    response = client.post("/api/accounts/1/deactivate")
    assert response.status_code == 401


def test_non_admin_cannot_list_accounts(client: TestClient) -> None:
    admin_token = issue_test_access_token(client)
    _, non_admin_token = _register_and_log_in_second_account(client, admin_token)

    response = client.get(
        "/api/accounts", headers={"Authorization": f"Bearer {non_admin_token}"}
    )

    assert response.status_code == 403


def test_get_accounts_rejects_missing_credential(client: TestClient) -> None:
    response = client.get("/api/accounts")
    assert response.status_code == 401


def test_admin_lists_accounts_with_metadata_only(client: TestClient) -> None:
    admin_token = issue_test_access_token(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    target_account, _ = _register_and_log_in_second_account(
        client, admin_token, username="listed-user"
    )

    response = client.get("/api/accounts", headers=admin_headers)

    assert response.status_code == 200, response.text
    accounts = response.json()
    usernames = {account["username"] for account in accounts}
    assert "mcp-test-user" in usernames
    assert "listed-user" in usernames

    target = next(
        account for account in accounts if account["id"] == target_account["id"]
    )
    assert target["is_admin"] is False
    assert target["is_active"] is True
    assert set(target.keys()) == {"id", "username", "is_admin", "is_active"}
