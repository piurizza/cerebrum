from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from cerebrum.notes.models import NoteMeta

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# The app holds a single sqlite3.Connection for its lifetime, shared across
# every request handler (some run in Starlette's threadpool, one runs on
# the event loop). WAL + busy_timeout (below) let concurrent readers and
# writers avoid instant "database is locked" errors, but SQLite's
# "in a transaction" state is still tracked per-connection, not per-caller:
# without serializing writers, one thread's commit could flush another
# thread's in-progress statements. write_lock makes each multi-statement
# write sequence (see index/indexer.py) fully atomic with respect to every
# other writer. Readers are not serialized -- WAL lets them proceed without
# blocking on an in-progress write.
write_lock = threading.Lock()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def row_to_note_meta(row: sqlite3.Row) -> NoteMeta:
    return NoteMeta(
        path=row["path"],
        title=row["title"],
        tags=json.loads(row["tags"]),
        created=datetime.fromisoformat(row["created"]) if row["created"] else None,
        updated=datetime.fromisoformat(row["updated"]) if row["updated"] else None,
    )


def list_notes(conn: sqlite3.Connection) -> list[NoteMeta]:
    rows = conn.execute(
        "SELECT path, title, tags, created, updated FROM notes ORDER BY path"
    ).fetchall()
    return [row_to_note_meta(row) for row in rows]
