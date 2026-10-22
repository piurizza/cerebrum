"""Sign-in through the OpenID Connect provider: the two HTTP routes.

`POST /api/auth/oidc/start` is called with fetch. It returns the provider's
authorization URL and sets the `oidc_flow` cookie; the page then navigates
to that URL. The provider sends the browser back to
`GET /api/auth/oidc/callback`, which always answers with a 303: to `/?oidc=1`
with a refresh cookie on success (the page's existing mount-time refresh
turns it into an access token, so no token ever travels in a URL), or back
to the page the flow started from with `?oidc_error=<code>` (KTD6).

The protocol lives in `accounts/oidc.py` and the account side in
`accounts/oidc_accounts.py`; this module owns the request's origin, the
flow cookie's attributes and where each outcome redirects.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cerebrum.accounts.oidc import (
    FLOW_COOKIE_MAX_AGE_SECONDS,
    FLOW_COOKIE_NAME,
    FlowIntent,
    FlowResult,
    LinkIntent,
    LoginIntent,
    OidcError,
    OidcErrorCode,
    RegisterIntent,
    decode_flow_cookie,
    finish_flow,
    start_flow,
)
from cerebrum.accounts.oidc_accounts import (
    create_invited_account,
    is_username_taken,
    sign_in,
)
from cerebrum.accounts.service import find_valid_invite_token_hash
from cerebrum.api.auth import set_refresh_cookie
from cerebrum.api.deps import get_auth_db
from cerebrum.settings import get_settings

logger = logging.getLogger(__name__)

CALLBACK_PATH = "/api/auth/oidc/callback"

# A bare host name or IPv4 address, or a bracketed IPv6 address, with an
# optional port. Anything else in `Host` (a path, `@`, whitespace) would
# reshape the redirect URI built from it, so it is refused outright rather
# than left to the provider's registered-URI check.
_HOST_PATTERN = re.compile(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?")


def _require_provider() -> None:
    # Both routes exist whether or not a provider is configured (so the
    # OpenAPI schema and the generated frontend types always carry them),
    # and answer exactly like a missing route when none is.
    if not get_settings().oidc_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


# No auth dependency, like `api/auth.py`'s `unauthenticated_router`: the
# person starting a flow is by definition not signed in yet, and the
# callback is a top-level navigation from the provider. Mounted directly on
# `app` in main.py for the same reason.
oidc_router = APIRouter(dependencies=[Depends(_require_provider)])


def request_scheme(request: Request) -> str:
    """The scheme the browser used to reach Cerebrum, for both the redirect
    URI and the flow cookie's `Secure` flag (KTD4). Read from the raw
    `X-Forwarded-Proto` header nginx sets, falling back to the socket's own
    scheme: uvicorn doesn't trust forwarded headers from nginx, so behind
    it `request.url.scheme` is always `http`."""
    forwarded = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded.split(",")[0].strip().lower()
    return scheme if scheme in ("http", "https") else request.url.scheme


def _redirect_uri(request: Request) -> str:
    """`<scheme>://<host>/api/auth/oidc/callback` for the origin the
    browser used (KTD7). `Host` keeps its port because nginx passes it as
    `$http_host` for this location. There is no public-URL setting: each
    origin people use is registered at the provider, so a forged header
    only gets the provider to refuse the redirect URI."""
    host = request.headers.get("host") or request.url.netloc
    if not _HOST_PATTERN.fullmatch(host):
        raise HTTPException(status_code=400, detail="Invalid Host header")
    return f"{request_scheme(request)}://{host}{CALLBACK_PATH}"


class OidcStartRequest(BaseModel):
    # `link` (from Settings, which also needs a bearer token and the current
    # password) is the third intent `accounts/oidc.py` understands; it is
    # not accepted here yet.
    intent: Literal["login", "register"]
    # `register` only: the username to create and the invite to redeem.
    username: str | None = None
    invite_token: str | None = None


class OidcStartResponse(BaseModel):
    authorization_url: str


def _register_intent(
    body: OidcStartRequest, auth_db: sqlite3.Connection
) -> RegisterIntent:
    """Check a sign-up up front, so a bad invite or a taken username shows
    on the form rather than after the round trip to the provider (KTD5).
    The callback checks the invite again, and consumes it.

    The invite is checked before the username, as `register_account()`
    does, so whether a username exists is only told to someone holding a
    usable invite. The setup token is never an invite: the first admin
    still bootstraps through `/api/auth/register` with a password (R7)."""
    if body.username is None or body.invite_token is None:
        raise HTTPException(
            status_code=400, detail="A username and an invite are required"
        )
    invite_hash = find_valid_invite_token_hash(auth_db, body.invite_token)
    if invite_hash is None:
        raise HTTPException(status_code=400, detail="Invalid registration token")
    if is_username_taken(auth_db, body.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    return RegisterIntent(username=body.username, invite_hash=invite_hash)


@oidc_router.post("/start", response_model=OidcStartResponse)
async def start(
    body: OidcStartRequest,
    request: Request,
    response: Response,
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> OidcStartResponse:
    intent: FlowIntent = (
        _register_intent(body, auth_db) if body.intent == "register" else LoginIntent()
    )
    try:
        started = await start_flow(_redirect_uri(request), intent)
    except OidcError as exc:
        # Discovery failed; `accounts/oidc.py` has logged why.
        raise HTTPException(
            status_code=502, detail="The sign-in provider could not be reached"
        ) from exc

    response.set_cookie(
        key=FLOW_COOKIE_NAME,
        value=started.flow_cookie,
        max_age=FLOW_COOKIE_MAX_AGE_SECONDS,
        # Sent back only to the callback. `Lax`, not the refresh cookie's
        # `Strict`: the provider returns the browser with a top-level
        # cross-site GET, which a `Strict` cookie would miss (KTD4).
        path=CALLBACK_PATH,
        httponly=True,
        samesite="lax",
        secure=request_scheme(request) == "https",
    )
    return OidcStartResponse(authorization_url=started.authorization_url)


def _failure_location(intent: FlowIntent, code: OidcErrorCode) -> str:
    """Back to the page the flow started from (KTD6). A sign-up keeps its
    username so the form can be refilled, never the invite token."""
    if isinstance(intent, RegisterIntent):
        query = urlencode({"oidc_error": code, "username": intent.username})
        return f"/register?{query}"
    if isinstance(intent, LinkIntent):
        return f"/settings?{urlencode({'oidc_error': code})}"
    return f"/login?{urlencode({'oidc_error': code})}"


def _complete(result: FlowResult, auth_db: sqlite3.Connection) -> str:
    """Do what the flow was started for, returning the new session's
    refresh token."""
    intent = result.intent
    if isinstance(intent, RegisterIntent):
        return create_invited_account(
            auth_db, result.identity, intent.username, intent.invite_hash
        )
    if isinstance(intent, LinkIntent):
        # `start` never issues this intent yet; a cookie carrying it can only
        # come from a later version of this route. Start over.
        logger.warning("OIDC link flow reached a callback that can't link yet")
        raise OidcError("expired")
    return sign_in(auth_db, result.identity)


@oidc_router.get("/callback", response_class=RedirectResponse, status_code=303)
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    auth_db: sqlite3.Connection = Depends(get_auth_db),
) -> RedirectResponse:
    flow_cookie = request.cookies.get(FLOW_COOKIE_NAME)
    # Until the cookie is read, a failure can only go back to the login page.
    intent: FlowIntent = LoginIntent()
    try:
        # First, so a failure for any later reason knows which page to go
        # back to.
        intent = decode_flow_cookie(flow_cookie).intent
        if error is not None:
            # The provider's own text goes to the log, never into the URL.
            logger.info("OIDC provider returned error %r", error[:100])
            raise OidcError("provider_error")
        if code is None or state is None:
            logger.info("OIDC callback without a code or state")
            raise OidcError("provider_error")
        result = await finish_flow(flow_cookie, state=state, code=code)
        refresh_token = _complete(result, auth_db)
    except OidcError as exc:
        response = RedirectResponse(_failure_location(intent, exc.code), 303)
    else:
        response = RedirectResponse("/?oidc=1", 303)
        set_refresh_cookie(response, refresh_token)

    # Cleared on every outcome, so a callback URL replayed from history (or
    # by anyone who saw it) finds no flow to finish.
    response.delete_cookie(
        key=FLOW_COOKIE_NAME,
        path=CALLBACK_PATH,
        httponly=True,
        samesite="lax",
        secure=request_scheme(request) == "https",
    )
    return response
