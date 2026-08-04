from __future__ import annotations

# The sentinel a caller must present, in addition to the process having
# `mcp_allow_stub_auth` explicitly enabled (see mcp/auth.py's wiring), for
# this stub to accept a credential at all. Not a secret -- accepting it
# requires the deployer to have already opted into stub auth.
STUB_VALID_CREDENTIAL = "stub-valid-credential"


class AuthenticationError(Exception):
    """Raised by `verify_credential()` when a credential fails verification."""


async def verify_credential(credential: str | None) -> str:
    """Verify a bearer-token-style credential and return the identity
    (subject) it authenticates, or raise `AuthenticationError`.

    This is a backend-wide function (KTD4), not MCP-scoped -- positioned
    beside `api/deps.py` so REST routes can eventually depend on the exact
    same function rather than accumulating a second, divergent auth path.
    Async, since real credential verification may need to check state (a
    token store) rather than pure computation.

    STUB (KTD4): the not-yet-written backend-authentication plan supplies
    the real implementation. This stub is intentionally default-deny --
    every credential is rejected except the fixed test sentinel above --
    and even that sentinel is only reachable when the caller has separately
    enabled `mcp_allow_stub_auth` (see `mcp/auth.py`); this function alone
    does not know about that setting.
    """
    if credential == STUB_VALID_CREDENTIAL:
        return "stub-subject"
    raise AuthenticationError("invalid credential")
