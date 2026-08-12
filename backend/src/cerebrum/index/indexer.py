from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cerebrum.index.db import write_lock
from cerebrum.notes.models import ParsedLink
from cerebrum.notes.parser import parse_note
from cerebrum.notes.service import iter_note_paths, retarget_note_links

logger = logging.getLogger(__name__)

# Bumped whenever a schema change means an unchanged-mtime note can no
# longer be trusted to already have every derived row it should -- the
# `tasks` table is the first case (see rebuild_index's user_version
# check below). SQLite's PRAGMA user_version is a single integer stored
# in the database file header for exactly this purpose; a database that
# predates this constant (including a brand-new one, which starts at 0)
# reads back 0 and gets one forced full rescan.
_SCHEMA_BACKFILL_VERSION = 1


@dataclass
class _PendingDeletion:
    path: str
    content_hash: str
    deleted_at: float


class PendingRenameCache:
    """Remembers recently-deleted note content hashes for a bounded
    window, so a create arriving in a LATER watcher debounce batch (or
    observed by the periodic backstop rescan) can still be paired as a
    rename with a delete from an EARLIER one -- extending the same-batch
    detection `apply_watch_batch` already does on its own.

    Locked, not "not thread-safe by design": `watch_vault` and
    `_run_backstop_rescan` run as two independent `asyncio.Task`s (see
    `main.py`'s `lifespan`), each dispatching its own `asyncio.to_thread`
    call -- meaning `apply_watch_batch` and `rebuild_index` genuinely CAN
    execute on separate OS threads at the same wall-clock moment; nothing
    serializes the two tasks against each other. This is the same dual-
    caller-thread topology `index/db.py`'s `write_lock` already guards
    the shared `sqlite3.Connection` against (see its module comment) --
    an initial version of this class wrongly assumed the two callers were
    mutually exclusive and shipped without a lock; code review caught the
    race before it reached production. All five methods below acquire
    `self._lock` for their full body, since `prune`/`pop_unambiguous_match`
    each do a read-then-mutate sequence on `self._entries` that isn't
    safe to interleave with a concurrent mutation from the other thread.
    """

    def __init__(self, window_seconds: float) -> None:
        self._window_seconds = window_seconds
        self._entries: list[_PendingDeletion] = []
        self._lock = threading.Lock()

    def add(self, path: str, content_hash: str, now: float) -> None:
        with self._lock:
            self._entries.append(_PendingDeletion(path, content_hash, now))

    def prune(self, now: float) -> None:
        with self._lock:
            self._entries = [
                entry
                for entry in self._entries
                if now - entry.deleted_at <= self._window_seconds
            ]

    def pop_unambiguous_match(self, content_hash: str) -> str | None:
        """Returns and removes the matching pending path, but only if
        exactly one entry shares `content_hash`. Zero or multiple matches
        return `None` and leave the cache unchanged -- ambiguous matches
        are never paired, mirroring `_match_unambiguous_pairs`'s
        same-batch rule applied across time instead of within one batch.
        """
        with self._lock:
            matches = [
                entry for entry in self._entries if entry.content_hash == content_hash
            ]
            if len(matches) != 1:
                return None
            self._entries.remove(matches[0])
            return matches[0].path

    def remove_by_path(self, path: str) -> None:
        """Drops any entry for `path`, regardless of hash or age -- used
        when a path reappears in the vault, so it can never be used as an
        unrelated later arrival's cross-window match source."""
        with self._lock:
            self._entries = [entry for entry in self._entries if entry.path != path]

    def is_empty(self) -> bool:
        with self._lock:
            return not self._entries


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


def upsert_note(
    conn: sqlite3.Connection,
    vault_root: Path,
    path: str,
    raw_content: str | None = None,
) -> None:
    """Reads (or reuses an already-read) `path`, and writes its parsed
    note/links/FTS rows.

    `raw_content`, when supplied, skips the disk read -- for a caller
    that already read the file to compute its content hash for rename
    matching (`rebuild_index`'s cache-aware branch), re-reading here
    would cost a second file read and SHA-256 hash for no reason.
    """
    file_path = vault_root / path
    if raw_content is None:
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
        conn.execute("DELETE FROM tasks WHERE source_path = ?", (path,))
        conn.executemany(
            "INSERT INTO links (source_path, target_path, link_text) VALUES (?, ?, ?)",
            [(path, link.target_path, link.link_text) for link in links],
        )
        conn.execute(
            "INSERT INTO notes_fts (path, title, body) VALUES (?, ?, ?)",
            (path, parsed.title, parsed.body),
        )
        conn.executemany(
            "INSERT INTO tasks (source_path, line, checked, text) VALUES (?, ?, ?, ?)",
            [(path, task.line, task.checked, task.text) for task in parsed.tasks],
        )


