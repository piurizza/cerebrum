"""An in-process fake OpenID Connect provider for tests.

Serves discovery, JWKS and the token endpoint through `httpx.MockTransport`,
so `cerebrum.accounts.oidc` talks to it exactly as it would to Keycloak or
Authentik, with no network. The browser's trip to the provider's login page
is `FakeProvider.authorize()`: it reads the authorization URL Cerebrum built
and hands back the `code` and `state` the provider would redirect with.

Every knob below makes the provider misbehave in one specific way (wrong
`iss`, `alg: none`, a rotated signing key, an unreachable host, ...), so a
test sets one knob and checks that Cerebrum refuses. The `fake_provider`
fixture in `conftest.py` installs a fresh provider per test.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from cerebrum.settings import get_settings

ISSUER = "https://idp.test/realms/cerebrum"
CLIENT_ID = "cerebrum"
CLIENT_SECRET = "fake-client-secret-with-enough-bytes-for-hs256"
REDIRECT_URI = "https://cerebrum.test/api/auth/oidc/callback"

# Every OIDC setting, so `configure_oidc_env()` can start from a clean
# slate whatever the developer's shell exports.
OIDC_ENV_KEYS = (
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_PROVIDER_NAME",
    "OIDC_SCOPES",
    "OIDC_ADMIN_GROUP",
    "OIDC_GROUPS_CLAIM",
    "OIDC_ALLOW_INSECURE_ISSUER",
    "AUTH_PASSWORD_LOGIN",
)

Signing = Literal["rs256", "none", "hs256_client_secret"]


def pin_oidc_env_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every OIDC variable at its "no provider" value. Set, not deleted: a
    variable that is merely unset would let a developer's backend/.env
    decide, while a blank one outranks it (blank means the default)."""
    for key in OIDC_ENV_KEYS:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("OIDC_ALLOW_INSECURE_ISSUER", "false")
    monkeypatch.setenv("AUTH_PASSWORD_LOGIN", "true")


