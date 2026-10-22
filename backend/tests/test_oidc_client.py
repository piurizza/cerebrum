"""The OpenID Connect client core (`accounts/oidc.py`) against the fake
provider in `tests/oidc_fake.py`.

The ID-token rejection tests are the security boundary: each one makes the
provider misbehave in one way and checks the flow fails closed."""

from __future__ import annotations

import ast
import asyncio
import base64
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs

import jwt
import pytest
from fastapi.testclient import TestClient

from cerebrum.accounts import oidc
from cerebrum.accounts.oidc import (
    FlowIntent,
    FlowResult,
    LinkIntent,
    LoginIntent,
    OidcError,
    RegisterIntent,
)
from cerebrum.main import create_app
from cerebrum.settings import get_settings
from tests.oidc_fake import (
    CLIENT_ID,
    CLIENT_SECRET,
    ISSUER,
    REDIRECT_URI,
    FakeProvider,
    configure_oidc_env,
    pkce_challenge,
)

_JWT_SECRET = "x" * 32


def _start(intent: FlowIntent | None = None) -> oidc.FlowStart:
    return asyncio.run(oidc.start_flow(REDIRECT_URI, intent or LoginIntent()))


def _run_flow(provider: FakeProvider, intent: FlowIntent | None = None) -> FlowResult:
    started = _start(intent)
    code, state = provider.authorize(started.authorization_url)
    return asyncio.run(oidc.finish_flow(started.flow_cookie, state=state, code=code))


def _refused(provider: FakeProvider) -> OidcError:
    with pytest.raises(OidcError) as excinfo:
        _run_flow(provider)
    return excinfo.value


def _token_form(provider: FakeProvider) -> dict[str, str]:
    (request,) = provider.token_requests
    form = parse_qs(request.content.decode("ascii"))
    return {key: values[0] for key, values in form.items()}


def _flow_claims(flow_cookie: str) -> dict[str, object]:
    claims: dict[str, object] = jwt.decode(
        flow_cookie,
        _JWT_SECRET,
        algorithms=["HS256"],
        audience=oidc.FLOW_COOKIE_AUDIENCE,
    )
    return claims


# -- happy path ----------------------------------------------------------------


def test_start_then_finish_returns_the_verified_identity(
    fake_provider: FakeProvider,
) -> None:
    result = _run_flow(fake_provider)

    assert result.identity == oidc.VerifiedIdentity(
        issuer=ISSUER,
        subject="provider-user-1",
        groups=frozenset({"staff", "cerebrum-admins"}),
        display_name="alice",
    )
    assert result.intent == LoginIntent()


def test_display_name_falls_back_to_email(fake_provider: FakeProvider) -> None:
    fake_provider.dropped_claims = {"preferred_username"}

    assert _run_flow(fake_provider).identity.display_name == "alice@example.test"


@pytest.mark.parametrize(
    "intent",
    [
        LoginIntent(),
        RegisterIntent(username="newbie", invite_hash="ab" * 32),
        LinkIntent(user_id=7),
    ],
)
def test_intent_round_trips_through_the_flow_cookie(
    fake_provider: FakeProvider, intent: FlowIntent
) -> None:
    assert _run_flow(fake_provider, intent).intent == intent


@pytest.mark.usefixtures("fake_provider")
def test_link_user_id_is_never_the_flow_cookie_subject() -> None:
    claims = _flow_claims(_start(LinkIntent(user_id=7)).flow_cookie)

    assert "sub" not in claims
    assert claims["intent"] == {"kind": "link", "user_id": 7}


@pytest.mark.usefixtures("fake_provider")
def test_flow_cookie_expires_after_ten_minutes() -> None:
    claims = _flow_claims(_start().flow_cookie)

    assert claims["aud"] == "cerebrum-oidc-flow"
    assert isinstance(claims["exp"], int) and isinstance(claims["iat"], int)
    assert claims["exp"] - claims["iat"] == 600


def test_authorization_url_carries_the_flow_parameters(
    fake_provider: FakeProvider,
) -> None:
    started = _start()
    fake_provider.authorize(started.authorization_url)
    params = fake_provider.last_authorization_params
    claims = _flow_claims(started.flow_cookie)

    assert params["response_type"] == "code"
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == REDIRECT_URI
    assert params["scope"] == "openid profile email"
    assert params["state"] == claims["state"]
    assert params["nonce"] == claims["nonce"]
    assert params["code_challenge_method"] == "S256"
    assert "response_mode" not in params


