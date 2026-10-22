"""Sign-in through one OpenID Connect provider: the protocol half.

Starts an authorization code flow (PKCE `S256`, `state`, `nonce`) and turns
the provider's callback into a `VerifiedIdentity`. Hand-rolled on `httpx`
and `pyjwt` rather than Authlib, which would bring a second session concept
(KTD3). Knows nothing about accounts or HTTP routes: the routes compute the
redirect URI, set and clear the flow cookie, and decide what an identity
means for an account.

Flow state lives in the `oidc_flow` cookie, a short-lived JWT signed with
`AUTH_JWT_SECRET` (KTD4), not in a database table. It is signed, not
encrypted; it stays `HttpOnly` and is bound to the browser that started the
flow.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote, urlencode

import httpx
import jwt

from cerebrum.settings import get_settings

logger = logging.getLogger(__name__)

# The codes a failed flow reports (KTD6). The page maps each one to text;
# whatever the provider said goes to the log only, never into a code.
OidcErrorCode = Literal[
    "not_linked",
    "inactive",
    "invite_invalid",
    "username_taken",
    "already_linked",
    "provider_error",
    "expired",
]

FLOW_COOKIE_NAME = "oidc_flow"
FLOW_COOKIE_MAX_AGE_SECONDS = 600
# Distinguishes a flow cookie from an access token signed with the same
# secret: access tokens carry no `aud`, so neither verifies as the other.
FLOW_COOKIE_AUDIENCE = "cerebrum-oidc-flow"

HTTP_TIMEOUT_SECONDS = 10.0
_METADATA_TTL_SECONDS = 3600.0
# Clock skew tolerated on the ID token's `exp` and `iat`.
_ID_TOKEN_LEEWAY_SECONDS = 60

# Asymmetric algorithms only: `none` and the HMAC family are never accepted,
# whatever discovery advertises. HS256 keyed with the client secret would
# let anyone who knows the secret mint identities.
_ALLOWED_ID_TOKEN_ALGS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "ES256", "ES384", "EdDSA"}
)

_DISCOVERY_PATH = "/.well-known/openid-configuration"


class OidcError(Exception):
    """A failed flow. `code` is safe to put in a redirect URL; the reason
    has already been logged where it was raised."""

    def __init__(self, code: OidcErrorCode) -> None:
        super().__init__(code)
        self.code: OidcErrorCode = code


@dataclass(frozen=True)
class LoginIntent:
    """Sign in to the account already linked to the identity."""


@dataclass(frozen=True)
class RegisterIntent:
    """Create an account from an invite, linked to the identity. Carries
    the invite's hash, never the invite token itself."""

    username: str
    invite_hash: str


@dataclass(frozen=True)
class LinkIntent:
    """Link the identity to an account that is already signed in."""

    user_id: int


FlowIntent = LoginIntent | RegisterIntent | LinkIntent


@dataclass(frozen=True)
class FlowStart:
    """Where to send the browser, and the value of the flow cookie to set
    on the way out."""

    authorization_url: str
    flow_cookie: str


@dataclass(frozen=True)
class FlowState:
    """The decoded flow cookie."""

    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    intent: FlowIntent


@dataclass(frozen=True)
class VerifiedIdentity:
    """Who the provider says signed in. `(issuer, subject)` is the
    identity; `display_name` (preferred username, else email) is for
    showing only and never matched against an account (KTD2)."""

    issuer: str
    subject: str
    groups: frozenset[str]
    display_name: str | None


@dataclass(frozen=True)
class FlowResult:
    identity: VerifiedIdentity
    intent: FlowIntent


# -- HTTP and the metadata cache ---------------------------------------------


@dataclass(frozen=True)
class _ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    id_token_algs: frozenset[str]
    token_auth_method: Literal["client_secret_basic", "client_secret_post"]
    fetched_at: float


@dataclass(frozen=True)
class _SigningKeys:
    jwks_uri: str
    keys: jwt.PyJWKSet
    # The raw JWKS entries by `kid`, to tell a key that declares its `alg`
    # from one that leaves it to the token (see `_key_for`).
    raw_by_kid: dict[str, dict[str, Any]]
    fetched_at: float


