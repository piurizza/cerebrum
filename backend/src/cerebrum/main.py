from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cerebrum.api.router import api_router
from cerebrum.index.db import connect
from cerebrum.index.indexer import rebuild_index
from cerebrum.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.cerebrum_vault_path.mkdir(parents=True, exist_ok=True)
    app.state.db = connect(settings.index_path)
    rebuild_index(app.state.db, settings.cerebrum_vault_path)
    yield
    app.state.db.close()


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
    return app


app = create_app()


def run() -> None:
    # 127.0.0.1, not 0.0.0.0: the latter is a bind-all address, not a
    # connectable one, so the "Running on http://0.0.0.0:8000" link
    # uvicorn prints isn't clickable. Docker's CMD binds 0.0.0.0 explicitly
    # since it needs to accept connections from outside the container.
    uvicorn.run("cerebrum.main:app", host="127.0.0.1", port=8000, reload=True)