@pytest.mark.usefixtures("fake_provider")
def test_each_flow_gets_fresh_state_nonce_and_verifier() -> None:
    first = _flow_claims(_start().flow_cookie)
    second = _flow_claims(_start().flow_cookie)

    for field in ("state", "nonce", "code_verifier"):
        assert first[field] != second[field]


def test_token_request_carries_the_pkce_verifier(fake_provider: FakeProvider) -> None:
    started = _start()
    code, state = fake_provider.authorize(started.authorization_url)
    asyncio.run(oidc.finish_flow(started.flow_cookie, state=state, code=code))
    form = _token_form(fake_provider)

    assert form["grant_type"] == "authorization_code"
    assert form["code"] == code
    assert form["redirect_uri"] == REDIRECT_URI
    assert form["code_verifier"] == _flow_claims(started.flow_cookie)["code_verifier"]
    assert (
        pkce_challenge(form["code_verifier"])
        == fake_provider.last_authorization_params["code_challenge"]
    )


def test_discovery_is_fetched_once_and_cached(fake_provider: FakeProvider) -> None:
    _run_flow(fake_provider)
    _run_flow(fake_provider)

    assert len(fake_provider.requests_to(fake_provider.discovery_url)) == 1
    assert len(fake_provider.requests_to(fake_provider.jwks_uri)) == 1


# -- the flow cookie and state -------------------------------------------------


def test_state_mismatch_is_refused_as_expired(fake_provider: FakeProvider) -> None:
    started = _start()
    code, _state = fake_provider.authorize(started.authorization_url)

    with pytest.raises(OidcError) as excinfo:
        asyncio.run(oidc.finish_flow(started.flow_cookie, state="forged", code=code))

    assert excinfo.value.code == "expired"
    assert not fake_provider.token_requests


def _resigned_flow_cookie(flow_cookie: str, secret: str, **changes: object) -> str:
    claims = {**_flow_claims(flow_cookie), **changes}
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.mark.parametrize(
    ("secret", "changes"),
    [
        pytest.param(_JWT_SECRET, {"exp": int(time.time()) - 1}, id="past-expiry"),
        pytest.param("z" * 32, {}, id="other-secret"),
        pytest.param(_JWT_SECRET, {"aud": "something-else"}, id="other-audience"),
        pytest.param(_JWT_SECRET, {"intent": {"kind": "admin"}}, id="bad-intent"),
    ],
)
def test_bad_flow_cookie_is_refused_as_expired(
    fake_provider: FakeProvider, secret: str, changes: dict[str, object]
) -> None:
    started = _start()
    code, state = fake_provider.authorize(started.authorization_url)
    cookie = _resigned_flow_cookie(started.flow_cookie, secret, **changes)

    with pytest.raises(OidcError) as excinfo:
        asyncio.run(oidc.finish_flow(cookie, state=state, code=code))

    assert excinfo.value.code == "expired"
    assert not fake_provider.token_requests


@pytest.mark.parametrize("cookie", [None, "", "not-a-jwt"])
@pytest.mark.usefixtures("fake_provider")
def test_missing_or_garbled_flow_cookie_is_refused_as_expired(
    cookie: str | None,
) -> None:
    with pytest.raises(OidcError) as excinfo:
        asyncio.run(oidc.finish_flow(cookie, state="state", code="code"))

    assert excinfo.value.code == "expired"


@pytest.mark.usefixtures("fake_provider")
def test_access_token_is_not_a_flow_cookie() -> None:
    access_token = jwt.encode(
        {"sub": "1", "exp": int(time.time()) + 600}, _JWT_SECRET, algorithm="HS256"
    )

    with pytest.raises(OidcError) as excinfo:
        oidc.decode_flow_cookie(access_token)

    assert excinfo.value.code == "expired"


# -- ID token rejection: the security boundary ---------------------------------


def test_alg_none_is_refused(fake_provider: FakeProvider) -> None:
    # Even when discovery claims to support it.
    fake_provider.signing = "none"
    fake_provider.signing_algs = ["RS256", "none"]

    assert _refused(fake_provider).code == "provider_error"


def test_hs256_signed_with_the_client_secret_is_refused(
    fake_provider: FakeProvider,
) -> None:
    fake_provider.signing = "hs256_client_secret"
    fake_provider.signing_algs = ["RS256", "HS256"]

    assert _refused(fake_provider).code == "provider_error"