@dataclass
class _Runtime:
    """Process-wide state: the cached discovery document and JWKS, and the
    transport requests go through (the network, unless a test swaps in
    `httpx.MockTransport`)."""

    transport: httpx.AsyncBaseTransport | None = None
    metadata: _ProviderMetadata | None = None
    signing_keys: _SigningKeys | None = None


_RUNTIME = _Runtime()


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Send every provider request through `transport` (tests pass an
    `httpx.MockTransport`); None goes back to the network. Also forgets
    the cached metadata, which belonged to the previous transport."""
    _RUNTIME.transport = transport
    clear_cache()


def clear_cache() -> None:
    _RUNTIME.metadata = None
    _RUNTIME.signing_keys = None


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, transport=_RUNTIME.transport)


def _truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


async def _get_json(client: httpx.AsyncClient, url: str, what: str) -> dict[str, Any]:
    try:
        response = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as error:
        logger.warning("OIDC %s request to %s failed: %r", what, url, error)
        raise OidcError("provider_error") from error
    if response.status_code != 200:
        logger.warning(
            "OIDC %s request to %s returned %s: %s",
            what,
            url,
            response.status_code,
            _truncate(response.text),
        )
        raise OidcError("provider_error")
    try:
        document = response.json()
    except ValueError as error:
        logger.warning("OIDC %s from %s is not JSON", what, url)
        raise OidcError("provider_error") from error
    if not isinstance(document, dict):
        logger.warning("OIDC %s from %s is not a JSON object", what, url)
        raise OidcError("provider_error")
    return document


def _parse_metadata(document: dict[str, Any], issuer: str) -> _ProviderMetadata:
    discovered_issuer = document.get("issuer")
    # Exact match, trailing slash included: Authentik's issuer ends in `/`,
    # which is easy to drop from OIDC_ISSUER.
    if discovered_issuer != issuer:
        logger.warning(
            "OIDC discovery reports issuer %r but OIDC_ISSUER is %r; they must "
            "match exactly, trailing slash included",
            discovered_issuer,
            issuer,
        )
        raise OidcError("provider_error")

    endpoints: dict[str, str] = {}
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = document.get(field)
        if not isinstance(value, str) or not value:
            logger.warning("OIDC discovery for %r has no %s", issuer, field)
            raise OidcError("provider_error")
        endpoints[field] = value

    # OIDC Discovery: a missing list means RS256 only, and
    # client_secret_basic only.
    advertised_algs = document.get("id_token_signing_alg_values_supported")
    if not isinstance(advertised_algs, list):
        advertised_algs = ["RS256"]
    auth_methods = document.get("token_endpoint_auth_methods_supported")
    if not isinstance(auth_methods, list):
        auth_methods = ["client_secret_basic"]
    use_post = (
        "client_secret_post" in auth_methods
        and "client_secret_basic" not in auth_methods
    )

    return _ProviderMetadata(
        issuer=issuer,
        authorization_endpoint=endpoints["authorization_endpoint"],
        token_endpoint=endpoints["token_endpoint"],
        jwks_uri=endpoints["jwks_uri"],
        id_token_algs=_ALLOWED_ID_TOKEN_ALGS.intersection(advertised_algs),
        token_auth_method="client_secret_post" if use_post else "client_secret_basic",
        fetched_at=time.monotonic(),
    )


async def _metadata(client: httpx.AsyncClient) -> _ProviderMetadata:
    """The provider's discovery document, fetched on first use and cached
    for an hour. Never fetched at startup, so a provider that is down
    never stops Cerebrum from starting."""
    issuer = _configured(get_settings().oidc_issuer)
    cached = _RUNTIME.metadata
    if (
        cached is not None
        and cached.issuer == issuer
        and time.monotonic() - cached.fetched_at < _METADATA_TTL_SECONDS
    ):
        return cached
    document = await _get_json(
        client, issuer.rstrip("/") + _DISCOVERY_PATH, "discovery"
    )
    metadata = _parse_metadata(document, issuer)
    _RUNTIME.metadata = metadata
    return metadata


async def _fetch_signing_keys(client: httpx.AsyncClient, jwks_uri: str) -> _SigningKeys:
    # `PyJWKSet`, never `PyJWKClient`: the latter fetches with blocking
    # `urllib`, which would stall the event loop and bypass the transport.
    document = await _get_json(client, jwks_uri, "JWKS")
    try:
        keys = jwt.PyJWKSet.from_dict(document)
    except jwt.PyJWTError as error:
        logger.warning("OIDC JWKS from %s has no usable keys: %s", jwks_uri, error)
        raise OidcError("provider_error") from error
    raw_keys = document.get("keys")
    raw_by_kid = {
        entry["kid"]: entry
        for entry in (raw_keys if isinstance(raw_keys, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("kid"), str)
    }
    signing_keys = _SigningKeys(
        jwks_uri=jwks_uri,
        keys=keys,
        raw_by_kid=raw_by_kid,
        fetched_at=time.monotonic(),
    )
    _RUNTIME.signing_keys = signing_keys
    return signing_keys


def _configured(value: str | None) -> str:
    # Callers only reach this module with a provider configured; failing
    # closed here keeps a misrouted call from building URLs out of None.
    if value is None:
        logger.error("OIDC flow used with no provider configured")
        raise OidcError("provider_error")
    return value


# -- starting a flow -----------------------------------------------------------


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _intent_claim(intent: FlowIntent) -> dict[str, Any]:
    if isinstance(intent, RegisterIntent):
        return {
            "kind": "register",
            "username": intent.username,
            "invite_hash": intent.invite_hash,
        }
    if isinstance(intent, LinkIntent):
        return {"kind": "link", "user_id": intent.user_id}
    return {"kind": "login"}


async def start_flow(redirect_uri: str, intent: FlowIntent) -> FlowStart:
    """Begin a flow: the provider's authorization URL to send the browser
    to, and the signed flow-cookie value that remembers this flow until the
    callback. `redirect_uri` is built by the caller from the request's
    origin (KTD7). Raises `OidcError("provider_error")` when discovery
    fails."""
    settings = get_settings()
    client_id = _configured(settings.oidc_client_id)
    async with _http_client() as client:
        metadata = await _metadata(client)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)

    scopes = settings.oidc_scopes.split()
    if "openid" not in scopes:
        scopes.insert(0, "openid")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in metadata.authorization_endpoint else "?"
    authorization_url = f"{metadata.authorization_endpoint}{separator}{query}"

    # The link intent's user id goes in its own claim, never `sub`: a flow
    # cookie must not look like an access token for that user.
    now = datetime.now(UTC)
    flow_cookie = jwt.encode(
        {
            "aud": FLOW_COOKIE_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=FLOW_COOKIE_MAX_AGE_SECONDS),
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "intent": _intent_claim(intent),
        },
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return FlowStart(authorization_url=authorization_url, flow_cookie=flow_cookie)


# -- finishing a flow ----------------------------------------------------------


def _parse_intent(claim: object) -> FlowIntent:
    if isinstance(claim, dict):
        kind = claim.get("kind")
        if kind == "login":
            return LoginIntent()
        username = claim.get("username")
        invite_hash = claim.get("invite_hash")
        if (
            kind == "register"
            and isinstance(username, str)
            and isinstance(invite_hash, str)
        ):
            return RegisterIntent(username=username, invite_hash=invite_hash)
        user_id = claim.get("user_id")
        if (
            kind == "link"
            and isinstance(user_id, int)
            and not isinstance(user_id, bool)
        ):
            return LinkIntent(user_id=user_id)
    raise ValueError(f"unrecognised intent {claim!r}")


def decode_flow_cookie(value: str | None) -> FlowState:
    """Verify and decode the flow cookie. A missing, expired, tampered or
    malformed cookie raises `OidcError("expired")`: to the user it is a
    flow that has to be started again.

    Public so the callback can learn the intent (and so where to send a
    failure) before anything else about the callback is checked."""
    if not value:
        logger.info("OIDC callback without a flow cookie")
        raise OidcError("expired")
    try:
        claims = jwt.decode(
            value,
            get_settings().auth_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=FLOW_COOKIE_AUDIENCE,
            options={"require": ["exp", "iat", "aud"]},
        )
        fields = {
            name: claims[name]
            for name in ("state", "nonce", "code_verifier", "redirect_uri")
        }
        if not all(isinstance(field, str) and field for field in fields.values()):
            raise ValueError("flow cookie field is not a non-empty string")
        intent = _parse_intent(claims.get("intent"))
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        logger.info("OIDC flow cookie refused: %s", error)
        raise OidcError("expired") from error
    return FlowState(intent=intent, **fields)


def _client_auth(
    metadata: _ProviderMetadata, client_id: str, client_secret: str
) -> tuple[dict[str, str], dict[str, str]]:
    """`(headers, form fields)` that authenticate the client at the token
    endpoint: `client_secret_basic` unless the provider supports only
    `client_secret_post` (KTD3)."""
    if metadata.token_auth_method == "client_secret_post":
        return {}, {"client_id": client_id, "client_secret": client_secret}
    # RFC 6749 section 2.3.1: both halves are form-encoded before base64.
    credentials = f"{quote(client_id, safe='')}:{quote(client_secret, safe='')}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}, {}


async def _exchange_code(
    client: httpx.AsyncClient, metadata: _ProviderMetadata, flow: FlowState, code: str
) -> str:
    """Trade the authorization code for the ID token."""
    settings = get_settings()
    client_id = _configured(settings.oidc_client_id)
    secret = settings.oidc_client_secret
    client_secret = _configured(None if secret is None else secret.get_secret_value())
    headers, auth_fields = _client_auth(metadata, client_id, client_secret)
    try:
        response = await client.post(
            metadata.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": flow.redirect_uri,
                "code_verifier": flow.code_verifier,
                **auth_fields,
            },
            headers={"Accept": "application/json", **headers},
        )
    except httpx.HTTPError as error:
        logger.warning("OIDC token request failed: %r", error)
        raise OidcError("provider_error") from error
    if response.status_code != 200:
        logger.warning(
            "OIDC token endpoint returned %s: %s",
            response.status_code,
            _truncate(response.text),
        )
        raise OidcError("provider_error")
    try:
        id_token = response.json().get("id_token")
    except (ValueError, AttributeError) as error:
        logger.warning("OIDC token response is not a JSON object")
        raise OidcError("provider_error") from error
    if not isinstance(id_token, str) or not id_token:
        logger.warning("OIDC token response has no id_token")
        raise OidcError("provider_error")
    return id_token


def _key_for(signing_keys: _SigningKeys, kid: str | None, alg: str) -> jwt.PyJWK | None:
    """The signing key the token names, or None when JWKS has no such key.
    A token without a `kid` is matched only when JWKS holds a single
    signing key."""
    candidates = [
        key for key in signing_keys.keys if key.public_key_use in (None, "sig")
    ]
    if kid is None:
        return candidates[0] if len(candidates) == 1 else None
    key = next((key for key in candidates if key.key_id == kid), None)
    raw = signing_keys.raw_by_kid.get(kid)
    if key is not None and raw is not None and "alg" not in raw:
        # The JWK leaves its algorithm open, so PyJWT guessed one from the
        # key type (RS256 for any RSA key). Bind it to the token's own,
        # already allowlisted, algorithm instead; a key of the wrong type
        # fails to load.
        return jwt.PyJWK(raw, algorithm=alg)
    return key


async def _signing_key(
    client: httpx.AsyncClient, metadata: _ProviderMetadata, kid: str | None, alg: str
) -> jwt.PyJWK:
    """The key to check the ID token with. JWKS is cached for an hour and
    refetched once when the token names a key the cache doesn't hold, so a
    provider's key rotation is picked up without waiting out the cache."""
    signing_keys = _RUNTIME.signing_keys
    fetched_now = False
    if (
        signing_keys is None
        or signing_keys.jwks_uri != metadata.jwks_uri
        or time.monotonic() - signing_keys.fetched_at >= _METADATA_TTL_SECONDS
    ):
        signing_keys = await _fetch_signing_keys(client, metadata.jwks_uri)
        fetched_now = True
    try:
        key = _key_for(signing_keys, kid, alg)
        if key is None and not fetched_now:
            signing_keys = await _fetch_signing_keys(client, metadata.jwks_uri)
            key = _key_for(signing_keys, kid, alg)
    except jwt.PyJWTError as error:
        logger.warning("OIDC JWKS key %r does not fit %s: %s", kid, alg, error)
        raise OidcError("provider_error") from error
    if key is None:
        logger.warning("OIDC ID token names key %r, which JWKS does not list", kid)
        raise OidcError("provider_error")
    return key