def remove_note(conn: sqlite3.Connection, path: str) -> None:
    with write_lock, conn:
        conn.execute("DELETE FROM notes WHERE path = ?", (path,))
        conn.execute("DELETE FROM links WHERE source_path = ?", (path,))
        conn.execute("DELETE FROM notes_fts WHERE path = ?", (path,))
        conn.execute("DELETE FROM tasks WHERE source_path = ?", (path,))


def rebuild_index(
    conn: sqlite3.Connection,
    vault_root: Path,
    pending_renames: PendingRenameCache | None = None,
) -> None:
    """Full rescan: upsert changed/new notes, drop rows for deleted ones.

    Always safe to call — the index is a disposable cache, never the
    source of truth (see SPEC.md). A single unreadable or malformed note
    is logged and skipped rather than aborting the whole rescan: this
    runs at FastAPI startup, and users hand-edit vault files outside the
    API, so one bad file must not take down the entire app.

    `pending_renames`, when supplied, is consulted for a genuinely new
    (never-before-indexed) path the same way `apply_watch_batch`'s
    new-arrival matching does (R9) -- without this, a backstop tick
    landing between a cross-window rename's delete and create batches
    would index the new path as an ordinary note first, permanently
    defeating pairing for that rename (an already-indexed path is never
    a rename target, R2/R4). Before that, it runs the same
    `_prepare_pending_renames` preamble `apply_watch_batch` does (prune
    expired entries, invalidate any entry for a path that currently
    exists, R3/R8) -- found missing in code review; without it, a
    backstop-only rescan (the exact case R9 exists for) could match an
    already-expired entry, or let a resurrected path's stale entry
    hijack an unrelated later arrival's link retargeting. Omitted, this
    behaves exactly as before this plan -- the startup rescan (which
    runs before any watcher state exists) always calls it this way. An
    already-indexed, merely-*changed* path never consults the cache
    either way -- only a path with no prior row at all is eligible,
    mirroring R4.
    """
    current_paths = set(iter_note_paths(vault_root))
    if pending_renames is not None:
        _prepare_pending_renames(pending_renames, current_paths, time.monotonic())

    with write_lock:
        existing_rows = conn.execute("SELECT path, mtime FROM notes").fetchall()
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    existing_mtimes = {row["path"]: row["mtime"] for row in existing_rows}

    # A database at a version older than _SCHEMA_BACKFILL_VERSION may be
    # missing rows a newer schema derives (the `tasks` table is the first
    # case) for any note whose mtime hasn't changed since it was last
    # indexed -- normally the signal that a note's derived rows are
    # already current, but not true across a schema change that adds a
    # new kind of derived row. Force every note through upsert_note once
    # to backfill, then bump the version so this is a one-time cost.
    needs_schema_backfill = schema_version < _SCHEMA_BACKFILL_VERSION
    # A note that raises during the backfill pass below must not be
    # treated as backfilled -- without this, bumping the version
    # unconditionally would permanently hide the gap: the note's mtime
    # never changes again on its own, so it would never be retried by
    # the ordinary mtime-skip path on any future rescan either. Left
    # False (and the version bump skipped) whenever ANY note fails
    # during a backfill pass, so the next rebuild_index call retries the
    # whole backfill rather than silently orphaning that one note.
    backfill_had_failures = False

    for path in existing_mtimes:
        if path not in current_paths:
            try:
                remove_note(conn, path)
            except Exception:  # noqa: BLE001 -- one bad row must not abort the rescan
                logger.exception("Failed to remove stale index entry for %s", path)

    for path in current_paths:
        try:
            mtime = (vault_root / path).stat().st_mtime
            if not needs_schema_backfill and existing_mtimes.get(path) == mtime:
                continue
            if (
                pending_renames is not None
                and not pending_renames.is_empty()
                and path not in existing_mtimes
            ):
                # Read once, reuse for both the match attempt and the
                # eventual upsert on a miss -- avoids reading and
                # SHA-256-hashing the same file twice.
                raw_content = (vault_root / path).read_text(encoding="utf-8")
                content_hash = _hash_content(raw_content)
                if _maybe_cross_window_pair(
                    conn, vault_root, path, content_hash, pending_renames
                ):
                    continue
                upsert_note(conn, vault_root, path, raw_content)
                continue
            upsert_note(conn, vault_root, path)
        except Exception:  # noqa: BLE001 -- one bad note must not abort the rescan
            logger.exception("Failed to index note %s; skipping", path)
            if needs_schema_backfill:
                backfill_had_failures = True

    if needs_schema_backfill and not backfill_had_failures:
        with write_lock:
            conn.execute(f"PRAGMA user_version = {_SCHEMA_BACKFILL_VERSION}")


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


