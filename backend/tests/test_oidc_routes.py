"""The OpenID Connect start and callback routes (`api/oidc.py`), end to end
through `TestClient` against the fake provider in `tests/oidc_fake.py`:
signing in with a linked identity, signing up with an invite, and linking
from Settings.

Each flow runs the way a browser would: `POST /api/auth/oidc/start` sets the
`oidc_flow` cookie in the client's jar, `FakeProvider.authorize()` stands in
for the trip to the provider's login page, and the callback request carries
the cookie back."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from cerebrum.accounts.service import NO_PASSWORD_HASH
from cerebrum.auth_db import hash_token
from tests.mcp_test_support import issue_test_access_token
from tests.oidc_fake import ISSUER, FakeProvider, configure_oidc_env

_START = "/api/auth/oidc/start"
_CALLBACK = "/api/auth/oidc/callback"
_SETUP_TOKEN = "y" * 32
_PASSWORD = "correct horse battery staple"
_JWT_SECRET = "x" * 32


# -- helpers -------------------------------------------------------------------


def _auth_db(client: TestClient) -> sqlite3.Connection:
    auth_db: sqlite3.Connection = client.app.state.auth_db
    return auth_db


def _bootstrap_admin(client: TestClient) -> str:
    """The first (admin) account, through the setup token; returns its
    access token."""
    return issue_test_access_token(client, "admin", _PASSWORD)


def _create_invite(client: TestClient, admin_token: str) -> str:
    response = client.post(
        "/api/invites", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


def _user_id(client: TestClient, username: str) -> int:
    row = (
        _auth_db(client)
        .execute("SELECT id FROM users WHERE username = ?", (username,))
        .fetchone()
    )
    assert row is not None, f"no user {username!r}"
    return int(row["id"])


def _count(client: TestClient, table: str) -> int:
    row = _auth_db(client).execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])


def _link(client: TestClient, user_id: int, subject: str, issuer: str = ISSUER) -> None:
    with _auth_db(client) as auth_db:
        auth_db.execute(
            """
            INSERT INTO oidc_identities (issuer, subject, user_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (issuer, subject, user_id, datetime.now(UTC).isoformat()),
        )


def _invite_consumed_by(client: TestClient, invite_token: str) -> Any:
    row = (
        _auth_db(client)
        .execute(
            "SELECT consumed_by FROM invites WHERE token_hash = ?",
            (hash_token(invite_token),),
        )
        .fetchone()
    )
    assert row is not None
    return row["consumed_by"]


def _start(
    client: TestClient,
    intent: str = "login",
    headers: dict[str, str] | None = None,
    **fields: str,
) -> httpx.Response:
    return client.post(_START, json={"intent": intent, **fields}, headers=headers)


def _callback(client: TestClient, **params: str) -> httpx.Response:
    return client.get(_CALLBACK, params=params, follow_redirects=False)


def _run_flow(
    client: TestClient, provider: FakeProvider, intent: str = "login", **fields: str
) -> httpx.Response:
    """Start a flow, sign in at the fake provider, and return the callback's
    response (not followed)."""
    started = _start(client, intent, **fields)
    assert started.status_code == 200, started.text
    code, state = provider.authorize(started.json()["authorization_url"])
    return _callback(client, code=code, state=state)


def _set_cookies(response: httpx.Response) -> dict[str, str]:
    """Every `Set-Cookie` header on `response`, by cookie name, lowercased
    (`response.cookies` doesn't expose the flags)."""
    cookies = {}
    for header in response.headers.get_list("set-cookie"):
        name = header.split("=", 1)[0]
        cookies[name] = header.lower()
    return cookies


def _assert_flow_cookie_cleared(response: httpx.Response) -> None:
    flow_cookie = _set_cookies(response).get("oidc_flow")
    assert flow_cookie is not None, "the callback did not clear oidc_flow"
    assert "max-age=0" in flow_cookie
    assert "path=/api/auth/oidc/callback" in flow_cookie


def _assert_failure(response: httpx.Response, location: str) -> None:
    assert response.status_code == 303, response.text
    assert response.headers["location"] == location
    assert "refresh_token" not in _set_cookies(response)
    _assert_flow_cookie_cleared(response)


# -- signing in ----------------------------------------------------------------


