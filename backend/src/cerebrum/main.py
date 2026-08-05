from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.server.http import StarletteWithLifespan

from cerebrum.api import health
from cerebrum.api.auth import unauthenticated_router
from cerebrum.api.router import api_router
from cerebrum.auth_db import connect as connect_auth_db
from cerebrum.index.db import connect
from cerebrum.index.indexer import rebuild_index
from cerebrum.mcp.auth import DiscoverabilityHintMiddleware
from cerebrum.mcp.server import create_mcp_server
from cerebrum.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with AsyncExitStack() as stack:
        settings.cerebrum_vault_path.mkdir(parents=True, exist_ok=True)
        app.state.db = connect(settings.index_path)
        stack.callback(app.state.db.close)

        # Separate database, separate connection, same open/close shape as
        # app.state.db above -- see auth_db.py for why this can't just be
        # another table in the index db (that one is a disposable cache;
        # this one is the sole record of accounts/sessions/tokens).
        app.state.auth_db = connect_auth_db(settings.auth_db_path)
        stack.callback(app.state.auth_db.close)

        # FastMCP's ASGI sub-app has its own lifespan (managing its internal
        # task group/session manager) that is never invoked just by being
        # Mount()-ed -- it must be explicitly entered here, through the same
        # AsyncExitStack as the db connection, so both tear down cleanly (in
        # LIFO order) if startup fails partway through (KTD3). Read off
        # `app.state` rather than a closure: `create_mcp_server(app)` (KTD8)
        # needs `app` to already exist, which happens after `FastAPI(...)`
        # is constructed with this `lifespan` reference, so the mount can't
        # be captured by this function's closure at definition time.
        #
        # Entered before rebuild_index() (not after) so that a rebuild_index
        # failure -- this lifespan's only other failure-prone step -- exercises
        # the AsyncExitStack's unwind through an *already-entered* MCP session
        # manager, not just the db connection; the two steps don't depend on
        # each other, so this ordering is free.
        mcp_app: StarletteWithLifespan | None = getattr(app.state, "mcp_app", None)
        if mcp_app is not None:
            await stack.enter_async_context(mcp_app.lifespan(mcp_app))

        rebuild_index(app.state.db, settings.cerebrum_vault_path)

        yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")
    # Mounted directly on `app`, not through `api_router` (see api/auth.py):
    # this router carries routes -- register, login, refresh -- that must
    # work with no `Authorization` header, so it must never end up behind
    # `api_router`'s default auth dependency.
    app.include_router(unauthenticated_router, prefix="/api/auth")
    # Also mounted directly on `app`, not through `api_router` (see
    # router.py): the Docker healthcheck hits this with no `Authorization`
    # header, so it must never end up behind `api_router`'s default auth
    # dependency either.
    app.include_router(health.router, prefix="/api")

    if settings.mcp_enabled:
        mcp = create_mcp_server(app)
        mcp_app = mcp.http_app(path="/")
        # `app.state.mcp_app` keeps pointing at the *unwrapped* app: the
        # lifespan above needs its real `.lifespan` attribute
        # (`StarletteWithLifespan`-specific), which a plain ASGI-callable
        # wrapper wouldn't carry.
        app.state.mcp_app = mcp_app
        # Own prefix (KTD2): `router.py`'s notes-catch-all route-ordering
        # hazard only applies within `api_router`'s own registration order --
        # a separate `Mount()` at a disjoint prefix sidesteps that class of
        # collision entirely rather than adding a new instance of it.
        # Wrapped in `DiscoverabilityHintMiddleware` (R9): FastMCP's own
        # `RequireAuthMiddleware` gives `verify_token()` no channel to
        # attach a message to its 401 responses, so the rewrite happens
        # one layer up, in front of the mount, instead.
        app.mount("/api/mcp", DiscoverabilityHintMiddleware(mcp_app))

    return app


app = create_app()


def run() -> None:
    # 127.0.0.1, not 0.0.0.0: the latter is a bind-all address, not a
    # connectable one, so the "Running on http://0.0.0.0:8000" link
    # uvicorn prints isn't clickable. Docker's CMD binds 0.0.0.0 explicitly
    # since it needs to accept connections from outside the container.
    uvicorn.run("cerebrum.main:app", host="127.0.0.1", port=8000, reload=True)
