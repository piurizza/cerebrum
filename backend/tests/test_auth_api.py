from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from cerebrum.accounts.service import NO_PASSWORD_HASH
from cerebrum.settings import get_settings

# Matches conftest.py's `client` fixture, which sets AUTH_SETUP_TOKEN to
# this exact value before constructing the app.
_SETUP_TOKEN = "y" * 32
_PASSWORD = "correct horse battery staple"

# A second `PasswordHasher` instance purely for test setup (inserting a
# second account directly, bypassing `/api/auth/register`'s invite-token
# requirement -- invite generation isn't wired up until a later unit) --
# not the same singleton `accounts/service.py` uses internally, but
# functionally identical since `PasswordHasher()` is stateless config.
_password_hasher = PasswordHasher()


def _insert_user(
    client: TestClient, username: str, password: str, *, is_active: bool = True
) -> None:
    auth_db: sqlite3.Connection = client.app.state.auth_db
    with auth_db:
        auth_db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, is_active, created_at)
            VALUES (?, ?, 0, ?, ?)
            """,
            (
                username,
                _password_hasher.hash(password),
                int(is_active),
                datetime.now(UTC).isoformat(),
            ),
        )


def _insert_user_with_hash(
    client: TestClient, username: str, password_hash: str
) -> None:
    """Insert an account whose `password_hash` is stored verbatim -- for the
    password-less sentinel and for a corrupt value no hasher would produce."""
    auth_db: sqlite3.Connection = client.app.state.auth_db
    with auth_db:
        auth_db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, is_active, created_at)
            VALUES (?, ?, 0, 1, ?)
            """,
            (username, password_hash, datetime.now(UTC).isoformat()),
        )


def _failed_login_attempts(client: TestClient, username: str) -> int:
    auth_db: sqlite3.Connection = client.app.state.auth_db
    row = auth_db.execute(
        "SELECT failed_login_attempts FROM users WHERE username = ?", (username,)
    ).fetchone()
    return int(row["failed_login_attempts"])


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


