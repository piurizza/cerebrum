from __future__ import annotations

import json

from fastapi import FastAPI
from fastmcp.server.auth import AccessToken, TokenVerifier
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cerebrum.auth import AuthenticationError, verify_credential
from cerebrum.mcp.context import get_auth_db


class SharedFunctionTokenVerifier(TokenVerifier):
    """Adapts the shared, backend-wide `verify_credential()` (`cerebrum.auth`,
    KTD4/KTD10) to FastMCP's own `TokenVerifier` interface -- neither FastMCP nor
    the official SDK integrate with FastAPI's `Depends()` graph, so this
    bridges rather than reuses.

    MCP auth is unconditionally on: every `verify_token()` call runs real
    credential verification via `verify_credential()`, with no separate
    settings-driven gate deciding whether that check even runs. (An
    earlier unit had this class enforce a second, independent gate on top
    of `verify_credential()` -- rejecting every request outright while
    that gate was off, regardless of credential validity -- which a later
    unit retired once MCP auth was ready to be unconditionally on.)

    `app` is needed so `verify_credential()` can reach `app.state.auth_db`
    -- see `cerebrum.auth.verify_credential()`'s own docstring for why that
    parameter exists. Closed over the same way `mcp/notes_tools.py`/
    `mcp/graph_tools.py` already reach `app.state.db` (KTD8), rather than
    being read from a request object FastMCP's `TokenVerifier` interface
    doesn't give this method access to.
    """

    def __init__(self, *, app: FastAPI) -> None:
        super().__init__()
        self._app = app

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            subject = await verify_credential(token, get_auth_db(self._app))
        except AuthenticationError:
            return None
        return AccessToken(token=token, client_id=subject, scopes=[])


# The plaintext appended to FastMCP's own invalid-token error description
# (R9). Deliberately generic about *how* to reach the settings page -- this
# module has no request/Host context to build an absolute URL from, and a
# relative path is meaningless to a non-browser MCP client anyway.
_DISCOVERABILITY_HINT = (
    " Generate a personal API token from Cerebrum's settings page in your "
    "browser and use it as this client's bearer token."
)


class DiscoverabilityHintMiddleware:
    """Wraps the FastMCP ASGI app to append R9's discoverability hint to its
    invalid-token 401 response.

    This can't be done inside `SharedFunctionTokenVerifier` above:
    `verify_token()`'s return value carries no message channel, and reading
    the installed `fastmcp==3.4.5` middleware source directly
    (`fastmcp/server/auth/middleware.py`'s `RequireAuthMiddleware.
    _send_auth_error()`) confirms it unconditionally *overwrites* the
    description for every `invalid_token` 401 with its own hardcoded,
    OAuth-reconnect-flow message ("clear authentication tokens in your MCP
    client and reconnect... obtain new tokens") -- wrong advice for this
    app, which has no such flow, and there is no supported extension point
    to override it. This wrapper is the only way to reach the response an
    MCP client actually receives.

    Scoped narrowly to the one case FastMCP's own source shows sends a
    single, non-streamed, buffer-safe JSON body: a *presented* credential
    that failed verification (`error == "invalid_token"`). The other 401
    case -- no `Authorization` header at all -- is left untouched:
    `_send_missing_auth()` sends an empty body by design, since RFC 6750
    §3.1 says "If the request lacks any authentication information, the
    error attribute SHOULD NOT be included" for that case; adding hint text
    there would violate the spec real MCP clients rely on for OAuth
    discovery. This narrowing is exactly what the plan's own
    deferred-to-implementation note anticipated ("pick whichever the
    library actually supports and adjust R9's implementation accordingly
    without changing its intent") -- R9's intent is satisfied for the case
    that already carries a message today, not silently dropped.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    @property
    def routes(self) -> list[object]:
        """Transparent passthrough to the wrapped app's `routes` --
        `test_mcp_auth.py`'s route-enumeration test (and any future
        route-table introspection) walks `Mount.app.routes` directly, and
        this wrapper must not become an opaque node that breaks that walk
        just by sitting in front of the real ASGI app."""
        return getattr(self._app, "routes", [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        deferred_start: Message | None = None

        async def capturing_send(message: Message) -> None:
            nonlocal deferred_start
            if message["type"] == "http.response.start":
                if message["status"] == 401:
                    # Hold this back -- whether to rewrite depends on the
                    # body, which arrives in the next message.
                    deferred_start = message
                    return
                await send(message)
                return
            if message["type"] == "http.response.body" and deferred_start is not None:
                start, deferred_start = deferred_start, None
                new_start, new_body = _rewrite_invalid_token_response(start, message)
                await send(new_start)
                await send(new_body)
                return
            await send(message)

        await self._app(scope, receive, capturing_send)


def _rewrite_invalid_token_response(
    start: Message, body_message: Message
) -> tuple[Message, Message]:
    """Append the discoverability hint to `body_message` when it's the
    `invalid_token` shape `_send_auth_error()` sends; otherwise return
    `start`/`body_message` unchanged (e.g. the empty-body missing-auth
    case, or a shape from a future FastMCP version this wasn't written
    against)."""
    body = body_message.get("body", b"")
    try:
        payload = json.loads(body) if body else None
    except ValueError:
        payload = None

    if not isinstance(payload, dict) or payload.get("error") != "invalid_token":
        return start, body_message

    payload["error_description"] = str(payload.get("error_description", "")) + (
        _DISCOVERABILITY_HINT
    )
    new_body = json.dumps(payload).encode()
    headers = [
        (name, value)
        for name, value in start["headers"]
        if name.lower() != b"content-length"
    ]
    headers.append((b"content-length", str(len(new_body)).encode()))
    new_start: Message = {**start, "headers": headers}
    new_body_message: Message = {**body_message, "body": new_body}
    return new_start, new_body_message
