from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from cerebrum.index.db import write_lock
from cerebrum.notes.models import ParsedLink
from cerebrum.notes.parser import parse_note
from cerebrum.notes.service import iter_note_paths, retarget_note_links

logger = logging.getLogger(__name__)


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

    Not thread-safe by design: `apply_watch_batch` and `rebuild_index`
    are never invoked concurrently with each other or themselves (each
    runs via a single sequential `asyncio.to_thread` call per caller), so
    a lock would only add overhead with nothing to protect against.
    """

    def __init__(self, window_seconds: float) -> None:
        self._window_seconds = window_seconds
        self._entries: list[_PendingDeletion] = []

    def add(self, path: str, content_hash: str, now: float) -> None:
        self._entries.append(_PendingDeletion(path, content_hash, now))

    def prune(self, now: float) -> None:
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
        self._entries = [entry for entry in self._entries if entry.path != path]

    def is_empty(self) -> bool:
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

    `pending_renames`, when supplied and non-empty, is consulted for a
    genuinely new (never-before-indexed) path the same way
    `apply_watch_batch`'s new-arrival matching does (R9) -- without this,
    a backstop tick landing between a cross-window rename's delete and
    create batches would index the new path as an ordinary note first,
    permanently defeating pairing for that rename (an already-indexed
    path is never a rename target, R2/R4). Omitted or empty, this
    behaves exactly as before this plan -- the startup rescan (which
    runs before any watcher state exists) always calls it this way.
    An already-indexed, merely-*changed* path never consults the cache
    either way -- only a path with no prior row at all is eligible,
    mirroring R4.
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

    consult_cache = pending_renames is not None and not pending_renames.is_empty()
    for path in current_paths:
        try:
            mtime = (vault_root / path).stat().st_mtime
            if existing_mtimes.get(path) == mtime:
                continue
            if consult_cache and path not in existing_mtimes:
                assert (
                    pending_renames is not None
                )  # narrows for mypy; see consult_cache
                content_hash = _hash_content(
                    (vault_root / path).read_text(encoding="utf-8")
                )
                if _maybe_cross_window_pair(
                    conn, vault_root, path, content_hash, pending_renames
                ):
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


def _maybe_cross_window_pair(
    conn: sqlite3.Connection,
    vault_root: Path,
    new_path: str,
    content_hash: str,
    pending_renames: PendingRenameCache,
) -> bool:
    """Checks `pending_renames` for an unambiguous match on
    `content_hash`; if found, applies the same rename outcome
    `_apply_pairs` does for a same-batch pair, minus `remove_note` for
    the old side (already applied in the batch that deleted it, possibly
    several batches ago). Shared by both `apply_watch_batch`'s
    new-arrival matching (U3) and `rebuild_index`'s backstop-rescan path
    (U4) -- the caller owns any batch-local ambiguity grouping before
    calling this; the cache's own hash-ambiguity rule (KTD1) always
    applies regardless.

    Returns whether `new_path` was handled as a cross-window rename. On
    `False` (no match, or the match's `retarget_note_links` call failed),
    the caller falls back to an ordinary upsert -- the consumed pending
    entry, if any, is not restored, so a failed match is not retried on a
    later batch or rescan tick.
    """
    old_path = pending_renames.pop_unambiguous_match(content_hash)
    if old_path is None:
        return False

    try:
        _, retargeted = retarget_note_links(vault_root, old_path, new_path)
    except Exception as exc:  # noqa: BLE001 -- falls back to ordinary upsert
        logger.warning(
            "failed to retarget links for cross-window rename %s -> %s; "
            "falling back to ordinary upsert: %s",
            old_path,
            new_path,
            exc,
        )
        return False

    _guarded_upsert(conn, vault_root, new_path)
    for retargeted_path in retargeted:
        _guarded_upsert(conn, vault_root, retargeted_path)
    return True


@dataclass
class _BatchClassification:
    gone: set[str]
    present: set[str]
    old_hashes: dict[str, str]
    new_hashes: dict[str, str]


def _classify_batch(
    conn: sqlite3.Connection,
    vault_root: Path,
    rel_paths: set[str],
    pending_renames: PendingRenameCache,
) -> _BatchClassification:
    """Splits `rel_paths` into `gone`/`present`, invalidates any pending
    cross-window entry for a path that reappeared (R8), and computes the
    content hashes same-batch and cross-window pairing both need.
    """
    gone = {path for path in rel_paths if not (vault_root / path).exists()}
    present = rel_paths - gone

    # R8: a path that reappeared in the vault can never remain eligible
    # as an unrelated later arrival's cross-window match source, whether
    # or not its new content happens to match its own old hash.
    for path in present:
        pending_renames.remove_by_path(path)

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
    hash_counts: dict[str, int] = {}
    for content_hash in unpaired_new_hashes.values():
        hash_counts[content_hash] = hash_counts.get(content_hash, 0) + 1

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
    pending_renames.prune(now)

    batch = _classify_batch(conn, vault_root, rel_paths, pending_renames)

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
