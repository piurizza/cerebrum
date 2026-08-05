from __future__ import annotations

import sqlite3
from typing import cast

from fastapi import FastAPI

INDEX_LAG_WARNING = (
    "Reads from the search index, which can lag slightly behind a just-completed write."
)


def get_db(app: FastAPI) -> sqlite3.Connection:
    """The same `app.state.db` connection `api/deps.py`'s `get_db` exposes to
    REST routes via `Depends()`, reached here through closure capture
    instead (KTD8): FastMCP tool functions are plain callables, not FastAPI
    endpoints, so they have no access to `Depends()`-injected values."""
    return cast(sqlite3.Connection, app.state.db)


def get_auth_db(app: FastAPI) -> sqlite3.Connection:
    """The `app.state.auth_db` counterpart to `get_db()` above -- added in
    U3 so `mcp/auth.py`'s `SharedFunctionTokenVerifier` can reach the auth
    database the same way REST routes do via `api/deps.py`'s
    `get_auth_db()`, now that `cerebrum.auth.verify_credential()` needs a
    live connection to do real verification."""
    return cast(sqlite3.Connection, app.state.auth_db)