def _check_claims(claims: dict[str, Any], client_id: str, nonce: str) -> None:
    """The ID token checks PyJWT doesn't make: `sub`, `azp` and `nonce`."""
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ValueError("no subject")
    audience = claims.get("aud")
    azp = claims.get("azp")
    # OIDC Core 3.1.3.7: with several audiences, `azp` must name us; when
    # present at all, it must be us.
    several_audiences = isinstance(audience, list) and len(audience) > 1
    if (several_audiences or azp is not None) and azp != client_id:
        raise ValueError(f"authorized party {azp!r} is not this client")
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not hmac.compare_digest(
        token_nonce.encode(), nonce.encode()
    ):
        raise ValueError("nonce does not match the flow")


async def _validate_id_token(
    client: httpx.AsyncClient, metadata: _ProviderMetadata, id_token: str, nonce: str
) -> dict[str, Any]:
    """Verify the ID token (KTD3) and return its claims: signature against
    JWKS, an allowlisted asymmetric algorithm, `iss`, `aud`, `azp`, `exp`
    and `iat` with 60 s of leeway, and the flow's `nonce`."""
    client_id = _configured(get_settings().oidc_client_id)
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as error:
        logger.warning("OIDC ID token is not a JWT: %s", error)
        raise OidcError("provider_error") from error
    alg = header.get("alg")
    kid = header.get("kid")
    # Before any key lookup: this is what keeps `none` and HS256 keyed with
    # the client secret out, whatever discovery advertises.
    if not isinstance(alg, str) or alg not in metadata.id_token_algs:
        logger.warning(
            "OIDC ID token algorithm %r is not one of %s",
            alg,
            sorted(metadata.id_token_algs),
        )
        raise OidcError("provider_error")
    if kid is not None and not isinstance(kid, str):
        logger.warning("OIDC ID token has a malformed kid %r", kid)
        raise OidcError("provider_error")

    key = await _signing_key(client, metadata, kid, alg)
    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key,
            algorithms=[alg],
            audience=client_id,
            issuer=metadata.issuer,
            leeway=_ID_TOKEN_LEEWAY_SECONDS,
            options={"require": ["iss", "sub", "aud", "exp", "iat"]},
        )
        _check_claims(claims, client_id, nonce)
    except (jwt.PyJWTError, ValueError) as error:
        logger.warning("OIDC ID token refused: %s", error)
        raise OidcError("provider_error") from error
    return claims


