from __future__ import annotations

from fastapi import APIRouter, Depends

from cerebrum.api import graph, notes, search
from cerebrum.api.deps import get_current_identity

# `dependencies=[Depends(get_current_identity)]` makes every route included
# below protected by default -- new routes must opt out explicitly rather
# than opt in, which is what closes the "someone forgets to add auth"
# failure mode this unit exists to retire. `health.router` is deliberately
# NOT included here (see main.py): it's mounted directly on `app` instead,
# since it must stay reachable with no `Authorization` header at all
# (Docker healthcheck).
api_router = APIRouter(dependencies=[Depends(get_current_identity)])
api_router.include_router(search.router)
# graph.router registers `/notes/{path:path}/backlinks` — it must be
# included before notes.router's catch-all `/notes/{path:path}`, or the
# generic route swallows the request first (Starlette matches in order).
api_router.include_router(graph.router)
api_router.include_router(notes.router)
