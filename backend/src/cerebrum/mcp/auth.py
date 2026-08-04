from __future__ import annotations

from fastmcp.server.auth import AccessToken, TokenVerifier

from cerebrum.auth import AuthenticationError, verify_credential


class SharedFunctionTokenVerifier(TokenVerifier):
    """Adapts the shared, backend-wide `verify_credential()` (`cerebrum.auth`,
    KTD4) to FastMCP's own `TokenVerifier` interface -- neither FastMCP nor
    the official SDK integrate with FastAPI's `Depends()` graph, so this
    bridges rather than reuses.

    `allow_stub_auth` is a second, independent gate (`settings.mcp_allow_stub_auth`,
    default `False`) enforced here, not inside `verify_credential()` itself:
    even if the stub function had a bug that accepted some credential, every
    request is still rejected outright while this flag is off, given
    `mcp_enabled` defaults to `True` and the real backend-auth function
    doesn't exist yet (see System-Wide Impact in the MCP server plan).
    """

    def __init__(self, *, allow_stub_auth: bool) -> None:
        super().__init__()
        self._allow_stub_auth = allow_stub_auth

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self._allow_stub_auth:
            return None
        try:
            subject = await verify_credential(token)
        except AuthenticationError:
            return None
        return AccessToken(token=token, client_id=subject, scopes=[])