def test_login_with_correct_credentials_returns_token_and_refresh_cookie(
    client: TestClient,
) -> None:
    client.post(
        "/api/auth/register",
        json={"username": "alice", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )

    response = client.post(
        "/api/auth/login", json={"username": "alice", "password": _PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]

    # `response.cookies` doesn't expose flags like HttpOnly/SameSite/Path
    # -- inspect the raw `Set-Cookie` header for those instead.
    set_cookie_header = response.headers["set-cookie"].lower()
    assert "refresh_token=" in set_cookie_header
    assert "httponly" in set_cookie_header
    assert "samesite=strict" in set_cookie_header
    assert "path=/api/auth/refresh" in set_cookie_header
    # Don't hardcode an expectation of True -- match whatever
    # `auth_cookie_secure` actually resolves to in this test environment.
    assert ("secure" in set_cookie_header) == get_settings().auth_cookie_secure


def test_wrong_password_and_nonexistent_username_return_identical_401(
    client: TestClient,
) -> None:
    client.post(
        "/api/auth/register",
        json={"username": "bob", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )

    wrong_password_response = client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "totally wrong password"},
    )
    nonexistent_response = client.post(
        "/api/auth/login", json={"username": "no-such-user", "password": _PASSWORD}
    )

    assert wrong_password_response.status_code == 401
    assert nonexistent_response.status_code == 401
    assert wrong_password_response.json() == nonexistent_response.json()


def test_login_for_deactivated_account_fails_like_wrong_credentials(
    client: TestClient,
) -> None:
    _insert_user(client, "carol", _PASSWORD, is_active=False)

    deactivated_response = client.post(
        "/api/auth/login", json={"username": "carol", "password": _PASSWORD}
    )
    baseline_response = client.post(
        "/api/auth/login", json={"username": "carol", "password": "wrong password"}
    )

    assert deactivated_response.status_code == 401
    assert deactivated_response.json() == baseline_response.json()


def test_access_token_is_valid_jwt_with_expected_ttl_and_no_is_admin_claim(
    client: TestClient,
) -> None:
    client.post(
        "/api/auth/register",
        json={"username": "dave", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )
    login_response = client.post(
        "/api/auth/login", json={"username": "dave", "password": _PASSWORD}
    )
    access_token = login_response.json()["access_token"]

    settings = get_settings()
    payload = jwt.decode(
        access_token, settings.auth_jwt_secret.get_secret_value(), algorithms=["HS256"]
    )

    assert "is_admin" not in payload
    expected_exp = datetime.now(UTC) + timedelta(
        minutes=settings.auth_access_token_ttl_minutes
    )
    actual_exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    assert abs((actual_exp - expected_exp).total_seconds()) < 5


def test_login_route_reachable_without_authorization_header(
    client: TestClient,
) -> None:
    client.post(
        "/api/auth/register",
        json={"username": "erin", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )

    # No `Authorization` header is set anywhere in this request -- login
    # lives on `unauthenticated_router`, and it would be self-defeating for
    # the endpoint that issues the credential to require one.
    response = client.post(
        "/api/auth/login", json={"username": "erin", "password": _PASSWORD}
    )

    assert response.status_code not in (401, 403)


def test_login_timing_for_nonexistent_username_and_wrong_password_is_comparable(
    client: TestClient,
) -> None:
    """Loose bound, not a strict timing guarantee -- just proving the
    dummy-hash timing-parity path (`accounts/service.py`'s
    `_DUMMY_PASSWORD_HASH`) actually executes for a nonexistent username,
    rather than being flaky under CI jitter."""
    client.post(
        "/api/auth/register",
        json={"username": "frank", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )

    start = time.monotonic()
    client.post(
        "/api/auth/login",
        json={"username": "no-such-user-at-all", "password": _PASSWORD},
    )
    nonexistent_duration = time.monotonic() - start

    start = time.monotonic()
    client.post(
        "/api/auth/login",
        json={"username": "frank", "password": "totally wrong password"},
    )
    wrong_password_duration = time.monotonic() - start

    slower = max(nonexistent_duration, wrong_password_duration)
    faster = max(min(nonexistent_duration, wrong_password_duration), 1e-6)
    assert slower / faster < 3


def test_five_failed_logins_lock_account_until_cleared(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"username": "grace", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )

    for _ in range(5):
        response = client.post(
            "/api/auth/login", json={"username": "grace", "password": "wrong password"}
        )
        assert response.status_code == 401

    # Sixth attempt, even with the correct password, still fails while locked.
    locked_response = client.post(
        "/api/auth/login", json={"username": "grace", "password": _PASSWORD}
    )
    assert locked_response.status_code == 401

    auth_db: sqlite3.Connection = client.app.state.auth_db
    with auth_db:
        auth_db.execute("UPDATE users SET locked_until = NULL WHERE username = 'grace'")

    unlocked_response = client.post(
        "/api/auth/login", json={"username": "grace", "password": _PASSWORD}
    )
    assert unlocked_response.status_code == 200

    row = auth_db.execute(
        "SELECT failed_login_attempts FROM users WHERE username = 'grace'"
    ).fetchone()
    assert row["failed_login_attempts"] == 0


def test_lockout_for_one_account_does_not_affect_another(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"username": "henry", "password": _PASSWORD, "token": _SETUP_TOKEN},
    )
    _insert_user(client, "iris", _PASSWORD)

    for _ in range(5):
        response = client.post(
            "/api/auth/login", json={"username": "henry", "password": "wrong password"}
        )
        assert response.status_code == 401

    locked_response = client.post(
        "/api/auth/login", json={"username": "henry", "password": _PASSWORD}
    )
    assert locked_response.status_code == 401

    other_account_response = client.post(
        "/api/auth/login", json={"username": "iris", "password": _PASSWORD}
    )
    assert other_account_response.status_code == 200


def _register_and_login(client: TestClient, username: str) -> None:
    client.post(
        "/api/auth/register",
        json={"username": username, "password": _PASSWORD, "token": _SETUP_TOKEN},
    )
    login_response = client.post(
        "/api/auth/login", json={"username": username, "password": _PASSWORD}
    )
    assert login_response.status_code == 200
    # `TestClient` persists cookies across requests on the same instance
    # (it wraps a `requests`-style session), so the `refresh_token` cookie
    # set by `/login` above is already attached for subsequent calls.


def test_refresh_with_valid_cookie_returns_new_access_token_and_rotates_cookie(
    client: TestClient,
) -> None:
    _register_and_login(client, "julia")
    old_refresh_cookie = client.cookies.get("refresh_token")

    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"]
    set_cookie_header = response.headers["set-cookie"].lower()
    assert "refresh_token=" in set_cookie_header
    assert "httponly" in set_cookie_header
    assert "samesite=strict" in set_cookie_header
    assert "path=/api/auth/refresh" in set_cookie_header
    assert client.cookies.get("refresh_token") != old_refresh_cookie


def test_refresh_rotated_access_token_is_a_valid_jwt_for_the_same_user(
    client: TestClient,
) -> None:
    _register_and_login(client, "kevin")

    response = client.post("/api/auth/refresh")

    settings = get_settings()
    payload = jwt.decode(
        response.json()["access_token"],
        settings.auth_jwt_secret.get_secret_value(),
        algorithms=["HS256"],
    )
    assert "sub" in payload


def test_refresh_with_no_cookie_present_returns_401_not_500(
    client: TestClient,
) -> None:
    response = client.post("/api/auth/refresh")

    assert response.status_code == 401


def test_refresh_with_reused_old_cookie_returns_401(client: TestClient) -> None:
    _register_and_login(client, "laura")
    old_refresh_cookie = client.cookies.get("refresh_token")

    first_response = client.post("/api/auth/refresh")
    assert first_response.status_code == 200

    # Present the now-rotated-away original token again by setting it
    # directly on the client's cookie jar, overriding the already-rotated
    # value the successful refresh above just stored there.
    client.cookies.set("refresh_token", old_refresh_cookie)
    reuse_response = client.post("/api/auth/refresh")

    assert reuse_response.status_code == 401


def test_refresh_with_garbage_cookie_value_returns_401(client: TestClient) -> None:
    client.cookies.set("refresh_token", "not-a-real-token")

    response = client.post("/api/auth/refresh")

    assert response.status_code == 401


def test_refresh_route_reachable_without_authorization_header(
    client: TestClient,
) -> None:
    _register_and_login(client, "mallory")

    # No `Authorization` header is set anywhere in this request -- refresh
    # lives on `unauthenticated_router` and authenticates via its own
    # cookie, not a bearer credential.
    response = client.post("/api/auth/refresh")

    assert response.status_code not in (401, 403)


def test_login_for_password_less_account_returns_generic_401_and_counts_failure(
    client: TestClient,
) -> None:
    _insert_user_with_hash(client, "jules", NO_PASSWORD_HASH)

    response = client.post(
        "/api/auth/login", json={"username": "jules", "password": _PASSWORD}
    )
    baseline = client.post(
        "/api/auth/login", json={"username": "no-such-user", "password": _PASSWORD}
    )

    assert response.status_code == 401
    assert response.json() == baseline.json()
    assert _failed_login_attempts(client, "jules") == 1


@pytest.mark.parametrize(
    "corrupt_hash",
    [
        "not-a-hash",
        "",
        "$argon2id$v=19$m=65536,t=3,p=4$truncated",
    ],
)
def test_login_for_account_with_corrupt_hash_returns_401_not_500(
    client: TestClient, corrupt_hash: str
) -> None:
    _insert_user_with_hash(client, "kim", corrupt_hash)

    response = client.post(
        "/api/auth/login", json={"username": "kim", "password": _PASSWORD}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert _failed_login_attempts(client, "kim") == 1


# --- GET /api/auth/methods ---------------------------------------------------

_OIDC_ISSUER = "https://idp.example/realms/home"
_OIDC_CLIENT_ID = "cerebrum-client-id"


def _configure_oidc(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    """Turn the provider on for a `client` that already exists. The routes
    read `get_settings()` per request, so clearing its cache is enough; the
    `client` fixture clears it again on teardown."""
    monkeypatch.setenv("OIDC_ISSUER", _OIDC_ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", _OIDC_CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "client-secret-value")
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_auth_methods_without_a_provider_offers_password_only(
    client: TestClient,
) -> None:
    response = client.get("/api/auth/methods")

    assert response.status_code == 200
    assert response.json() == {"password_login": True, "oidc": None}


def test_auth_methods_with_a_provider_names_it_without_leaking_its_config(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_oidc(monkeypatch, OIDC_PROVIDER_NAME="Authentik")

    response = client.get("/api/auth/methods")

    assert response.status_code == 200
    assert response.json() == {
        "password_login": True,
        "oidc": {"provider_name": "Authentik"},
    }
    assert _OIDC_ISSUER not in response.text
    assert "idp.example" not in response.text
    assert _OIDC_CLIENT_ID not in response.text
    assert "client-secret-value" not in response.text


def test_auth_methods_reports_password_login_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_oidc(monkeypatch, AUTH_PASSWORD_LOGIN="false")

    response = client.get("/api/auth/methods")

    assert response.json() == {
        "password_login": False,
        "oidc": {"provider_name": "SSO"},
    }
