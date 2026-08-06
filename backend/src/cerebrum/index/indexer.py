from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from cerebrum.index.db import write_lock
from cerebrum.notes.models import ParsedLink
from cerebrum.notes.parser import parse_note
from cerebrum.notes.service import iter_note_paths

logger = logging.getLogger(__name__)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _dedupe_links(links: list[ParsedLink]) -> list[ParsedLink]:
    seen: set[tuple[str, str | None]] = set()
    deduped: list[ParsedLink] = []
    for link in links:
        key = (link.target_path, link.link_text)
        if key not in seen:
            seen.add(key)
            deduped.append(link)
    return deduped


def upsert_note(conn: sqlite3.Connection, vault_root: Path, path: str) -> None:
    file_path = vault_root / path
    raw_content = file_path.read_text(encoding="utf-8")
    parsed = parse_note(path, raw_content)
    links = _dedupe_links(parsed.links)

    with write_lock, conn:
        conn.execute(
            """
            INSERT INTO notes (path, title, tags, created, updated, content_hash, mtime)
            VALUES (:path, :title, :tags, :created, :updated, :content_hash, :mtime)
            ON CONFLICT(path) DO UPDATE SET
                title = excluded.title,
                tags = excluded.tags,
                created = excluded.created,
                updated = excluded.updated,
                content_hash = excluded.content_hash,
                mtime = excluded.mtime
            """,
            {
                "path": path,
                "title": parsed.title,
                "tags": json.dumps(parsed.tags),
                "created": parsed.created.isoformat() if parsed.created else None,
                "updated": parsed.updated.isoformat() if parsed.updated else None,
                "content_hash": _hash_content(raw_content),
                "mtime": file_path.stat().st_mtime,
            },
        )

        conn.execute("DELETE FROM links WHERE source_path = ?", (path,))
        conn.execute("DELETE FROM notes_fts WHERE path = ?", (path,))
        conn.executemany(
            "INSERT INTO links (source_path, target_path, link_text) VALUES (?, ?, ?)",
            [(path, link.target_path, link.link_text) for link in links],
        )
        conn.execute(
            "INSERT INTO notes_fts (path, title, body) VALUES (?, ?, ?)",
            (path, parsed.title, parsed.body),
        )


def remove_note(conn: sqlite3.Connection, path: str) -> None:
    with write_lock, conn:
        conn.execute("DELETE FROM notes WHERE path = ?", (path,))
        conn.execute("DELETE FROM links WHERE source_path = ?", (path,))
        conn.execute("DELETE FROM notes_fts WHERE path = ?", (path,))


def rebuild_index(conn: sqlite3.Connection, vault_root: Path) -> None:
    """Full rescan: upsert changed/new notes, drop rows for deleted ones.

    Always safe to call — the index is a disposable cache, never the
    source of truth (see SPEC.md). A single unreadable or malformed note
    is logged and skipped rather than aborting the whole rescan: this
    runs at FastAPI startup, and users hand-edit vault files outside the
    API, so one bad file must not take down the entire app.
    """
    current_paths = set(iter_note_paths(vault_root))

    with write_lock:
        existing_rows = conn.execute("SELECT path, mtime FROM notes").fetchall()
    existing_mtimes = {row["path"]: row["mtime"] for row in existing_rows}

    for path in existing_mtimes:
        if path not in current_paths:
            try:
                remove_note(conn, path)
            except Exception:  # noqa: BLE001 -- one bad row must not abort the rescan
                logger.exception("Failed to remove stale index entry for %s", path)

    for path in current_paths:
        try:
            mtime = (vault_root / path).stat().st_mtime
            if existing_mtimes.get(path) == mtime:
                continue
            upsert_note(conn, vault_root, path)
        except Exception:  # noqa: BLE001 -- one bad note must not abort the rescan
            logger.exception("Failed to index note %s; skipping", path)