def test_algorithm_discovery_does_not_advertise_is_refused(
    fake_provider: FakeProvider,
) -> None:
    fake_provider.signing_algs = ["ES256"]

    assert _refused(fake_provider).code == "provider_error"


def test_forged_signature_is_refused(fake_provider: FakeProvider) -> None:
    good_key = fake_provider.signing_key
    fake_provider.sign_with_unpublished_key()
    # Same `kid` as the published key, different private key.
    fake_provider.signing_key.kid = good_key.kid

    assert _refused(fake_provider).code == "provider_error"


def test_wrong_issuer_is_refused(fake_provider: FakeProvider) -> None:
    fake_provider.claim_overrides = {"iss": "https://evil.test/realms/cerebrum"}

    assert _refused(fake_provider).code == "provider_error"


def test_audience_without_the_client_id_is_refused(fake_provider: FakeProvider) -> None:
    fake_provider.claim_overrides = {"aud": "some-other-client"}

    assert _refused(fake_provider).code == "provider_error"


def test_several_audiences_without_azp_are_refused(fake_provider: FakeProvider) -> None:
    fake_provider.claim_overrides = {"aud": [CLIENT_ID, "some-other-client"]}

    assert _refused(fake_provider).code == "provider_error"


def test_several_audiences_with_another_clients_azp_are_refused(
    fake_provider: FakeProvider,
) -> None:
    fake_provider.claim_overrides = {
        "aud": [CLIENT_ID, "some-other-client"],
        "azp": "some-other-client",
    }

    assert _refused(fake_provider).code == "provider_error"


def test_several_audiences_with_our_azp_are_accepted(
    fake_provider: FakeProvider,
) -> None:
    fake_provider.claim_overrides = {
        "aud": [CLIENT_ID, "some-other-client"],
        "azp": CLIENT_ID,
    }

    assert _run_flow(fake_provider).identity.subject == "provider-user-1"


def test_wrong_nonce_is_refused(fake_provider: FakeProvider) -> None:
    fake_provider.claim_overrides = {"nonce": "replayed-nonce"}

    assert _refused(fake_provider).code == "provider_error"


@pytest.mark.parametrize("claim", ["nonce", "sub", "exp", "iat", "iss", "aud"])
def test_missing_required_claim_is_refused(
    fake_provider: FakeProvider, claim: str
) -> None:
    fake_provider.dropped_claims = {claim}

    assert _refused(fake_provider).code == "provider_error"


def test_empty_subject_is_refused(fake_provider: FakeProvider) -> None:
    fake_provider.claim_overrides = {"sub": ""}

    assert _refused(fake_provider).code == "provider_error"


def test_expired_id_token_is_refused(fake_provider: FakeProvider) -> None:
    now = int(time.time())
    fake_provider.claim_overrides = {"iat": now - 600, "exp": now - 120}

    assert _refused(fake_provider).code == "provider_error"


def test_iat_slightly_in_the_future_is_accepted(fake_provider: FakeProvider) -> None:
    fake_provider.claim_overrides = {"iat": int(time.time()) + 30}

    assert _run_flow(fake_provider).identity.subject == "provider-user-1"


def test_iat_far_in_the_future_is_refused(fake_provider: FakeProvider) -> None:
    now = int(time.time())
    fake_provider.claim_overrides = {"iat": now + 300, "exp": now + 900}

    assert _refused(fake_provider).code == "provider_error"


# -- signing keys --------------------------------------------------------------


def test_unknown_kid_refetches_jwks_once_and_accepts_the_rotated_key(
    fake_provider: FakeProvider,
) -> None:
    _run_flow(fake_provider)  # caches JWKS holding key-1
    fake_provider.rotate_key()

    result = _run_flow(fake_provider)

    assert result.identity.subject == "provider-user-1"
    assert len(fake_provider.requests_to(fake_provider.jwks_uri)) == 2


def test_kid_still_unknown_after_one_refetch_is_refused(
    fake_provider: FakeProvider,
) -> None:
    _run_flow(fake_provider)
    fake_provider.sign_with_unpublished_key()

    assert _refused(fake_provider).code == "provider_error"
    assert len(fake_provider.requests_to(fake_provider.jwks_uri)) == 2


