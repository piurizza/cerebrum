from __future__ import annotations

from fastapi.testclient import TestClient

# Matches conftest.py's `client` fixture, which sets AUTH_SETUP_TOKEN to
# this exact value before constructing the app.
_SETUP_TOKEN = "y" * 32


def test_register_first_account_with_valid_setup_token_succeeds(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "correct horse battery",
            "token": _SETUP_TOKEN,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["is_admin"] is True


def test_register_with_invalid_token_returns_4xx(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "correct horse battery",
            "token": "wrong-token",
        },
    )

    assert 400 <= response.status_code < 500


def test_register_route_reachable_without_authorization_header(
    client: TestClient,
) -> None:
    # No `Authorization` header is set anywhere in this request -- the
    # route lives on `unauthenticated_router` (mounted directly on `app`,
    # outside `api_router`), so it must never 401/403 for lacking one.
    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "password": "correct horse battery",
            "token": _SETUP_TOKEN,
        },
    )

    assert response.status_code not in (401, 403)
