from __future__ import annotations

import json
import re
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


def search_notes(conn: sqlite3.Connection, query: str) -> list[NoteMeta]:
    """Full-text search over title + body, backed by `notes_fts` (kept in
    sync with `notes` on every upsert/delete -- see index/indexer.py).

    Each word in `query` becomes an FTS5 prefix term; all terms must
    match (across title or body, in any order) for a note to qualify.
    Results are ranked by relevance (`bm25`), most relevant first.
    """
    terms = re.findall(r"\w+", query)
    if not terms:
        return []

    match_query = " AND ".join(f"{term}*" for term in terms)
    rows = conn.execute(
        """
        SELECT n.path, n.title, n.tags, n.created, n.updated
        FROM notes_fts
        JOIN notes n ON n.path = notes_fts.path
        WHERE notes_fts MATCH ?
        ORDER BY bm25(notes_fts)
        """,
        (match_query,),
    ).fetchall()
    return [row_to_note_meta(row) for row in rows]