def _apply_retarget(
    conn: sqlite3.Connection,
    vault_root: Path,
    old_path: str,
    new_path: str,
    *,
    remove_old: bool,
) -> bool:
    """Calls `retarget_note_links(old_path, new_path)` and, on success,
    indexes `new_path` and every retargeted note as independent,
    individually-guarded operations (R7); on failure, logs and leaves the
    caller to fall back to independent delete/create handling.

    `remove_old` controls whether `old_path`'s index row is also removed
    here: a same-batch pair (`_apply_pairs`) needs it, since `old_path`
    hasn't been removed yet; a cross-window match
    (`_maybe_cross_window_pair`) doesn't, since that already happened in
    the earlier batch that deleted it.

    Returns whether the pair was applied.
    """
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
        return False

    if remove_old:
        _guarded_remove(conn, old_path)
    _guarded_upsert(conn, vault_root, new_path)
    for retargeted_path in retargeted:
        _guarded_upsert(conn, vault_root, retargeted_path)
    return True


def _apply_pairs(
    conn: sqlite3.Connection, vault_root: Path, pairs: list[tuple[str, str]]
) -> tuple[set[str], set[str]]:
    """Applies each confirmed same-batch rename pair via
    `_apply_retarget` (removing `old_path`'s row, since it hasn't been
    removed yet).

    Returns the `old_path`/`new_path` sets that were actually applied as
    renames, so the caller can exclude them from independent handling.
    """
    paired_old: set[str] = set()
    paired_new: set[str] = set()
    for old_path, new_path in pairs:
        if _apply_retarget(conn, vault_root, old_path, new_path, remove_old=True):
            paired_old.add(old_path)
            paired_new.add(new_path)

    return paired_old, paired_new


def _maybe_cross_window_pair(
    conn: sqlite3.Connection,
    vault_root: Path,
    new_path: str,
    content_hash: str,
    pending_renames: PendingRenameCache,
) -> bool:
    """Checks `pending_renames` for an unambiguous match on
    `content_hash`; if found, applies the rename via `_apply_retarget`
    (without removing the old side -- already applied in the batch that
    deleted it, possibly several batches ago). Shared by both
    `apply_watch_batch`'s new-arrival matching (U3) and `rebuild_index`'s
    backstop-rescan path (U4) -- the caller owns any batch-local
    ambiguity grouping before calling this; the cache's own
    hash-ambiguity rule (KTD1) always applies regardless.

    Returns whether `new_path` was handled as a cross-window rename. On
    `False` (no match, or the match's `retarget_note_links` call failed),
    the caller falls back to an ordinary upsert -- the consumed pending
    entry, if any, is not restored, so a failed match is not retried on a
    later batch or rescan tick.
    """
    old_path = pending_renames.pop_unambiguous_match(content_hash)
    if old_path is None:
        return False
    return _apply_retarget(conn, vault_root, old_path, new_path, remove_old=False)


@dataclass
class _BatchClassification:
    gone: set[str]
    present: set[str]
    old_hashes: dict[str, str]
    new_hashes: dict[str, str]


def _prepare_pending_renames(
    pending_renames: PendingRenameCache, present_paths: set[str], now: float
) -> None:
    """Shared preamble both `apply_watch_batch` and `rebuild_index` must
    run before consulting `pending_renames` for a match: prune entries
    older than the configured window (R3), then invalidate any entry for
    a path that currently exists (R8) -- a path that reappeared in the
    vault can never remain eligible as an unrelated later arrival's
    cross-window match source, whether or not its new content happens to
    match its own old hash.

    Originally only `apply_watch_batch` ran this (via its own `.prune()`
    call plus `_classify_batch`'s R8 loop); `rebuild_index`'s cache-aware
    branch consulted the cache without either step, found in code review
    -- an unpruned entry could match past its window, and an uninvalidated
    resurrected path's stale entry could hijack an unrelated later
    arrival's link retargeting.
    """
    pending_renames.prune(now)
    for path in present_paths:
        pending_renames.remove_by_path(path)


