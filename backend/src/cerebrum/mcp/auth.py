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

    `allow_stub_auth` is a second, independent gate (`settings.mcp_allow_stub_auth`,
    default `False`) enforced here, not inside `verify_credential()` itself:
    even if a bug in that function accepted some credential it shouldn't,
    every request is still rejected outright while this flag is off. The
    name is a carryover from before U3: `verify_credential()` no longer
    contains a stub, only real JWT verification, so this flag now gates
    whether real credential checks run for MCP requests at all -- a later
    unit (per the backend-authentication plan's U5) is expected to retire
    this gate and the setting entirely once MCP auth is unconditionally on.

    `app` (added in U3) is needed so `verify_credential()` can reach
    `app.state.auth_db` -- see `cerebrum.auth.verify_credential()`'s own
    docstring for why that parameter exists now. Closed over the same way
    `mcp/notes_tools.py`/`mcp/graph_tools.py` already reach `app.state.db`
    (KTD8), rather than being read from a request object FastMCP's
    `TokenVerifier` interface doesn't give this method access to.
    """

    def __init__(self, *, app: FastAPI, allow_stub_auth: bool) -> None:
        super().__init__()
        self._app = app
        self._allow_stub_auth = allow_stub_auth

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self._allow_stub_auth:
            return None
        try:
            subject = await verify_credential(token, get_auth_db(self._app))
        except AuthenticationError:
            return None
        return AccessToken(token=token, client_id=subject, scopes=[])
