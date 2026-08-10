from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.server.http import StarletteWithLifespan

from cerebrum.api import health
from cerebrum.api.auth import unauthenticated_router
from cerebrum.api.router import api_router
from cerebrum.auth_db import connect as connect_auth_db
from cerebrum.index.db import connect
from cerebrum.index.indexer import PendingRenameCache, rebuild_index
from cerebrum.index.watcher import watch_vault
from cerebrum.mcp.auth import DiscoverabilityHintMiddleware
from cerebrum.mcp.server import create_mcp_server
from cerebrum.settings import Settings, get_settings

logger = logging.getLogger(__name__)


async def _run_backstop_rescan(
    conn: sqlite3.Connection,
    vault_root: Path,
    settings: Settings,
    pending_renames: PendingRenameCache | None = None,
) -> None:
    """Periodically rebuild the index from scratch as a self-healing
    backstop for changes the live watcher missed (a debounce edge case, a
    watcher restart gap, or `watch_vault` itself having given up after an
    unrecoverable `awatch()` error -- R4).

    Mirrors `watch_vault`'s loop-level try/except shape (see watcher.py),
    but per-iteration rather than around the whole loop: one bad
    `rebuild_index` call (a transiently locked file, an unexpected
    exception) must not permanently kill this safety net for the rest of
    the process's life (KTD9), so each tick is caught and logged on its
    own rather than letting the loop -- and this task -- die outright.

    `pending_renames` should be the SAME instance passed to `watch_vault`
    (see `lifespan` below) -- sharing it is what lets a cross-window
    rename survive a backstop tick landing between its two watcher
    batches (R9), rather than the tick indexing the new path first and
    permanently defeating pairing for that rename.
    """
    while True:
        try:
            await asyncio.sleep(settings.watcher_backstop_interval_seconds)
            await asyncio.to_thread(rebuild_index, conn, vault_root, pending_renames)
        # `asyncio.CancelledError` is a `BaseException`, not an `Exception`
        # (Python 3.8+) -- this deliberately does *not* catch it, so
        # `task.cancel()` (shutdown, KTD9) still interrupts this loop
        # normally rather than being swallowed as just another bad tick.
        except Exception as exc:  # noqa: BLE001 -- one bad tick must not kill the loop
            logger.warning("backstop rescan iteration failed: %s", exc)


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

        # Started after rebuild_index (not before): both tasks assume the
        # index already reflects an initial full scan, and both stop via
        # a single stack.push_async_callback registered last, below --
        # after MCP and rebuild_index -- so they stop before app.state.db/
        # auth_db close on shutdown (KTD2).
        if settings.watcher_enabled:
            stop_event = asyncio.Event()
            watcher_task: asyncio.Task[None] | None = None
            backstop_task: asyncio.Task[None] | None = None
            # Shared across both tasks (R9) so a rename whose delete and
            # create land in separate watcher debounce batches also
            # survives a backstop tick landing between them -- passing
            # each task its own instance would let the backstop index the
            # new path first and permanently defeat pairing for that
            # rename, since an already-indexed path is never a rename
            # target.
            pending_renames = PendingRenameCache(
                settings.watcher_rename_pairing_window_seconds
            )
            try:
                watcher_task = asyncio.create_task(
                    watch_vault(
                        app.state.db,
                        settings.cerebrum_vault_path,
                        settings,
                        stop_event,
                        pending_renames,
                    )
                )
                backstop_task = asyncio.create_task(
                    _run_backstop_rescan(
                        app.state.db,
                        settings.cerebrum_vault_path,
                        settings,
                        pending_renames,
                    )
                )
            except Exception as exc:  # noqa: BLE001 -- see comment below
                # Defensive backstop only -- task creation raising
                # synchronously is not the primary protection R4 asks for.
                # A missing/unreadable vault path surfaces asynchronously
                # instead, on watch_vault's first awatch() iteration inside
                # its own task, which watch_vault already catches
                # internally (see watcher.py).
                logger.warning("failed to start watcher/backstop tasks: %s", exc)

            async def _stop_background_tasks() -> None:
                stop_event.set()
                for task in (watcher_task, backstop_task):
                    if task is not None:
                        task.cancel()
                results = await asyncio.gather(
                    *(t for t in (watcher_task, backstop_task) if t is not None),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException) and not isinstance(
                        result, asyncio.CancelledError
                    ):
                        logger.warning(
                            "watcher/backstop task did not shut down cleanly: %s",
                            result,
                        )

            stack.push_async_callback(_stop_background_tasks)

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
