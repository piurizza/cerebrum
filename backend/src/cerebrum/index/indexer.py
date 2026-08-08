from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from cerebrum.index.db import write_lock
from cerebrum.notes.models import ParsedLink
from cerebrum.notes.parser import parse_note
from cerebrum.notes.service import iter_note_paths, retarget_note_links

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


def _match_unambiguous_pairs(
    old_hashes: dict[str, str], new_hashes: dict[str, str]
) -> list[tuple[str, str]]:
    """Pair `gone` paths with `new-arrival` paths that share a content
    hash, but only when the hash is unambiguous on both sides (R3):
    exactly one deleted candidate and exactly one new-arrival candidate
    share it. A hash shared by more than one candidate on either side is
    excluded entirely -- every path sharing it falls back to independent
    delete/create handling.
    """
    by_old_hash: dict[str, list[str]] = {}
    for path, content_hash in old_hashes.items():
        by_old_hash.setdefault(content_hash, []).append(path)

    by_new_hash: dict[str, list[str]] = {}
    for path, content_hash in new_hashes.items():
        by_new_hash.setdefault(content_hash, []).append(path)

    pairs: list[tuple[str, str]] = []
    for content_hash, old_paths in by_old_hash.items():
        new_paths = by_new_hash.get(content_hash)
        if len(old_paths) == 1 and new_paths is not None and len(new_paths) == 1:
            pairs.append((old_paths[0], new_paths[0]))
    return pairs


def _fetch_content_hashes(conn: sqlite3.Connection, paths: set[str]) -> dict[str, str]:
    if not paths:
        return {}
    placeholders = ",".join("?" * len(paths))
    with write_lock:
        rows = conn.execute(
            f"SELECT path, content_hash FROM notes WHERE path IN ({placeholders})",
            tuple(paths),
        ).fetchall()
    return {row["path"]: row["content_hash"] for row in rows}


def _guarded_remove(conn: sqlite3.Connection, path: str) -> None:
    """Runs `remove_note` for one path, containing any failure (transient
    races like a concurrent delete, same as `rebuild_index`'s per-note
    containment, but also a malformed note or a DB error) so one bad file
    never aborts the rest of the batch.
    """
    try:
        remove_note(conn, path)
    except Exception:  # noqa: BLE001 -- one bad file must not abort the batch
        logger.exception("skipping change for %s", path)


def _guarded_upsert(conn: sqlite3.Connection, vault_root: Path, path: str) -> None:
    """Runs `upsert_note` for one path, containing any failure -- not just
    the transient-race `FileNotFoundError`/`PermissionError` the watcher
    loop tolerates, but also `InvalidNoteContentError` (malformed
    frontmatter is a normal user-triggerable condition, not rare) and any
    other unexpected error -- so one bad file never aborts the rest of the
    batch or kills the whole watcher task, mirroring `rebuild_index`'s
    broad per-note containment.
    """
    try:
        upsert_note(conn, vault_root, path)
    except Exception:  # noqa: BLE001 -- one bad file must not abort the batch
        logger.exception("skipping change for %s", path)


def _hash_new_arrivals(vault_root: Path, new_arrivals: set[str]) -> dict[str, str]:
    new_hashes: dict[str, str] = {}
    for path in new_arrivals:
        try:
            new_hashes[path] = _hash_content(
                (vault_root / path).read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001 -- one bad file must not abort the batch
            logger.exception("skipping rename-hash read for %s", path)
    return new_hashes


def _apply_pairs(
    conn: sqlite3.Connection, vault_root: Path, pairs: list[tuple[str, str]]
) -> tuple[set[str], set[str]]:
    """Applies each confirmed rename pair: repoints links via
    `retarget_note_links`, then indexes `old_path`, `new_path`, and every
    retargeted note as independent, individually-guarded operations (R7).
    A pair whose link-repointing itself fails is logged and left for the
    caller to fall back to independent delete/create handling.

    Returns the `old_path`/`new_path` sets that were actually applied as
    renames, so the caller can exclude them from that independent
    handling.
    """
    paired_old: set[str] = set()
    paired_new: set[str] = set()
    for old_path, new_path in pairs:
        try:
            _, retargeted = retarget_note_links(vault_root, old_path, new_path)
        except Exception as exc:  # noqa: BLE001 -- pair falls back to independent ops
            logger.warning(
                "failed to retarget links for rename %s -> %s; falling back to "
                "independent delete/create: %s",
                old_path,
                new_path,
                exc,
            )
            continue

        paired_old.add(old_path)
        paired_new.add(new_path)

        _guarded_remove(conn, old_path)
        _guarded_upsert(conn, vault_root, new_path)
        for retargeted_path in retargeted:
            _guarded_upsert(conn, vault_root, retargeted_path)

    return paired_old, paired_new


def apply_watch_batch(
    conn: sqlite3.Connection, vault_root: Path, rel_paths: set[str]
) -> None:
    """Classify one watcher debounce batch's changed paths into confirmed
    renames vs. plain deletes/upserts, and apply the right index action
    for each.

    A delete+create pair in the same batch whose content is byte-identical
    (matching SHA-256 `content_hash`) is treated as a rename: other notes'
    links to the old path are repointed via `retarget_note_links` before
    the index is updated, so an external `mv` doesn't break incoming
    links. Pairing only fires when unambiguous (R3) -- a hash shared by
    more than one deleted or new-arrival path falls back to independent
    delete/create handling for every path sharing it. A path that already
    has an index row is never treated as a rename target (R4), even if
    its new content coincidentally matches a just-deleted note's hash --
    only genuinely new, previously-untracked paths qualify as the "new"
    side of a pair.

    Every per-path/per-pair operation is individually contained (mirrors
    `rebuild_index`'s and `watch_vault`'s log-and-continue pattern), so
    one bad file, and a failed rename link-repointing (R7), never abort
    the rest of the batch.
    """
    gone = {path for path in rel_paths if not (vault_root / path).exists()}
    present = rel_paths - gone

    # One query covers both lookups this classification needs: `gone`'s
    # stored hashes (to find deleted notes worth pairing) and which
    # `present` paths are already indexed (to exclude ordinary content
    # edits from the "new arrival" candidate set, per R4) -- `gone` and
    # `present` partition `rel_paths`, so a single IN(...) over the whole
    # set replaces what would otherwise be two near-identical round-trips.
    indexed_hashes = _fetch_content_hashes(conn, rel_paths)
    old_hashes = {path: h for path, h in indexed_hashes.items() if path in gone}
    new_arrivals = present - indexed_hashes.keys()
    # Hashing reads and hashes each new file's full content -- skip that
    # work when nothing was deleted this batch, since `_match_unambiguous_pairs`
    # can never produce a pair without at least one `old_hashes` entry.
    new_hashes = _hash_new_arrivals(vault_root, new_arrivals) if old_hashes else {}

    pairs = _match_unambiguous_pairs(old_hashes, new_hashes)
    paired_old, paired_new = _apply_pairs(conn, vault_root, pairs)

    for path in gone - paired_old:
        _guarded_remove(conn, path)

    for path in present - paired_new:
        _guarded_upsert(conn, vault_root, path)
