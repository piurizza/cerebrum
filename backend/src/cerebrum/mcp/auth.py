from __future__ import annotations

from fastapi import FastAPI
from fastmcp.server.auth import AccessToken, TokenVerifier

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
