from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from cerebrum.accounts.service import NO_PASSWORD_HASH
from cerebrum.settings import get_settings
from tests.oidc_fake import ISSUER

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


# -- the linked provider identity (`/api/account/identity`) --------------------


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _invited_user(client: TestClient, admin_token: str, username: str = "bob") -> str:
    """A non-admin account with a password, through an invite; returns its
    access token."""
    invite = client.post("/api/invites", headers=_bearer(admin_token))
    assert invite.status_code == 201, invite.text
    registered = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": _OLD_PASSWORD,
            "token": invite.json()["token"],
        },
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login", json={"username": username, "password": _OLD_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


def _passwordless_user(client: TestClient, admin_token: str) -> str:
    """A non-admin account with no password (as signing up through the
    provider leaves it); returns its access token."""
    token = _invited_user(client, admin_token, "carol")
    with _auth_db(client) as auth_db:
        auth_db.execute(
            "UPDATE users SET password_hash = ? WHERE username = 'carol'",
            (NO_PASSWORD_HASH,),
        )
    return token


def _auth_db(client: TestClient) -> sqlite3.Connection:
    auth_db: sqlite3.Connection = client.app.state.auth_db
    return auth_db


def _link(
    client: TestClient,
    username: str,
    subject: str = "provider-user-1",
    issuer: str = ISSUER,
    display_name: str | None = "alice",
) -> None:
    with _auth_db(client) as auth_db:
        auth_db.execute(
            """
            INSERT INTO oidc_identities
                (issuer, subject, user_id, display_name, created_at)
            SELECT ?, ?, id, ?, ? FROM users WHERE username = ?
            """,
            (issuer, subject, display_name, datetime.now(UTC).isoformat(), username),
        )


def _links(client: TestClient) -> list[tuple[str, str]]:
    rows = (
        _auth_db(client)
        .execute(
            """
            SELECT users.username, oidc_identities.issuer FROM oidc_identities
            JOIN users ON users.id = oidc_identities.user_id
            ORDER BY users.username, oidc_identities.issuer
            """
        )
        .fetchall()
    )
    return [(row["username"], row["issuer"]) for row in rows]


def _identity(client: TestClient, token: str) -> dict[str, object]:
    response = client.get("/api/account/identity", headers=_bearer(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


def _unlink(client: TestClient, token: str) -> httpx.Response:
    return client.delete("/api/account/identity", headers=_bearer(token))


def _switch_password_login_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_PASSWORD_LOGIN", "false")
    get_settings.cache_clear()


def test_identity_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/api/account/identity").status_code == 401
    assert client.delete("/api/account/identity").status_code == 401


def test_identity_without_a_provider_configured(client: TestClient) -> None:
    token = _register_and_login(client)

    assert _identity(client, token) == {
        "linked": False,
        "provider_name": None,
        "display_name": None,
        "has_password": True,
        "password_usable": True,
    }
    assert _unlink(client, token).status_code == 204


@pytest.mark.usefixtures("fake_provider")
def test_identity_of_an_unlinked_account(client: TestClient) -> None:
    token = _register_and_login(client)

    assert _identity(client, token) == {
        "linked": False,
        "provider_name": "SSO",
        "display_name": None,
        "has_password": True,
        "password_usable": True,
    }


@pytest.mark.usefixtures("fake_provider")
def test_identity_of_a_linked_account(client: TestClient) -> None:
    admin_token = _register_and_login(client)
    bob_token = _invited_user(client, admin_token)
    _link(client, "bob")

    assert _identity(client, bob_token) == {
        "linked": True,
        "provider_name": "SSO",
        "display_name": "alice",
        "has_password": True,
        "password_usable": True,
    }


@pytest.mark.usefixtures("fake_provider")
def test_identity_ignores_a_link_from_another_issuer(client: TestClient) -> None:
    token = _register_and_login(client)
    _link(client, "mira", issuer="https://old-idp.test")

    identity = _identity(client, token)

    assert identity["linked"] is False
    assert identity["display_name"] is None


@pytest.mark.usefixtures("fake_provider")
def test_password_switch_off_makes_a_linked_non_admins_password_unusable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_token = _register_and_login(client)
    bob_token = _invited_user(client, admin_token)
    dave_token = _invited_user(client, admin_token, "dave")
    _link(client, "mira", subject="admin-subject")
    _link(client, "bob")
    _switch_password_login_off(monkeypatch)

    # Linked non-admin: the password exists but no longer signs in.
    assert _identity(client, bob_token)["has_password"] is True
    assert _identity(client, bob_token)["password_usable"] is False
    # Admins keep theirs (break-glass), and so do unlinked accounts.
    assert _identity(client, admin_token)["password_usable"] is True
    assert _identity(client, dave_token)["password_usable"] is True


@pytest.mark.usefixtures("fake_provider")
def test_identity_of_a_passwordless_account(client: TestClient) -> None:
    admin_token = _register_and_login(client)
    carol_token = _passwordless_user(client, admin_token)
    _link(client, "carol")

    identity = _identity(client, carol_token)

    assert identity["has_password"] is False
    assert identity["password_usable"] is False


@pytest.mark.usefixtures("fake_provider")
def test_unlinking_a_password_account(client: TestClient) -> None:
    admin_token = _register_and_login(client)
    bob_token = _invited_user(client, admin_token)
    _link(client, "bob")
    _link(client, "mira", subject="admin-subject")

    response = _unlink(client, bob_token)

    assert response.status_code == 204, response.text
    assert _links(client) == [("mira", ISSUER)]
    assert _identity(client, bob_token)["linked"] is False
    # Idempotent: nothing left to unlink is still a success.
    assert _unlink(client, bob_token).status_code == 204


@pytest.mark.usefixtures("fake_provider")
def test_unlinking_leaves_links_from_another_issuer_alone(client: TestClient) -> None:
    token = _register_and_login(client)
    _link(client, "mira")
    _link(client, "mira", subject="old-subject", issuer="https://old-idp.test")

    assert _unlink(client, token).status_code == 204

    assert _links(client) == [("mira", "https://old-idp.test")]


@pytest.mark.usefixtures("fake_provider")
def test_unlinking_a_passwordless_account_is_refused(client: TestClient) -> None:
    admin_token = _register_and_login(client)
    carol_token = _passwordless_user(client, admin_token)
    _link(client, "carol")

    response = _unlink(client, carol_token)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "You need a password you can sign in with before unlinking"
    )
    assert _links(client) == [("carol", ISSUER)]


@pytest.mark.usefixtures("fake_provider")
def test_password_switch_off_linked_non_admin_cannot_unlink(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_token = _register_and_login(client)
    bob_token = _invited_user(client, admin_token)
    _link(client, "bob")
    _link(client, "mira", subject="admin-subject")
    _switch_password_login_off(monkeypatch)

    refused = _unlink(client, bob_token)
    # The admin's password still signs in (break-glass), so they may unlink.
    allowed = _unlink(client, admin_token)

    assert refused.status_code == 409, refused.text
    assert allowed.status_code == 204, allowed.text
    assert _links(client) == [("bob", ISSUER)]