# -- discovery and provider failures -------------------------------------------


def test_discovery_issuer_must_match_exactly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    configured = "https://idp.test/x"
    configure_oidc_env(monkeypatch, OIDC_ISSUER=configured)
    provider = FakeProvider(issuer=configured)
    provider.discovery_issuer = "https://idp.test/x/"
    oidc.use_transport(provider.transport)
    try:
        with (
            caplog.at_level(logging.WARNING, logger="cerebrum.accounts.oidc"),
            pytest.raises(OidcError) as excinfo,
        ):
            _start()
    finally:
        oidc.use_transport(None)
        get_settings.cache_clear()

    assert excinfo.value.code == "provider_error"
    assert "'https://idp.test/x/'" in caplog.text
    assert "'https://idp.test/x'" in caplog.text


def test_unreachable_provider_is_a_provider_error_within_the_timeout(
    fake_provider: FakeProvider,
) -> None:
    fake_provider.unreachable = True

    with pytest.raises(OidcError) as excinfo:
        _start()

    assert excinfo.value.code == "provider_error"
    (request,) = fake_provider.requests
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 10.0,
        "write": 10.0,
        "pool": 10.0,
    }


def test_app_starts_with_an_unreachable_provider(
    fake_provider: FakeProvider, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_provider.unreachable = True
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert not fake_provider.requests


def test_token_endpoint_error_is_a_provider_error_without_its_text(
    fake_provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    fake_provider.token_error = (
        400,
        {"error": "invalid_grant", "error_description": "secret-provider-detail"},
    )

    with caplog.at_level(logging.WARNING, logger="cerebrum.accounts.oidc"):
        error = _refused(fake_provider)

    assert error.code == "provider_error"
    assert "secret-provider-detail" not in str(error)
    assert "secret-provider-detail" in caplog.text


# -- client authentication -----------------------------------------------------


def _basic_credentials(provider: FakeProvider) -> str | None:
    (request,) = provider.token_requests
    header = request.headers.get("authorization")
    if header is None:
        return None
    return base64.b64decode(header.removeprefix("Basic ")).decode()


@pytest.mark.parametrize(
    "methods",
    [
        ["client_secret_basic", "client_secret_post"],
        ["client_secret_basic"],
        None,  # not advertised: client_secret_basic by default
        ["private_key_jwt"],
    ],
)
def test_client_secret_basic_by_default(
    fake_provider: FakeProvider, methods: list[str] | None
) -> None:
    fake_provider.token_auth_methods = methods
    _run_flow(fake_provider)

    assert _basic_credentials(fake_provider) == f"{CLIENT_ID}:{CLIENT_SECRET}"
    assert "client_secret" not in _token_form(fake_provider)


def test_client_secret_post_only_when_listed_alone(
    fake_provider: FakeProvider,
) -> None:
    fake_provider.token_auth_methods = ["client_secret_post"]
    _run_flow(fake_provider)
    form = _token_form(fake_provider)

    assert _basic_credentials(fake_provider) is None
    assert form["client_id"] == CLIENT_ID
    assert form["client_secret"] == CLIENT_SECRET


# -- groups --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        (["staff", "cerebrum-admins"], {"staff", "cerebrum-admins"}),
        ("staff  cerebrum-admins", {"staff", "cerebrum-admins"}),
        (None, set()),
        (42, set()),
        (["staff", 3, ""], {"staff"}),
    ],
)
def test_groups_claim_shapes(
    fake_provider: FakeProvider, claim: object, expected: set[str]
) -> None:
    if claim is None:
        fake_provider.dropped_claims = {"groups"}
    else:
        fake_provider.claim_overrides = {"groups": claim}

    assert _run_flow(fake_provider).identity.groups == expected


@pytest.mark.usefixtures("fake_provider")
def test_groups_come_from_the_configured_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OIDC_GROUPS_CLAIM", "roles")
    get_settings.cache_clear()

    assert oidc.read_groups({"roles": ["editors"], "groups": ["staff"]}) == {"editors"}
    assert oidc.read_groups({"groups": ["staff"]}) == frozenset()


# -- module boundary -----------------------------------------------------------


def test_module_has_no_web_framework_imports() -> None:
    assert oidc.__file__ is not None
    tree = ast.parse(Path(oidc.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    assert not {
        name for name in imported if name.split(".")[0] in {"fastapi", "starlette"}
    }