def configure_oidc_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """Point the settings at the fake provider. `overrides` maps env var
    names to values (for example `OIDC_GROUPS_CLAIM="roles"`)."""
    pin_oidc_env_off(monkeypatch)
    env = {
        "OIDC_ISSUER": ISSUER,
        "OIDC_CLIENT_ID": CLIENT_ID,
        "OIDC_CLIENT_SECRET": CLIENT_SECRET,
        **overrides,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def pkce_challenge(verifier: str) -> str:
    """The `S256` code challenge for `verifier` (RFC 7636 section 4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class _SigningKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    def public_jwk(self) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key())
        )
        jwk.update({"kid": self.kid, "alg": "RS256", "use": "sig"})
        return jwk


def _new_signing_key(kid: str) -> _SigningKey:
    return _SigningKey(
        kid=kid,
        private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
    )


@dataclass
class _Grant:
    """What the provider remembers between the authorization request and
    the code exchange."""

    redirect_uri: str
    nonce: str
    code_challenge: str


class FakeProvider:  # pylint: disable=too-many-instance-attributes
    def __init__(
        self,
        issuer: str = ISSUER,
        client_id: str = CLIENT_ID,
        client_secret: str = CLIENT_SECRET,
    ) -> None:
        self.issuer = issuer
        self.client_id = client_id
        self.client_secret = client_secret
        self._base = issuer.rstrip("/")
        self._grants: dict[str, _Grant] = {}

        # The signing key tokens use, and the keys JWKS publishes. Kept
        # apart so a test can sign with a key JWKS does not (yet) list.
        self.signing_key = _new_signing_key("key-1")
        self.published_keys = [self.signing_key]

        # The signed-in user, as the ID token describes them.
        self.subject = "provider-user-1"
        self.extra_claims: dict[str, Any] = {
            "preferred_username": "alice",
            "email": "alice@example.test",
            "groups": ["staff", "cerebrum-admins"],
        }

        # Misbehaviour knobs. Each defaults to a well-behaved provider.
        # Claims merged into the ID token last, so they can replace the
        # standard ones (`iss`, `aud`, `nonce`, `exp`, ...).
        self.claim_overrides: dict[str, Any] = {}
        self.dropped_claims: set[str] = set()
        self.signing: Signing = "rs256"
        # The `issuer` discovery reports, when it differs from the real one.
        self.discovery_issuer: str | None = None
        self.signing_algs = ["RS256"]
        # None leaves `token_endpoint_auth_methods_supported` out of
        # discovery, which means `client_secret_basic` (OIDC Discovery).
        self.token_auth_methods: list[str] | None = [
            "client_secret_basic",
            "client_secret_post",
        ]
        # `(status, body)` the token endpoint answers with instead of tokens.
        self.token_error: tuple[int, dict[str, Any]] | None = None
        # Every request fails as a connect timeout would.
        self.unreachable = False

        # What the client sent, for assertions.
        self.requests: list[httpx.Request] = []
        self.last_authorization_params: dict[str, str] = {}

    # -- endpoints ---------------------------------------------------------

    @property
    def discovery_url(self) -> str:
        return f"{self._base}/.well-known/openid-configuration"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self._base}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self._base}/protocol/openid-connect/token"

    @property
    def jwks_uri(self) -> str:
        return f"{self._base}/protocol/openid-connect/certs"

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def requests_to(self, url: str) -> list[httpx.Request]:
        return [request for request in self.requests if str(request.url) == url]

    @property
    def token_requests(self) -> list[httpx.Request]:
        return self.requests_to(self.token_endpoint)

    # -- the browser's side ------------------------------------------------

    def authorize(self, authorization_url: str) -> tuple[str, str]:
        """The user signs in at the provider: check the authorization
        request the way a provider would and return `(code, state)`, the
        two query parameters of the redirect back to Cerebrum."""
        parts = urlsplit(authorization_url)
        endpoint = f"{parts.scheme}://{parts.netloc}{parts.path}"
        assert endpoint == self.authorization_endpoint
        params = {key: values[0] for key, values in parse_qs(parts.query).items()}
        self.last_authorization_params = params
        assert params["response_type"] == "code"
        assert params["client_id"] == self.client_id
        assert params["code_challenge_method"] == "S256"
        assert "openid" in params["scope"].split()

        code = secrets.token_urlsafe(16)
        self._grants[code] = _Grant(
            redirect_uri=params["redirect_uri"],
            nonce=params["nonce"],
            code_challenge=params["code_challenge"],
        )
        return code, params["state"]

    # -- key rotation ------------------------------------------------------

    def rotate_key(self) -> None:
        """Sign with a new key and publish only that one, as a provider
        does after retiring a key."""
        self.signing_key = _new_signing_key(f"key-{len(self.published_keys) + 1}")
        self.published_keys = [self.signing_key]

    def sign_with_unpublished_key(self) -> None:
        """Sign with a key JWKS never lists."""
        self.signing_key = _new_signing_key("never-published")

    # -- request handling --------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.unreachable:
            raise httpx.ConnectTimeout("fake provider unreachable", request=request)
        url = str(request.url)
        if request.method == "GET" and url == self.discovery_url:
            return httpx.Response(200, json=self._discovery())
        if request.method == "GET" and url == self.jwks_uri:
            keys = [key.public_jwk() for key in self.published_keys]
            return httpx.Response(200, json={"keys": keys})
        if request.method == "POST" and url == self.token_endpoint:
            return self._token(request)
        return httpx.Response(404, json={"error": "not_found"})

    def _discovery(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "issuer": self.discovery_issuer or self.issuer,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "jwks_uri": self.jwks_uri,
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": self.signing_algs,
            "code_challenge_methods_supported": ["S256"],
        }
        if self.token_auth_methods is not None:
            document["token_endpoint_auth_methods_supported"] = self.token_auth_methods
        return document

    def _client_authenticated(
        self, request: httpx.Request, form: dict[str, str]
    ) -> bool:
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
            client_id, _, client_secret = decoded.partition(":")
            return (unquote(client_id), unquote(client_secret)) == (
                self.client_id,
                self.client_secret,
            )
        return (form.get("client_id"), form.get("client_secret")) == (
            self.client_id,
            self.client_secret,
        )

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.token_error is not None:
            status, body = self.token_error
            return httpx.Response(status, json=body)
        form = {
            key: values[0]
            for key, values in parse_qs(request.content.decode("ascii")).items()
        }
        if not self._client_authenticated(request, form):
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = self._grants.pop(form.get("code", ""), None)
        if (
            form.get("grant_type") != "authorization_code"
            or grant is None
            or form.get("redirect_uri") != grant.redirect_uri
            or pkce_challenge(form.get("code_verifier", "")) != grant.code_challenge
        ):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(
            200,
            json={
                "access_token": "fake-access-token",
                "token_type": "Bearer",
                "expires_in": 300,
                "id_token": self.id_token(grant.nonce),
            },
        )

    def id_token(self, nonce: str) -> str:
        """The ID token this provider would issue now, knobs applied."""
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "sub": self.subject,
            "aud": self.client_id,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            **self.extra_claims,
            **self.claim_overrides,
        }
        for claim in self.dropped_claims:
            claims.pop(claim, None)
        # Every variant names the current key's `kid`, so a refusal comes
        # from the algorithm check, not from an unknown key.
        headers = {"kid": self.signing_key.kid}
        if self.signing == "none":
            return jwt.encode(claims, "", algorithm="none", headers=headers)
        if self.signing == "hs256_client_secret":
            return jwt.encode(
                claims, self.client_secret, algorithm="HS256", headers=headers
            )
        return jwt.encode(
            claims, self.signing_key.private_key, algorithm="RS256", headers=headers
        )