def read_groups(claims: dict[str, Any]) -> frozenset[str]:
    """The user's groups, from the claim `OIDC_GROUPS_CLAIM` names. A list
    and a space-separated string are both understood; anything else, or no
    claim at all, means no groups. The one place groups are read, so
    later grants hang off it."""
    value = claims.get(get_settings().oidc_groups_claim)
    if isinstance(value, str):
        return frozenset(value.split())
    if isinstance(value, list):
        return frozenset(item for item in value if isinstance(item, str) and item)
    return frozenset()


def _display_name(claims: dict[str, Any]) -> str | None:
    for claim in ("preferred_username", "email"):
        value = claims.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def finish_flow(flow_cookie: str | None, *, state: str, code: str) -> FlowResult:
    """Turn the provider's callback into a verified identity: check the
    flow cookie and `state`, exchange `code`, and validate the ID token.
    Raises `OidcError`: `expired` for a cookie or `state` problem,
    `provider_error` for anything the provider got wrong."""
    flow = decode_flow_cookie(flow_cookie)
    # Constant-time, and over bytes: `compare_digest` refuses non-ASCII str.
    if not hmac.compare_digest(flow.state.encode(), state.encode()):
        logger.info("OIDC callback state does not match the flow cookie")
        raise OidcError("expired")

    async with _http_client() as client:
        metadata = await _metadata(client)
        id_token = await _exchange_code(client, metadata, flow, code)
        claims = await _validate_id_token(client, metadata, id_token, flow.nonce)

    identity = VerifiedIdentity(
        issuer=metadata.issuer,
        subject=claims["sub"],
        groups=read_groups(claims),
        display_name=_display_name(claims),
    )
    return FlowResult(identity=identity, intent=flow.intent)
