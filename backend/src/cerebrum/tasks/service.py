from __future__ import annotations

import sqlite3

from cerebrum.index.db import write_lock
from cerebrum.tasks.models import TaskItem


def list_open_tasks(conn: sqlite3.Connection) -> list[TaskItem]:
    # write_lock: this read races the filesystem watcher/backstop rescan's
    # sustained writes against the same shared connection -- see
    # index/db.py's write_lock docstring for the exact hazard
    # (sqlite3.InterfaceError) an unlocked read can hit here (mirrors
    # graph/service.py's identical reasoning for its own reads).
    with write_lock:
        rows = conn.execute(
            """
            SELECT t.source_path, n.title, t.line, t.text
            FROM tasks t
            JOIN notes n ON n.path = t.source_path
            WHERE t.checked = 0
            ORDER BY n.path, t.line
            """
        ).fetchall()
    return [
        TaskItem(
            path=row["source_path"],
            title=row["title"],
            line=row["line"],
            text=row["text"],
        )
        for row in rows
    ]
