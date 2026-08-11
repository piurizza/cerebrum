from __future__ import annotations

from fastapi import APIRouter, Depends

from cerebrum.api import admin, attachments, graph, notes, search, tasks, tokens
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
# No route-ordering hazard with `/tokens` vs. any of the above (no shared
# path prefix, unlike graph.router/notes.router's `/notes/{path:path}`
# collision above) -- inclusion order here doesn't matter.
api_router.include_router(tokens.router)
# `admin.router`'s own routes each additionally depend on `require_admin`
# (see admin.py) -- this router-level `get_current_identity` still runs
# first as `api_router`'s default, `require_admin` layers the `is_admin`
# check on top. No shared path prefix with anything above, same as
# `tokens.router` -- inclusion order doesn't matter here either.
api_router.include_router(admin.router)
# attachments.router's own prefix (`/attachments`) is disjoint from every
# path prefix above (`/search`, `/notes`, `/tokens`, `/admin`/...), so
# there's no route-ordering hazard here either -- inclusion order doesn't
# matter, same as tokens.router/admin.router above.
api_router.include_router(attachments.router)
# `/tasks` shares no path prefix with any router above (`/search`,
# `/notes`, `/graph`, `/tokens`, `/admin`, `/attachments`), so -- like
# tokens.router/admin.router -- inclusion order doesn't matter here.
api_router.include_router(tasks.router)
