from __future__ import annotations

import sqlite3
from typing import cast

from fastapi import FastAPI


def get_db(app: FastAPI) -> sqlite3.Connection:
    """The same `app.state.db` connection `api/deps.py`'s `get_db` exposes to
    REST routes via `Depends()`, reached here through closure capture
    instead (KTD8): FastMCP tool functions are plain callables, not FastAPI
    endpoints, so they have no access to `Depends()`-injected values."""
    return cast(sqlite3.Connection, app.state.db)
