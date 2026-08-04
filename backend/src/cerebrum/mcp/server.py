from __future__ import annotations

from fastmcp import FastMCP

from cerebrum.settings import get_settings


def create_mcp_server() -> FastMCP:
    """Build the FastMCP instance mounted under `/api/mcp` (KTD2).

    A factory rather than a module-level singleton, mirroring `create_app()`,
    so tests can construct a fresh instance per test the way `conftest.py`'s
    `client` fixture already rebuilds `create_app()`.
    """
    settings = get_settings()
    return FastMCP(name=settings.app_name)
