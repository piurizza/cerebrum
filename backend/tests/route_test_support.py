from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from starlette.routing import BaseRoute, Mount, Route


def iter_routes(routes: list[BaseRoute], prefix: str = "") -> Iterator[tuple[str, str]]:
    """Recursively walk a Starlette route table, yielding `(method, path)`
    pairs for every concrete `Route`, descending into any nested `Mount`
    (an ASGI sub-app, e.g. the FastMCP mount, can nest routes arbitrarily
    deep). Shared by any test that needs to enumerate the *actual* mounted
    route table rather than trust a hand-maintained list of endpoints --
    see `test_rest_auth.py`'s route-enumeration test, which walks the
    fully-assembled `app.routes` this way specifically so a newly added
    route can't silently skip auth.

    Deliberately generic: this module knows nothing about REST, auth, or
    path-parameter placeholders (e.g. `{path:path}`) -- substituting a
    placeholder value into a matched path so a request doesn't 404 before
    reaching whatever's under test is the caller's concern, not this
    walker's, so a second caller with different substitution needs (or no
    path parameters to worry about at all, like `test_mcp_auth.py`'s own
    local route walker) isn't fighting REST-specific assumptions baked in
    here.
    """
    for route in routes:
        if isinstance(route, Mount):
            sub_routes: Any = getattr(route.app, "routes", None)
            if sub_routes:
                yield from iter_routes(sub_routes, prefix + route.path)
        elif isinstance(route, Route):
            for method in sorted(route.methods or ()):
                # HEAD is implicitly added by Starlette alongside GET and
                # carries the exact same auth dependency -- enumerating it
                # separately would only duplicate every GET-route case
                # below with response bodies this test never inspects.
                if method == "HEAD":
                    continue
                yield (method, prefix + route.path)
        else:
            # Newer FastAPI versions don't eagerly flatten `include_router()`
            # calls into plain `Route`/`Mount` entries on `app.routes` --
            # each call instead leaves a lazy wrapper object (currently
            # `fastapi.routing._IncludedRouter`, private, hence duck-typed
            # here rather than imported) carrying the original `APIRouter`
            # and its prefix. Recursing into it is what makes this walker
            # actually see `api_router`'s routes at all under those
            # versions -- confirmed empirically against this repo's
            # installed FastAPI, not assumed.
            original_router = getattr(route, "original_router", None)
            include_context = getattr(route, "include_context", None)
            sub_prefix = getattr(include_context, "prefix", None) or ""
            if original_router is not None:
                yield from iter_routes(original_router.routes, prefix + sub_prefix)
