from __future__ import annotations

from fastapi import APIRouter

from cerebrum.api import graph, health, notes, search

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(search.router)
# graph.router registers `/notes/{path:path}/backlinks` — it must be
# included before notes.router's catch-all `/notes/{path:path}`, or the
# generic route swallows the request first (Starlette matches in order).
api_router.include_router(graph.router)
api_router.include_router(notes.router)
