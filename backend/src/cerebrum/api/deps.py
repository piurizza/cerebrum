from __future__ import annotations

import sqlite3
from typing import cast

from fastapi import Request


def get_db(request: Request) -> sqlite3.Connection:
    return cast(sqlite3.Connection, request.app.state.db)