def _classify_batch(
    conn: sqlite3.Connection,
    vault_root: Path,
    rel_paths: set[str],
    pending_renames: PendingRenameCache,
    now: float,
) -> _BatchClassification:
    """Splits `rel_paths` into `gone`/`present`, runs
    `_prepare_pending_renames` for this batch's `present` set, and
    computes the content hashes same-batch and cross-window pairing both
    need.
    """
    gone = {path for path in rel_paths if not (vault_root / path).exists()}
    present = rel_paths - gone

    _prepare_pending_renames(pending_renames, present, now)

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
    # work only when nothing was deleted this batch AND the cache holds
    # nothing from an earlier batch, since neither same-batch nor
    # cross-window pairing can produce a match without one of those.
    new_hashes = (
        _hash_new_arrivals(vault_root, new_arrivals)
        if old_hashes or not pending_renames.is_empty()
        else {}
    )
    return _BatchClassification(gone, present, old_hashes, new_hashes)


def _match_cross_window_arrivals(
    conn: sqlite3.Connection,
    vault_root: Path,
    new_hashes: dict[str, str],
    paired_new: set[str],
    pending_renames: PendingRenameCache,
) -> set[str]:
    """Runs cross-window matching for this batch's unpaired new-arrival
    paths against `pending_renames`, per R2's batch-level ambiguity rule
    (KTD2 step 6): a hash shared by more than one new arrival *in this
    batch* is skipped entirely, mirroring `_match_unambiguous_pairs`'s
    two-sided grouping rather than a naive per-path lookup.

    Returns the set of new-arrival paths successfully matched and applied
    via `_maybe_cross_window_pair`, so the caller can exclude them from
    its ordinary-upsert fallback.
    """
    unpaired_new_hashes = {
        path: h for path, h in new_hashes.items() if path not in paired_new
    }
    hash_counts = Counter(unpaired_new_hashes.values())

    matched: set[str] = set()
    for path, content_hash in unpaired_new_hashes.items():
        if hash_counts[content_hash] != 1:
            continue
        if _maybe_cross_window_pair(
            conn, vault_root, path, content_hash, pending_renames
        ):
            matched.add(path)
    return matched


def apply_watch_batch(
    conn: sqlite3.Connection,
    vault_root: Path,
    rel_paths: set[str],
    pending_renames: PendingRenameCache,
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

    A delete and create landing in DIFFERENT batches still pair, as long
    as they fall within `pending_renames`'s configured window (R1): an
    unpaired `gone` path's hash is remembered via `pending_renames.add`,
    and a later batch's unpaired new-arrival paths are checked against it
    via `_maybe_cross_window_pair` before falling back to an ordinary
    upsert -- but only when a new-arrival hash is unique within *this*
    batch too (R2), mirroring `_match_unambiguous_pairs`'s two-sided
    grouping rather than a naive per-path lookup. A path that reappears
    in the vault invalidates its own pending entry first (R8), so it can
    never be used as an unrelated later arrival's match source.

    Every per-path/per-pair operation is individually contained (mirrors
    `rebuild_index`'s and `watch_vault`'s log-and-continue pattern), so
    one bad file, and a failed rename link-repointing (R7), never abort
    the rest of the batch.
    """
    now = time.monotonic()
    batch = _classify_batch(conn, vault_root, rel_paths, pending_renames, now)

    pairs = _match_unambiguous_pairs(batch.old_hashes, batch.new_hashes)
    paired_old, paired_new = _apply_pairs(conn, vault_root, pairs)

    # Cross-window matching runs against `pending_renames` as it stood
    # BEFORE this batch's own unpaired `gone` paths are added below --
    # otherwise a same-batch pair that just failed (both sides still
    # unpaired) would immediately "cross-window" match against itself
    # within this same call, re-attempting the identical doomed
    # `retarget_note_links` call for no benefit. Genuine cross-window
    # pairing is for a LATER batch observing an EARLIER one's leftover
    # entry, never this batch's own.
    cross_window_matched = _match_cross_window_arrivals(
        conn, vault_root, batch.new_hashes, paired_new, pending_renames
    )

    for path in batch.gone - paired_old:
        gone_hash = batch.old_hashes.get(path)
        if gone_hash is not None:
            pending_renames.add(path, gone_hash, now)
        _guarded_remove(conn, path)

    for path in batch.present - paired_new - cross_window_matched:
        _guarded_upsert(conn, vault_root, path)
