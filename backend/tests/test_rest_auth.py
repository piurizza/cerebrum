from __future__ import annotations

import re
import sqlite3

from fastapi.testclient import TestClient

from tests.mcp_test_support import issue_test_access_token
from tests.route_test_support import iter_routes

# The 4 REST routes that must stay reachable with no `Authorization`
# header at all -- every other route included into `api_router` picks up
# `get_current_identity` as a default dependency (see router.py) and must
# reject both a missing and a wrong bearer credential.
_EXEMPT_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/refresh"),
}

_PATH_PARAM = re.compile(r"\{[^/}]+\}")

_SETUP_TOKEN = "y" * 32
_PASSWORD = "correct horse battery staple"


def _concrete_path(path: str) -> str:
    """Substitute a placeholder value into any path-parameter segment
    (e.g. `{path:path}`) so a request reaches the route's own dependency
    graph -- and therefore `get_current_identity` -- instead of 404ing on
    an unresolved template. REST-specific, unlike `route_test_support.
    iter_routes()` itself, which knows nothing about path parameters."""
    return _PATH_PARAM.sub("placeholder", path)


def _rest_routes(client: TestClient) -> list[tuple[str, str]]:
    """The actual mounted REST route table, walked fresh off the
    fully-assembled app (not a hand-maintained list) -- so a future route
    that forgets auth is caught structurally. Restricted to `/api/*`
    paths, excluding the `/api/mcp` mount: that mount carries a JSON-RPC
    protocol authenticated through a completely different mechanism
    (`SharedFunctionTokenVerifier`, exercised by `test_mcp_auth.py`'s own
    route-enumeration test), not `api_router`'s `get_current_identity`
    dependency, so a plain REST-style request against it wouldn't
    exercise anything this test cares about. FastAPI's own `/docs`,
    `/openapi.json`, etc. are excluded the same way (they don't start
    with `/api/`).
    """
    return [
        (method, path)
        for method, path in iter_routes(client.app.routes)
        if path.startswith("/api/") and not path.startswith("/api/mcp")
    ]


def test_every_non_exempt_rest_route_rejects_missing_and_wrong_credential(
    client: TestClient,
) -> None:
    routes = _rest_routes(client)
    assert routes, "expected at least one REST route on the app"
    protected_routes = [route for route in routes if route not in _EXEMPT_ROUTES]
    assert protected_routes, "expected at least one protected REST route"

    for method, path in protected_routes:
        concrete_path = _concrete_path(path)

        no_credential_response = client.request(method, concrete_path)
        assert no_credential_response.status_code == 401, (
            f"{method} {concrete_path} did not reject a request with no credential"
        )

        wrong_credential_response = client.request(
            method, concrete_path, headers={"Authorization": "Bearer garbage"}
        )
        assert wrong_credential_response.status_code == 401, (
            f"{method} {concrete_path} did not reject a request with a wrong credential"
        )


def test_health_reachable_with_no_credential(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code != 401


def test_register_reachable_with_no_credential(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": "rest-auth-test",
            "password": _PASSWORD,
            "token": _SETUP_TOKEN,
        },
    )
    assert response.status_code != 401


def test_login_reachable_with_no_credential(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={
            "username": "rest-auth-test",
            "password": _PASSWORD,
            "token": _SETUP_TOKEN,
        },
    )

    response = client.post(
        "/api/auth/login", json={"username": "rest-auth-test", "password": _PASSWORD}
    )
    assert response.status_code != 401


def test_refresh_reachable_with_no_authorization_header(client: TestClient) -> None:
    """`refresh()` authenticates via its own `refresh_token` cookie, never
    a bearer credential (see `api/auth.py`) -- confirmed here by logging
    in first (which leaves a valid refresh cookie in `client`'s cookie
    jar, set automatically by `TestClient`) and then calling `refresh()`
    with deliberately no `Authorization` header, getting a normal
    (non-401) response rather than being rejected for "missing" auth."""
    client.post(
        "/api/auth/register",
        json={
            "username": "rest-auth-test",
            "password": _PASSWORD,
            "token": _SETUP_TOKEN,
        },
    )
    client.post(
        "/api/auth/login", json={"username": "rest-auth-test", "password": _PASSWORD}
    )

    response = client.post("/api/auth/refresh")
    assert response.status_code != 401


def test_valid_access_token_reaches_a_real_protected_route(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/api/notes")
    assert response.status_code == 200


def test_deactivated_accounts_token_rejected_on_next_rest_request(
    client: TestClient,
) -> None:
    token = issue_test_access_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/notes", headers=headers).status_code == 200

    auth_db: sqlite3.Connection = client.app.state.auth_db
    with auth_db:
        auth_db.execute("UPDATE users SET is_active = 0")

    response = client.get("/api/notes", headers=headers)
    assert response.status_code == 401
