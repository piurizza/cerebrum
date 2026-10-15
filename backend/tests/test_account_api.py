from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

# Matches conftest.py's `client` fixture, which sets AUTH_SETUP_TOKEN to
# this exact value before constructing the app.
_SETUP_TOKEN = "y" * 32
_OLD_PASSWORD = "correct horse battery staple"
_NEW_PASSWORD = "a brand new long passphrase"


def _register_and_login(client: TestClient, username: str = "mira") -> str:
    """Bootstrap the first account and log in. Returns the access token;
    the refresh-token cookie is left in `client`'s cookie jar."""
    client.post(
        "/api/auth/register",
        json={"username": username, "password": _OLD_PASSWORD, "token": _SETUP_TOKEN},
    )
    response = client.post(
        "/api/auth/login", json={"username": username, "password": _OLD_PASSWORD}
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _change_password(
    client: TestClient, access_token: str, current: str, new: str
) -> httpx.Response:
    return client.post(
        "/api/account/password",
        json={"current_password": current, "new_password": new},
        headers={"Authorization": f"Bearer {access_token}"},
    )


def _login_status(client: TestClient, password: str, username: str = "mira") -> int:
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).status_code


def test_change_password_swaps_which_password_logs_in(client: TestClient) -> None:
    token = _register_and_login(client)

    response = _change_password(client, token, _OLD_PASSWORD, _NEW_PASSWORD)

    assert response.status_code == 200
    assert _login_status(client, _OLD_PASSWORD) == 401
    assert _login_status(client, _NEW_PASSWORD) == 200


def test_change_password_returns_a_working_session_for_the_caller(
    client: TestClient,
) -> None:
    token = _register_and_login(client)

    response = _change_password(client, token, _OLD_PASSWORD, _NEW_PASSWORD)

    assert response.json()["access_token"]
    set_cookie = response.headers["set-cookie"].lower()
    assert "refresh_token=" in set_cookie
    assert "path=/api/auth/refresh" in set_cookie
    # The fresh cookie the response just stored keeps this device signed in.
    assert client.post("/api/auth/refresh").status_code == 200


def test_change_password_signs_out_every_other_session(client: TestClient) -> None:
    # Two independent sessions for the same account: `other_device` logs in
    # first, then `client` logs in and changes the password.
    _register_and_login(client)
    other_device = TestClient(client.app)
    other_login = other_device.post(
        "/api/auth/login", json={"username": "mira", "password": _OLD_PASSWORD}
    )
    assert other_login.status_code == 200
    token = client.post(
        "/api/auth/login", json={"username": "mira", "password": _OLD_PASSWORD}
    ).json()["access_token"]

    _change_password(client, token, _OLD_PASSWORD, _NEW_PASSWORD)

    assert other_device.post("/api/auth/refresh").status_code == 401


def test_wrong_current_password_is_403_and_changes_nothing(client: TestClient) -> None:
    token = _register_and_login(client)

    response = _change_password(client, token, "not my password at all", _NEW_PASSWORD)

    assert response.status_code == 403
    assert _login_status(client, _OLD_PASSWORD) == 200
    assert _login_status(client, _NEW_PASSWORD) == 401


def test_wrong_current_password_counts_toward_login_lockout(
    client: TestClient,
) -> None:
    # Without this, a stolen access token could brute-force the password
    # through this endpoint without ever tripping the lockout login enforces.
    token = _register_and_login(client)

    for _ in range(5):
        _change_password(client, token, "wrong guess, repeated", _NEW_PASSWORD)

    assert _login_status(client, _OLD_PASSWORD) == 401
    # Locked out here too, even with the right current password.
    locked = _change_password(client, token, _OLD_PASSWORD, _NEW_PASSWORD)
    assert locked.status_code == 403


def test_too_short_new_password_is_400(client: TestClient) -> None:
    token = _register_and_login(client)

    response = _change_password(client, token, _OLD_PASSWORD, "short")

    assert response.status_code == 400
    assert "12" in response.json()["detail"]
    assert _login_status(client, _OLD_PASSWORD) == 200


def test_change_password_requires_authentication(client: TestClient) -> None:
    _register_and_login(client)

    response = client.post(
        "/api/account/password",
        json={"current_password": _OLD_PASSWORD, "new_password": _NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert _login_status(client, _OLD_PASSWORD) == 200