def test_login_with_a_linked_active_account_signs_in(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    _bootstrap_admin(client)
    admin_id = _user_id(client, "admin")
    _link(client, admin_id, fake_provider.subject)

    response = _run_flow(client, fake_provider)

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/?oidc=1"
    cookies = _set_cookies(response)
    refresh_cookie = cookies["refresh_token"]
    assert "httponly" in refresh_cookie
    assert "samesite=strict" in refresh_cookie
    assert "path=/api/auth/refresh" in refresh_cookie
    _assert_flow_cookie_cleared(response)

    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    claims = jwt.decode(
        refreshed.json()["access_token"], _JWT_SECRET, algorithms=["HS256"]
    )
    assert claims["sub"] == str(admin_id)


def test_login_ignores_the_password_lockout(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    _bootstrap_admin(client)
    admin_id = _user_id(client, "admin")
    _link(client, admin_id, fake_provider.subject)
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "no"})
    locked = client.post(
        "/api/auth/login", json={"username": "admin", "password": _PASSWORD}
    )
    assert locked.status_code == 401

    response = _run_flow(client, fake_provider)

    assert response.headers["location"] == "/?oidc=1"
    assert client.post("/api/auth/refresh").status_code == 200


def test_login_with_an_unlinked_identity_is_refused_and_creates_nothing(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    _bootstrap_admin(client)

    response = _run_flow(client, fake_provider)

    _assert_failure(response, "/login?oidc_error=not_linked")
    assert _count(client, "users") == 1
    assert _count(client, "oidc_identities") == 0


def test_login_ignores_a_link_from_another_issuer(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    _bootstrap_admin(client)
    _link(
        client,
        _user_id(client, "admin"),
        fake_provider.subject,
        issuer="https://old-idp.test",
    )

    response = _run_flow(client, fake_provider)

    _assert_failure(response, "/login?oidc_error=not_linked")


def test_login_with_a_deactivated_account_is_refused(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    invite = _create_invite(client, admin_token)
    registered = client.post(
        "/api/auth/register",
        json={"username": "bob", "password": _PASSWORD, "token": invite},
    )
    assert registered.status_code == 201, registered.text
    bob_id = _user_id(client, "bob")
    _link(client, bob_id, fake_provider.subject)
    deactivated = client.post(
        f"/api/accounts/{bob_id}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deactivated.status_code == 204, deactivated.text

    response = _run_flow(client, fake_provider)

    _assert_failure(response, "/login?oidc_error=inactive")
    sessions = (
        _auth_db(client)
        .execute(
            "SELECT COUNT(*) AS n FROM refresh_tokens WHERE user_id = ?", (bob_id,)
        )
        .fetchone()
    )
    assert sessions["n"] == 0


# -- signing up with an invite -------------------------------------------------


def test_invite_sign_up_creates_a_linked_passwordless_account(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    invite = _create_invite(client, admin_token)

    response = _run_flow(
        client, fake_provider, "register", username="carol", invite_token=invite
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/?oidc=1"
    _assert_flow_cookie_cleared(response)

    row = (
        _auth_db(client)
        .execute(
            "SELECT id, password_hash, is_admin, is_active FROM users "
            "WHERE username = 'carol'"
        )
        .fetchone()
    )
    assert row["password_hash"] == NO_PASSWORD_HASH
    assert row["is_admin"] == 0
    assert row["is_active"] == 1
    identity = (
        _auth_db(client)
        .execute("SELECT issuer, subject, user_id, display_name FROM oidc_identities")
        .fetchone()
    )
    assert tuple(identity) == (ISSUER, fake_provider.subject, row["id"], "alice")
    assert _invite_consumed_by(client, invite) == row["id"]

    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    claims = jwt.decode(
        refreshed.json()["access_token"], _JWT_SECRET, algorithms=["HS256"]
    )
    assert claims["sub"] == str(row["id"])

    # No password exists to sign in with.
    password_login = client.post(
        "/api/auth/login", json={"username": "carol", "password": NO_PASSWORD_HASH}
    )
    assert password_login.status_code == 401


def test_invite_consumed_before_the_callback_is_refused(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    invite = _create_invite(client, admin_token)
    started = _start(client, "register", username="carol", invite_token=invite)
    assert started.status_code == 200, started.text
    code, state = fake_provider.authorize(started.json()["authorization_url"])
    # Someone else redeems the invite with a password in the meantime.
    used = client.post(
        "/api/auth/register",
        json={"username": "dave", "password": _PASSWORD, "token": invite},
    )
    assert used.status_code == 201, used.text

    response = _callback(client, code=code, state=state)

    _assert_failure(response, "/register?oidc_error=invite_invalid&username=carol")
    users = _auth_db(client).execute("SELECT username FROM users").fetchall()
    assert sorted(row["username"] for row in users) == ["admin", "dave"]
    assert _count(client, "oidc_identities") == 0


def test_username_taken_before_the_callback_rolls_everything_back(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    invite = _create_invite(client, admin_token)
    other_invite = _create_invite(client, admin_token)
    started = _start(client, "register", username="carol", invite_token=invite)
    assert started.status_code == 200, started.text
    code, state = fake_provider.authorize(started.json()["authorization_url"])
    taken = client.post(
        "/api/auth/register",
        json={"username": "carol", "password": _PASSWORD, "token": other_invite},
    )
    assert taken.status_code == 201, taken.text

    response = _callback(client, code=code, state=state)

    _assert_failure(response, "/register?oidc_error=username_taken&username=carol")
    assert invite not in response.headers["location"]
    assert _invite_consumed_by(client, invite) is None
    assert _count(client, "users") == 2
    assert _count(client, "oidc_identities") == 0


def test_invite_sign_up_with_an_identity_linked_elsewhere_is_refused(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    _link(client, _user_id(client, "admin"), fake_provider.subject)
    invite = _create_invite(client, admin_token)

    response = _run_flow(
        client, fake_provider, "register", username="carol", invite_token=invite
    )

    _assert_failure(response, "/register?oidc_error=already_linked&username=carol")
    assert _invite_consumed_by(client, invite) is None
    assert _count(client, "users") == 1


def test_register_start_with_an_invalid_invite_is_refused_without_a_cookie(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    _bootstrap_admin(client)

    response = _start(client, "register", username="carol", invite_token="nope")

    assert response.status_code == 400, response.text
    assert "set-cookie" not in response.headers
    assert not fake_provider.requests


def test_register_start_with_a_taken_username_is_refused_without_a_cookie(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    invite = _create_invite(client, admin_token)

    response = _start(client, "register", username="admin", invite_token=invite)

    assert response.status_code == 409, response.text
    assert "set-cookie" not in response.headers
    assert not fake_provider.requests


@pytest.mark.usefixtures("fake_provider")
def test_register_start_needs_a_username_and_an_invite(client: TestClient) -> None:
    _bootstrap_admin(client)

    response = _start(client, "register", username="carol")

    assert response.status_code == 400, response.text
    assert "set-cookie" not in response.headers


@pytest.mark.usefixtures("fake_provider")
def test_start_refuses_an_unknown_intent(client: TestClient) -> None:
    response = _start(client, "merge")

    assert response.status_code == 422, response.text
    assert "set-cookie" not in response.headers


def test_setup_token_bootstrap_still_works_and_is_not_offered_through_the_provider(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    refused = _start(client, "register", username="root", invite_token=_SETUP_TOKEN)
    assert refused.status_code == 400, refused.text
    assert "set-cookie" not in refused.headers
    assert not fake_provider.requests

    registered = client.post(
        "/api/auth/register",
        json={"username": "root", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["is_admin"] is True


# -- linking from Settings -----------------------------------------------------


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _invited_password_user(
    client: TestClient, admin_token: str, username: str = "bob"
) -> str:
    """A non-admin account with a password, through an invite; returns its
    access token."""
    invite = _create_invite(client, admin_token)
    registered = client.post(
        "/api/auth/register",
        json={"username": username, "password": _PASSWORD, "token": invite},
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login", json={"username": username, "password": _PASSWORD}
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


def _start_link(
    client: TestClient, token: str, password: str | None = _PASSWORD
) -> httpx.Response:
    fields = {} if password is None else {"current_password": password}
    return _start(client, "link", headers=_bearer(token), **fields)


def _run_link_flow(
    client: TestClient,
    provider: FakeProvider,
    token: str,
    password: str | None = _PASSWORD,
) -> httpx.Response:
    started = _start_link(client, token, password)
    assert started.status_code == 200, started.text
    code, state = provider.authorize(started.json()["authorization_url"])
    return _callback(client, code=code, state=state)


def _identities(client: TestClient) -> list[tuple[str, int]]:
    rows = (
        _auth_db(client)
        .execute("SELECT subject, user_id FROM oidc_identities ORDER BY subject")
        .fetchall()
    )
    return [(row["subject"], row["user_id"]) for row in rows]


def test_password_user_links_from_settings(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)
    sessions_before = _count(client, "refresh_tokens")

    response = _run_link_flow(client, fake_provider, bob_token)

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/settings"
    # Linking adds a sign-in method; it is not a sign-in.
    assert "refresh_token" not in _set_cookies(response)
    assert _count(client, "refresh_tokens") == sessions_before
    _assert_flow_cookie_cleared(response)

    identity = client.get("/api/account/identity", headers=_bearer(bob_token))
    assert identity.status_code == 200, identity.text
    assert identity.json() == {
        "linked": True,
        "provider_name": "SSO",
        "display_name": "alice",
        "has_password": True,
        "password_usable": True,
    }
    assert _identities(client) == [(fake_provider.subject, _user_id(client, "bob"))]

    # The linked identity now signs bob in.
    signed_in = _run_flow(client, fake_provider)
    assert signed_in.headers["location"] == "/?oidc=1"


def test_link_to_an_identity_linked_elsewhere_is_refused(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    admin_id = _user_id(client, "admin")
    _link(client, admin_id, fake_provider.subject)
    bob_token = _invited_password_user(client, admin_token)

    response = _run_link_flow(client, fake_provider, bob_token)

    _assert_failure(response, "/settings?oidc_error=already_linked")
    assert _identities(client) == [(fake_provider.subject, admin_id)]


def test_link_when_the_caller_already_has_another_identity_is_refused(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)
    bob_id = _user_id(client, "bob")
    _link(client, bob_id, "another-provider-user")

    response = _run_link_flow(client, fake_provider, bob_token)

    _assert_failure(response, "/settings?oidc_error=already_linked")
    assert _identities(client) == [("another-provider-user", bob_id)]


def test_relinking_the_callers_own_identity_is_a_no_op(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)
    bob_id = _user_id(client, "bob")
    _link(client, bob_id, fake_provider.subject)

    response = _run_link_flow(client, fake_provider, bob_token)

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/settings"
    assert "refresh_token" not in _set_cookies(response)
    assert _identities(client) == [(fake_provider.subject, bob_id)]


def test_link_ignores_a_link_from_another_issuer(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)
    bob_id = _user_id(client, "bob")
    _link(client, bob_id, "old-subject", issuer="https://old-idp.test")

    response = _run_link_flow(client, fake_provider, bob_token)

    assert response.headers["location"] == "/settings"
    rows = (
        _auth_db(client)
        .execute("SELECT issuer, subject FROM oidc_identities ORDER BY issuer")
        .fetchall()
    )
    assert [tuple(row) for row in rows] == [
        (ISSUER, fake_provider.subject),
        ("https://old-idp.test", "old-subject"),
    ]


def test_link_start_refuses_a_personal_api_token(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    created = client.post(
        "/api/tokens", json={"name": "laptop"}, headers=_bearer(admin_token)
    )
    assert created.status_code == 201, created.text

    response = _start_link(client, created.json()["token"])

    assert response.status_code == 403, response.text
    assert "set-cookie" not in response.headers
    assert not fake_provider.requests


@pytest.mark.parametrize("headers", [None, _bearer("not-a-real-token")])
def test_link_start_needs_a_signed_in_session(
    fake_provider: FakeProvider,
    client: TestClient,
    headers: dict[str, str] | None,
) -> None:
    _bootstrap_admin(client)

    response = _start(client, "link", headers=headers, current_password=_PASSWORD)

    assert response.status_code == 401, response.text
    assert "set-cookie" not in response.headers
    assert not fake_provider.requests


@pytest.mark.parametrize("password", [None, "not my password"])
def test_link_start_without_the_right_password_is_refused(
    fake_provider: FakeProvider, client: TestClient, password: str | None
) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)

    response = _start_link(client, bob_token, password)

    assert response.status_code == 403, response.text
    assert "set-cookie" not in response.headers
    assert not fake_provider.requests
    failed = (
        _auth_db(client)
        .execute("SELECT failed_login_attempts FROM users WHERE username = 'bob'")
        .fetchone()
    )
    assert failed["failed_login_attempts"] == 1


@pytest.mark.usefixtures("fake_provider")
def test_wrong_link_passwords_lock_the_account(client: TestClient) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)

    for _ in range(5):
        assert _start_link(client, bob_token, "wrong guess").status_code == 403

    login = client.post(
        "/api/auth/login", json={"username": "bob", "password": _PASSWORD}
    )
    assert login.status_code == 401
    # Locked out here too, even with the right password.
    assert _start_link(client, bob_token).status_code == 403


def test_passwordless_account_links_without_a_password(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    invite = _create_invite(client, admin_token)
    signed_up = _run_flow(
        client, fake_provider, "register", username="carol", invite_token=invite
    )
    assert signed_up.headers["location"] == "/?oidc=1"
    carol_token = client.post("/api/auth/refresh").json()["access_token"]
    # As after the operator switched provider: carol's link is under the
    # old issuer, so she has none for the configured one.
    with _auth_db(client) as auth_db:
        auth_db.execute("UPDATE oidc_identities SET issuer = 'https://old-idp.test'")

    response = _run_link_flow(client, fake_provider, carol_token, password=None)

    assert response.headers["location"] == "/settings"
    assert len(_identities(client)) == 2


def test_link_for_an_account_deactivated_meanwhile_is_refused(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)
    bob_id = _user_id(client, "bob")
    started = _start_link(client, bob_token)
    assert started.status_code == 200, started.text
    code, state = fake_provider.authorize(started.json()["authorization_url"])
    deactivated = client.post(
        f"/api/accounts/{bob_id}/deactivate", headers=_bearer(admin_token)
    )
    assert deactivated.status_code == 204, deactivated.text

    response = _callback(client, code=code, state=state)

    _assert_failure(response, "/settings?oidc_error=inactive")
    assert _count(client, "oidc_identities") == 0


def test_unlinking_a_password_account_stops_provider_sign_in(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    bob_token = _invited_password_user(client, admin_token)
    linked = _run_link_flow(client, fake_provider, bob_token)
    assert linked.headers["location"] == "/settings"

    unlinked = client.delete("/api/account/identity", headers=_bearer(bob_token))

    assert unlinked.status_code == 204, unlinked.text
    assert _count(client, "oidc_identities") == 0
    _assert_failure(_run_flow(client, fake_provider), "/login?oidc_error=not_linked")


# -- admin group sync ----------------------------------------------------------

# `configure_oidc_env()` turns admin sync on for a `client` that already
# exists: the routes read `get_settings()` per request.
_ADMIN_GROUP = "cerebrum-admins"


def _is_admin(client: TestClient, username: str) -> bool:
    row = (
        _auth_db(client)
        .execute("SELECT is_admin FROM users WHERE username = ?", (username,))
        .fetchone()
    )
    assert row is not None, f"no user {username!r}"
    return bool(row["is_admin"])


def _set_admin(client: TestClient, username: str, is_admin: bool = True) -> None:
    with _auth_db(client) as auth_db:
        auth_db.execute(
            "UPDATE users SET is_admin = ? WHERE username = ?",
            (int(is_admin), username),
        )


def _provider_sign_in(
    client: TestClient, provider: FakeProvider, subject: str, groups: list[str]
) -> None:
    """Sign in through the provider as `subject`, a member of `groups`."""
    provider.subject = subject
    provider.extra_claims["groups"] = groups
    response = _run_flow(client, provider)
    assert response.headers["location"] == "/?oidc=1", response.text


def _provider_only_user(
    client: TestClient, provider: FakeProvider, admin_token: str, username: str
) -> None:
    """A passwordless account signed up through the provider, linked to the
    subject `username`."""
    invite = _create_invite(client, admin_token)
    provider.subject = username
    signed_up = _run_flow(
        client, provider, "register", username=username, invite_token=invite
    )
    assert signed_up.headers["location"] == "/?oidc=1", signed_up.text


def _skipped_demotions(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "cerebrum.accounts.oidc_accounts"
        and record.levelno == logging.WARNING
    ]


def test_admin_group_membership_promotes_and_its_loss_demotes(
    fake_provider: FakeProvider, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_token = _bootstrap_admin(client)
    _invited_password_user(client, admin_token)
    _link(client, _user_id(client, "bob"), "bob-subject")
    configure_oidc_env(monkeypatch, OIDC_ADMIN_GROUP=_ADMIN_GROUP)

    _provider_sign_in(client, fake_provider, "bob-subject", ["staff", _ADMIN_GROUP])
    assert _is_admin(client, "bob") is True

    _provider_sign_in(client, fake_provider, "bob-subject", ["staff"])
    assert _is_admin(client, "bob") is False


def test_admin_removed_from_the_group_is_demoted_when_another_admin_has_a_password(
    fake_provider: FakeProvider, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_token = _bootstrap_admin(client)
    _invited_password_user(client, admin_token)
    _set_admin(client, "bob")
    _link(client, _user_id(client, "bob"), "bob-subject")
    configure_oidc_env(monkeypatch, OIDC_ADMIN_GROUP=_ADMIN_GROUP)

    _provider_sign_in(client, fake_provider, "bob-subject", [])

    assert _is_admin(client, "bob") is False
    assert _is_admin(client, "admin") is True


def test_demoting_the_only_active_admin_is_skipped_and_logged(
    fake_provider: FakeProvider,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    admin_token = _bootstrap_admin(client)
    _provider_only_user(client, fake_provider, admin_token, "carol")
    _set_admin(client, "carol")
    # The bootstrap admin's password no longer counts: the account is
    # deactivated.
    with _auth_db(client) as auth_db:
        auth_db.execute("UPDATE users SET is_active = 0 WHERE username = 'admin'")
    configure_oidc_env(monkeypatch, OIDC_ADMIN_GROUP=_ADMIN_GROUP)

    with caplog.at_level(logging.WARNING, logger="cerebrum.accounts.oidc_accounts"):
        _provider_sign_in(client, fake_provider, "carol", ["staff"])

    assert _is_admin(client, "carol") is True
    assert len(_skipped_demotions(caplog)) == 1


def test_demotion_is_skipped_when_no_other_admin_has_a_password(
    fake_provider: FakeProvider,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    admin_token = _bootstrap_admin(client)
    _link(client, _user_id(client, "admin"), "admin-subject")
    # Another admin, but one with no password to fall back on.
    _provider_only_user(client, fake_provider, admin_token, "carol")
    _set_admin(client, "carol")
    configure_oidc_env(monkeypatch, OIDC_ADMIN_GROUP=_ADMIN_GROUP)

    with caplog.at_level(logging.WARNING, logger="cerebrum.accounts.oidc_accounts"):
        _provider_sign_in(client, fake_provider, "admin-subject", ["staff"])

    assert _is_admin(client, "admin") is True
    assert len(_skipped_demotions(caplog)) == 1


def test_invited_member_of_the_admin_group_starts_as_a_non_admin(
    fake_provider: FakeProvider, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_token = _bootstrap_admin(client)
    configure_oidc_env(monkeypatch, OIDC_ADMIN_GROUP=_ADMIN_GROUP)
    fake_provider.extra_claims["groups"] = [_ADMIN_GROUP]

    _provider_only_user(client, fake_provider, admin_token, "carol")
    assert _is_admin(client, "carol") is False

    _provider_sign_in(client, fake_provider, "carol", [_ADMIN_GROUP])
    assert _is_admin(client, "carol") is True


def test_without_an_admin_group_provider_sign_in_never_changes_admin(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    admin_token = _bootstrap_admin(client)
    _invited_password_user(client, admin_token)
    _link(client, _user_id(client, "admin"), "admin-subject")
    _link(client, _user_id(client, "bob"), "bob-subject")

    _provider_sign_in(client, fake_provider, "admin-subject", [])
    _provider_sign_in(client, fake_provider, "bob-subject", [_ADMIN_GROUP])

    assert _is_admin(client, "admin") is True
    assert _is_admin(client, "bob") is False


def test_password_sign_in_never_changes_admin(
    fake_provider: FakeProvider, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_token = _bootstrap_admin(client)
    _invited_password_user(client, admin_token)
    _link(client, _user_id(client, "admin"), "admin-subject")
    _link(client, _user_id(client, "bob"), fake_provider.subject)
    configure_oidc_env(monkeypatch, OIDC_ADMIN_GROUP=_ADMIN_GROUP)

    for username in ("admin", "bob"):
        login = client.post(
            "/api/auth/login", json={"username": username, "password": _PASSWORD}
        )
        assert login.status_code == 200, login.text

    # The admin is in no group and bob is in the admin group (the fake
    # provider's default), yet only a provider sign-in would act on that.
    assert _is_admin(client, "admin") is True
    assert _is_admin(client, "bob") is False


# -- failures and the flow cookie ----------------------------------------------


@pytest.mark.usefixtures("fake_provider")
def test_callback_without_a_flow_cookie_is_expired(client: TestClient) -> None:
    response = _callback(client, code="some-code", state="some-state")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?oidc_error=expired"


def test_provider_error_is_reported_without_echoing_the_provider(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    started = _start(client)
    assert started.status_code == 200, started.text
    _, state = fake_provider.authorize(started.json()["authorization_url"])

    response = _callback(
        client,
        error="access_denied",
        error_description="The user said <b>no</b>",
        state=state,
    )

    _assert_failure(response, "/login?oidc_error=provider_error")
    assert not fake_provider.token_requests


@pytest.mark.usefixtures("fake_provider")
def test_provider_error_on_sign_up_returns_to_the_register_page(
    client: TestClient,
) -> None:
    admin_token = _bootstrap_admin(client)
    invite = _create_invite(client, admin_token)
    started = _start(client, "register", username="carol", invite_token=invite)
    assert started.status_code == 200, started.text

    response = _callback(client, error="access_denied")

    _assert_failure(response, "/register?oidc_error=provider_error&username=carol")


def test_callback_without_a_code_is_a_provider_error(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    started = _start(client)
    assert started.status_code == 200, started.text
    _, state = fake_provider.authorize(started.json()["authorization_url"])

    response = _callback(client, state=state)

    _assert_failure(response, "/login?oidc_error=provider_error")


def test_replayed_callback_fails_because_the_cookie_was_cleared(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    _bootstrap_admin(client)
    _link(client, _user_id(client, "admin"), fake_provider.subject)
    started = _start(client)
    code, state = fake_provider.authorize(started.json()["authorization_url"])
    first = _callback(client, code=code, state=state)
    assert first.headers["location"] == "/?oidc=1"

    replayed = _callback(client, code=code, state=state)

    assert replayed.status_code == 303
    assert replayed.headers["location"] == "/login?oidc_error=expired"
    assert len(fake_provider.token_requests) == 1


def test_start_reports_an_unreachable_provider(
    fake_provider: FakeProvider, client: TestClient
) -> None:
    fake_provider.unreachable = True

    response = _start(client)

    assert response.status_code == 502, response.text
    assert "set-cookie" not in response.headers


# -- origin, cookie flags and configuration ------------------------------------


@pytest.mark.usefixtures("fake_provider")
def test_redirect_uri_and_cookie_follow_the_forwarded_origin(
    client: TestClient,
) -> None:
    response = _start(
        client,
        headers={"Host": "fedora.example:8443", "X-Forwarded-Proto": "https"},
    )

    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert query["redirect_uri"] == [
        "https://fedora.example:8443/api/auth/oidc/callback"
    ]
    flow_cookie = _set_cookies(response)["oidc_flow"]
    assert "secure" in flow_cookie
    assert "httponly" in flow_cookie
    assert "samesite=lax" in flow_cookie
    assert "path=/api/auth/oidc/callback" in flow_cookie
    assert "max-age=600" in flow_cookie


@pytest.mark.usefixtures("fake_provider")
def test_flow_cookie_is_not_secure_over_plain_http(client: TestClient) -> None:
    response = _start(client)

    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert query["redirect_uri"] == ["http://testserver/api/auth/oidc/callback"]
    flow_cookie = _set_cookies(response)["oidc_flow"]
    assert "secure" not in flow_cookie
    assert "samesite=lax" in flow_cookie


def test_routes_are_not_found_without_a_provider(client: TestClient) -> None:
    assert _start(client).status_code == 404
    assert _callback(client, code="c", state="s").status_code == 404
