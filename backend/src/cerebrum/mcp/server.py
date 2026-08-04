from __future__ import annotations

from fastapi import FastAPI
from fastmcp import FastMCP

from cerebrum.mcp.auth import SharedFunctionTokenVerifier
from cerebrum.mcp.graph_tools import register_graph_tools
from cerebrum.mcp.notes_tools import register_notes_tools
from cerebrum.settings import get_settings


def create_mcp_server(app: FastAPI) -> FastMCP:
    """Build the FastMCP instance mounted under `/api/mcp` (KTD2).

    A factory rather than a module-level singleton, mirroring `create_app()`,
    so tests can construct a fresh instance per test the way `conftest.py`'s
    `client` fixture already rebuilds `create_app()`. Takes `app` so tool
    registration can close over it (KTD8) to reach `app.state.db` and
    settings the same way REST routes do via `api/deps.py`'s `get_db`.
    """
    settings = get_settings()
    verifier = SharedFunctionTokenVerifier(
        app=app, allow_stub_auth=settings.mcp_allow_stub_auth
    )
    mcp = FastMCP(name=settings.app_name, auth=verifier)
    register_notes_tools(mcp, app)
    register_graph_tools(mcp, app)
    return mcp
