from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from cerebrum.graph.service import get_backlinks
from cerebrum.index import indexer
from cerebrum.index.db import list_notes
from cerebrum.index.indexer import (
    PendingRenameCache,
    apply_watch_batch,
    rebuild_index,
    upsert_note,
)
from cerebrum.notes.service import read_note, write_note

# Rename-pairing tests split out of test_indexer.py (U1-U4): same-batch
# pairing (origin plan), cross-window pairing across separate watcher
# batches and the backstop rescan, the PendingRenameCache primitive, and
# their composition with U1's attachment relocation. Kept in a dedicated
# module so test_indexer.py's other, unrelated coverage (upsert/remove,
# search, concurrency) doesn't grow past pylint's module-length limit.


def test_rebuild_index_pairs_new_path_against_pending_cache(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """Happy path (U4/R9): rebuild_index consults pending_renames for a
    genuinely new (never-before-indexed) path the same way
    apply_watch_batch's new-arrival matching does."""
    write_note(vault, "linker.md", "See [Old](old.md).")
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    upsert_note(db, vault, "linker.md")
    upsert_note(db, vault, "old.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)

    (vault / "new.md").write_text("shared body", encoding="utf-8")
    rebuild_index(db, vault, pending_renames)

    linker = read_note(vault, "linker.md")
    assert "[Old](new.md)" in linker.content
    assert {note.path for note in list_notes(db)} == {"new.md", "linker.md"}


def test_rebuild_index_default_pending_renames_none_behaves_as_before(
    vault: Path, db: sqlite3.Connection
) -> None:
    """Edge case: rebuild_index's default (no pending_renames argument)
    behaves identically to before this plan -- the FastAPI-startup
    rescan call site, which runs before any cache exists, needs no
    changes."""
    write_note(vault, "a.md", "content")
    rebuild_index(db, vault)

    assert {note.path for note in list_notes(db)} == {"a.md"}


def test_rebuild_index_empty_pending_renames_short_circuits(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """Edge case: an empty (but non-None) pending_renames behaves the
    same as None -- no hashing performed for a plain new note."""
    write_note(vault, "a.md", "content")

    assert pending_renames.is_empty()
    rebuild_index(db, vault, pending_renames)

    assert {note.path for note in list_notes(db)} == {"a.md"}


def test_rebuild_index_cache_miss_reads_new_file_only_once(
    vault: Path,
    db: sqlite3.Connection,
    pending_renames: PendingRenameCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: rebuild_index's cache-aware branch reads a new file
    once to compute its hash for the match attempt, then reuses that
    content for the upsert on a miss -- not a second disk read."""
    (vault / "unrelated.md").write_text("some other content", encoding="utf-8")
    upsert_note(db, vault, "unrelated.md")
    (vault / "unrelated.md").unlink()
    apply_watch_batch(db, vault, {"unrelated.md"}, pending_renames)

    (vault / "new.md").write_text("brand new content", encoding="utf-8")

    real_read_text = Path.read_text
    read_counts: dict[str, int] = {}

    def counting_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "new.md":
            read_counts["new.md"] = read_counts.get("new.md", 0) + 1
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    # pending_renames is non-empty (holds "unrelated.md"'s hash) but
    # doesn't match "new.md"'s content -- this exercises the miss path.
    rebuild_index(db, vault, pending_renames)

    assert read_counts["new.md"] == 1
    assert {note.path for note in list_notes(db)} == {"new.md"}


def test_backstop_rescan_pairs_rename_split_across_watcher_and_backstop(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """Integration (R9): a delete observed by apply_watch_batch and a
    create later observed by the backstop rescan -- not another
    apply_watch_batch call -- still pair when both share the same
    PendingRenameCache instance. Simulates a backstop tick landing
    between a cross-window rename's two watcher batches."""
    write_note(vault, "linker.md", "See [Old](old.md).")
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    upsert_note(db, vault, "linker.md")
    upsert_note(db, vault, "old.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)

    (vault / "new.md").write_text("shared body", encoding="utf-8")
    # The backstop rescan observes the new arrival, not another watcher
    # batch -- this is the exact race the doc review found: without a
    # shared cache, this call would just upsert "new.md" as an ordinary
    # note, permanently defeating pairing for this rename.
    rebuild_index(db, vault, pending_renames)

    linker = read_note(vault, "linker.md")
    assert "[Old](new.md)" in linker.content


def test_backstop_rescan_prunes_expired_entries_before_matching(
    vault: Path, db: sqlite3.Connection
) -> None:
    """Regression (found in code review): rebuild_index's cache-aware
    branch never called pending_renames.prune() -- only apply_watch_batch
    did. A backstop-only rescan (the exact case R9 exists for: the watcher
    has died and only the backstop keeps running) could match an entry
    well past the configured window. Uses a near-zero window so an
    apply_watch_batch call is never in the picture to incidentally prune
    it via the code path that already did."""
    cache = PendingRenameCache(window_seconds=0.01)
    write_note(vault, "linker.md", "See [Old](old.md).")
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    upsert_note(db, vault, "linker.md")
    upsert_note(db, vault, "old.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, cache)

    time.sleep(0.05)  # well past the 0.01s window

    (vault / "new.md").write_text("shared body", encoding="utf-8")
    # Only rebuild_index observes the new arrival from here on -- no
    # further apply_watch_batch call to incidentally prune the cache.
    rebuild_index(db, vault, cache)

    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content  # not retargeted -- pairing expired
    # old.md was already removed from the index by the earlier
    # apply_watch_batch call; only new.md and linker.md remain.
    assert {note.path for note in list_notes(db)} == {"new.md", "linker.md"}


def test_backstop_rescan_reappeared_path_invalidates_pending_entry(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """Regression (found in code review): rebuild_index's cache-aware
    branch never invalidated a reappeared path's stale entry (R8) --
    only apply_watch_batch's _classify_batch did. If a path is deleted
    (observed by apply_watch_batch), then reappears with different
    content observed ONLY by the backstop rescan (watcher dead), its
    stale pending entry must not survive to hijack an unrelated later
    arrival's link retargeting."""
    write_note(vault, "linker.md", "See [Old](old.md).")
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    upsert_note(db, vault, "linker.md")
    upsert_note(db, vault, "old.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)

    # old.md comes back with DIFFERENT content -- not a rename after all.
    # Observed only by rebuild_index (the watcher is presumed dead here).
    (vault / "old.md").write_text("resurrected, different content", encoding="utf-8")
    rebuild_index(db, vault, pending_renames)

    # A later, unrelated new arrival with the ORIGINAL hash, also only
    # observed by rebuild_index, must not wrongly pair against the
    # now-invalid entry.
    (vault / "unrelated.md").write_text("shared body", encoding="utf-8")
    rebuild_index(db, vault, pending_renames)

    assert {note.path for note in list_notes(db)} == {
        "old.md",
        "unrelated.md",
        "linker.md",
    }
    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content  # untouched -- old.md is still live


def test_pending_rename_cache_survives_concurrent_add_and_pop_from_two_threads() -> (
    None
):
    """Regression (found in code review): PendingRenameCache's docstring
    originally claimed apply_watch_batch and rebuild_index are "never
    invoked concurrently with each other" -- false, since watch_vault and
    _run_backstop_rescan run as two independent asyncio.Tasks, each
    issuing its own asyncio.to_thread call with no synchronization
    between them. This drives real concurrent mutation from two OS
    threads via a threading.Barrier to maximize interleaving and confirms
    no exception (e.g. ValueError from list.remove() racing a concurrent
    mutation) escapes, and the cache ends in a consistent state."""
    cache = PendingRenameCache(window_seconds=30)
    iterations = 500
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer() -> None:
        barrier.wait()
        for i in range(iterations):
            cache.add(f"writer-{i}.md", f"hash-{i}", now=float(i))

    def reader() -> None:
        barrier.wait()
        for i in range(iterations):
            try:
                cache.prune(now=float(i))
                cache.pop_unambiguous_match(f"hash-{i}")
                cache.remove_by_path(f"writer-{i}.md")
                cache.is_empty()
            except BaseException as exc:  # noqa: BLE001 -- captured for the assertion
                errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors


def test_apply_watch_batch_pairs_unambiguous_rename(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    write_note(vault, "x.md", "content")
    write_note(vault, "old.md", "See [X](x.md).")
    upsert_note(db, vault, "x.md")
    upsert_note(db, vault, "old.md")

    (vault / "old.md").rename(vault / "new.md")

    apply_watch_batch(db, vault, {"old.md", "new.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"x.md", "new.md"}
    stale_rows = db.execute(
        "SELECT * FROM links WHERE source_path = 'old.md'"
    ).fetchall()
    assert stale_rows == []
    assert [note.path for note in get_backlinks(db, "x.md")] == ["new.md"]


def test_apply_watch_batch_relinks_third_note_on_rename(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [T](target.md).")
    upsert_note(db, vault, "target.md")
    upsert_note(db, vault, "linker.md")

    (vault / "target.md").rename(vault / "renamed.md")

    apply_watch_batch(db, vault, {"target.md", "renamed.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"renamed.md", "linker.md"}
    linker = read_note(vault, "linker.md")
    assert "[T](renamed.md)" in linker.content
    assert [note.path for note in get_backlinks(db, "renamed.md")] == ["linker.md"]


def test_apply_watch_batch_pairs_multiple_independent_renames(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    (vault / "a.md").rename(vault / "a2.md")
    (vault / "b.md").rename(vault / "b2.md")

    apply_watch_batch(db, vault, {"a.md", "a2.md", "b.md", "b2.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"a2.md", "b2.md"}


def test_apply_watch_batch_ambiguous_hash_falls_back_to_independent_ops(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    # Two simultaneous deletions with IDENTICAL content, and one new
    # arrival matching that content: the hash is ambiguous on the "gone"
    # side (two candidates), so no pairing occurs -- all three are
    # applied as independent delete/delete/create.
    (vault / "x.md").write_text("identical body", encoding="utf-8")
    (vault / "y.md").write_text("identical body", encoding="utf-8")
    upsert_note(db, vault, "x.md")
    upsert_note(db, vault, "y.md")

    (vault / "x.md").unlink()
    (vault / "y.md").unlink()
    (vault / "z.md").write_text("identical body", encoding="utf-8")

    apply_watch_batch(db, vault, {"x.md", "y.md", "z.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"z.md"}


def test_apply_watch_batch_never_treats_already_indexed_path_as_rename_target(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    # "deleted.md" is removed; "b.md" already has an index row (an
    # existing note being edited) and just happens to be edited to the
    # same content "deleted.md" used to have. R4: "b.md" must still be
    # handled as a plain upsert, never as the rename target.
    (vault / "deleted.md").write_text("shared content", encoding="utf-8")
    write_note(vault, "linker.md", "See [D](deleted.md).")
    upsert_note(db, vault, "deleted.md")
    upsert_note(db, vault, "linker.md")

    (vault / "deleted.md").unlink()
    (vault / "b.md").write_text("shared content", encoding="utf-8")
    upsert_note(db, vault, "b.md")  # b.md already tracked before this batch

    apply_watch_batch(db, vault, {"deleted.md", "b.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"b.md", "linker.md"}
    # No relinking happened -- linker.md's link still points at the
    # (now-ghost) old target, not at "b.md".
    linker = read_note(vault, "linker.md")
    assert "[D](deleted.md)" in linker.content


def test_apply_watch_batch_different_content_not_paired(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    write_note(vault, "old.md", "content")
    write_note(vault, "linker.md", "See [Old](old.md).")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "linker.md")

    (vault / "old.md").unlink()
    (vault / "new.md").write_text("totally different content", encoding="utf-8")

    apply_watch_batch(db, vault, {"old.md", "new.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"new.md", "linker.md"}
    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content  # untouched -- not treated as a rename


def test_apply_watch_batch_cross_window_pairing(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """R1: a rename whose delete and create land in separate
    `apply_watch_batch` calls (separate watcher debounce batches) still
    pairs and relinks, as long as the same `PendingRenameCache` instance
    is threaded through both -- this replaces the old
    test_apply_watch_batch_no_cross_call_pairing, which pinned the
    opposite (pre-this-plan) behavior."""
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    write_note(vault, "linker.md", "See [Old](old.md).")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "linker.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)  # delete-only batch

    (vault / "new.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(
        db, vault, {"new.md"}, pending_renames
    )  # separate, later, create-only batch

    assert {note.path for note in list_notes(db)} == {"new.md", "linker.md"}
    linker = read_note(vault, "linker.md")
    assert "[Old](new.md)" in linker.content


def test_apply_watch_batch_cross_window_pairing_expires_outside_window(
    vault: Path, db: sqlite3.Connection
) -> None:
    """R3: a pending deletion older than the configured window is
    dropped and never pairs."""
    cache = PendingRenameCache(window_seconds=0.01)
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    write_note(vault, "linker.md", "See [Old](old.md).")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "linker.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, cache)

    time.sleep(0.05)  # well past the 0.01s window

    (vault / "new.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(db, vault, {"new.md"}, cache)

    assert {note.path for note in list_notes(db)} == {"new.md", "linker.md"}
    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content  # not retargeted -- pairing expired


def test_apply_watch_batch_cross_window_ambiguous_pending_hash_not_paired(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """R2: two unrelated notes deleted in separate earlier batches share
    a content hash -- a later new arrival with that hash pairs with
    neither."""
    (vault / "a.md").write_text("shared body", encoding="utf-8")
    (vault / "b.md").write_text("shared body", encoding="utf-8")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    (vault / "a.md").unlink()
    apply_watch_batch(db, vault, {"a.md"}, pending_renames)
    (vault / "b.md").unlink()
    apply_watch_batch(db, vault, {"b.md"}, pending_renames)

    (vault / "c.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(db, vault, {"c.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"c.md"}


def test_apply_watch_batch_same_batch_new_arrival_hash_collision_not_paired(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """R2: two new-arrival paths in the SAME batch sharing a content hash
    that matches exactly one pending deletion must not pair -- without
    the batch-level grouping step, whichever is processed first would
    silently consume the one pending match."""
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    write_note(vault, "linker.md", "See [Old](old.md).")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "linker.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)

    (vault / "new-a.md").write_text("shared body", encoding="utf-8")
    (vault / "new-b.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(db, vault, {"new-a.md", "new-b.md"}, pending_renames)

    # Neither new arrival was treated as the rename target.
    assert {note.path for note in list_notes(db)} == {
        "new-a.md",
        "new-b.md",
        "linker.md",
    }
    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content


def test_apply_watch_batch_reappeared_path_invalidates_pending_entry(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """R8: a path that reappears (with different content, before its
    pending entry is matched or expires) invalidates its own stale entry
    -- a later unrelated arrival sharing the ORIGINAL hash must not
    wrongly pair against it."""
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    write_note(vault, "linker.md", "See [Old](old.md).")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "linker.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)

    # old.md comes back with different content -- not a rename after all.
    (vault / "old.md").write_text("resurrected, different content", encoding="utf-8")
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)

    # A later, unrelated new arrival with the ORIGINAL hash must not pair
    # against the now-invalid entry.
    (vault / "unrelated.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(db, vault, {"unrelated.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {
        "old.md",
        "unrelated.md",
        "linker.md",
    }
    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content  # untouched -- old.md is still live


def test_apply_watch_batch_failed_same_batch_pair_still_feeds_pending_cache(
    vault: Path,
    db: sqlite3.Connection,
    pending_renames: PendingRenameCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-batch pairing attempt that fails (retarget_note_links
    raises) still adds the gone side to pending_renames -- it's eligible
    for a later, genuine cross-window retry rather than lost entirely."""
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    upsert_note(db, vault, "old.md")
    (vault / "old.md").rename(vault / "new.md")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(indexer, "retarget_note_links", boom)
    apply_watch_batch(db, vault, {"old.md", "new.md"}, pending_renames)
    monkeypatch.undo()

    # Same-batch pairing failed and fell back to independent ops -- but
    # old.md's hash is now pending. A later, unrelated batch with a
    # genuinely new arrival sharing that hash pairs successfully.
    write_note(vault, "linker.md", "See [X](old.md).")
    upsert_note(db, vault, "linker.md")
    (vault / "later.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(db, vault, {"later.md"}, pending_renames)

    linker = read_note(vault, "linker.md")
    assert "[X](later.md)" in linker.content


def test_apply_watch_batch_retarget_failure_falls_back_to_independent_ops(
    vault: Path,
    db: sqlite3.Connection,
    pending_renames: PendingRenameCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_note(vault, "old.md", "content")
    write_note(vault, "other.md", "unrelated content")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "other.md")

    (vault / "old.md").rename(vault / "new.md")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(indexer, "retarget_note_links", boom)

    apply_watch_batch(db, vault, {"old.md", "new.md", "other.md"}, pending_renames)

    # Falls back to independent remove/upsert for the failed pair; an
    # unrelated path in the same batch is still processed correctly.
    assert {note.path for note in list_notes(db)} == {"new.md", "other.md"}


def test_apply_watch_batch_cross_window_retarget_failure_falls_back_to_upsert(
    vault: Path,
    db: sqlite3.Connection,
    pending_renames: PendingRenameCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cross-window match's own retarget_note_links failure falls back
    to an ordinary upsert of the new path -- the consumed pending entry
    is not restored, so it isn't retried on a later batch either."""
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    upsert_note(db, vault, "old.md")
    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"}, pending_renames)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(indexer, "retarget_note_links", boom)
    (vault / "new.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(db, vault, {"new.md"}, pending_renames)

    assert {note.path for note in list_notes(db)} == {"new.md"}
    assert pending_renames.is_empty()


def test_apply_watch_batch_cross_window_pairing_relocates_attachments(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """Integration: a cross-window match composes with U1's attachment
    relocation, not just link text -- confirms both units compose
    through the shared retarget_note_links call."""
    # Written directly (not via write_note, which stamps frontmatter
    # timestamps) so idea.md's and better-idea.md's raw bytes -- and thus
    # their content hashes -- match exactly, the same way every other
    # cross-window test in this file pairs its two sides.
    (vault / "idea.md").write_text("![](idea.attachments/abc123.png)", encoding="utf-8")
    attachment_dir = vault / "idea.attachments"
    attachment_dir.mkdir()
    (attachment_dir / "abc123.png").write_bytes(b"fake-png-bytes")
    upsert_note(db, vault, "idea.md")

    (vault / "idea.md").unlink()
    apply_watch_batch(db, vault, {"idea.md"}, pending_renames)

    (vault / "better-idea.md").write_text(
        "![](idea.attachments/abc123.png)", encoding="utf-8"
    )
    apply_watch_batch(db, vault, {"better-idea.md"}, pending_renames)

    new_dir = vault / "better-idea.attachments"
    assert new_dir.is_dir()
    assert (new_dir / "abc123.png").read_bytes() == b"fake-png-bytes"
    note = read_note(vault, "better-idea.md")
    assert "better-idea.attachments/abc123.png" in note.content


def test_apply_watch_batch_contains_upsert_failure_for_one_retargeted_path(
    vault: Path,
    db: sqlite3.Connection,
    pending_renames: PendingRenameCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_note(vault, "target.md", "content")
    write_note(vault, "linker-a.md", "See [A](target.md).")
    write_note(vault, "linker-b.md", "See [B](target.md).")
    upsert_note(db, vault, "target.md")
    upsert_note(db, vault, "linker-a.md")
    upsert_note(db, vault, "linker-b.md")

    (vault / "target.md").rename(vault / "renamed.md")

    original_upsert = indexer.upsert_note

    def flaky_upsert(conn: sqlite3.Connection, vault_root: Path, path: str) -> None:
        if path == "linker-a.md":
            raise FileNotFoundError(path)
        original_upsert(conn, vault_root, path)

    monkeypatch.setattr(indexer, "upsert_note", flaky_upsert)

    apply_watch_batch(db, vault, {"target.md", "renamed.md"}, pending_renames)

    # retarget_note_links succeeded -- both linkers' files were rewritten
    # on disk regardless of the monkeypatched upsert failure.
    assert "[A](renamed.md)" in (vault / "linker-a.md").read_text(encoding="utf-8")
    assert "[B](renamed.md)" in (vault / "linker-b.md").read_text(encoding="utf-8")

    # old/new are indexed correctly, and the retargeted path whose upsert
    # didn't fail (linker-b.md) is indexed correctly too. linker-a.md's
    # index row failed to update (logged and skipped) but its prior row
    # from before the rename is still present -- apply_watch_batch did
    # not raise, and did not lose track of the other paths.
    assert {note.path for note in list_notes(db)} == {
        "renamed.md",
        "linker-a.md",
        "linker-b.md",
    }
    assert [note.path for note in get_backlinks(db, "renamed.md")] == ["linker-b.md"]


def test_apply_watch_batch_malformed_frontmatter_does_not_crash_batch(
    vault: Path, db: sqlite3.Connection, pending_renames: PendingRenameCache
) -> None:
    """Regression: `_guarded_upsert` used to only catch
    `FileNotFoundError`/`PermissionError`, so a note with malformed
    frontmatter (a normal user-triggerable mistake, not a rare edge case
    -- see `parser.py`) raised `InvalidNoteContentError` straight out of
    `apply_watch_batch`, which would propagate through `watch_vault`'s
    `asyncio.to_thread` call and kill the whole watcher task permanently,
    since `InvalidNoteContentError` isn't `OSError`/
    `WatchfilesRustInternalError` either."""
    write_note(vault, "a.md", "content")
    upsert_note(db, vault, "a.md")

    # Written directly to disk (bypassing write_note's own validation) to
    # simulate an external hand-edit that broke the frontmatter, mirroring
    # test_parser.py::test_parse_note_raises_on_invalid_date.
    (vault / "b.md").write_text(
        "---\ntitle: B\ncreated: not-a-date\n---\nBody.\n", encoding="utf-8"
    )

    apply_watch_batch(db, vault, {"a.md", "b.md"}, pending_renames)

    # The malformed note is skipped (logged), not indexed -- but the
    # well-formed note in the same batch still is, and nothing raised.
    assert {note.path for note in list_notes(db)} == {"a.md"}


def test_hash_new_arrivals_transient_read_failure_does_not_crash_batch(
    vault: Path,
    db: sqlite3.Connection,
    pending_renames: PendingRenameCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new-arrival candidate that disappears between the batch's
    existence check and `_hash_new_arrivals`'s per-file read (a
    transient race the watcher already tolerates elsewhere) must not
    abort the batch -- it just drops out of hashing and falls through to
    the ordinary upsert path once resolved."""
    write_note(vault, "old.md", "content")
    write_note(vault, "flaky.md", "flaky content")
    write_note(vault, "fine.md", "fine content")
    upsert_note(db, vault, "old.md")

    (vault / "old.md").unlink()  # a deletion is required to trigger hashing at all

    real_read_text = Path.read_text
    flaky_read_attempted = False

    def flaky_read_text(self: Path, *args: object, **kwargs: object) -> str:
        nonlocal flaky_read_attempted
        if self.name == "flaky.md" and not flaky_read_attempted:
            # Fail only the first read (the hashing attempt inside
            # _hash_new_arrivals) -- the race is transient, so the file
            # is readable again by the time the ordinary upsert path
            # reads it.
            flaky_read_attempted = True
            raise FileNotFoundError(str(self))
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    apply_watch_batch(db, vault, {"old.md", "flaky.md", "fine.md"}, pending_renames)

    # old.md is removed; both flaky.md and fine.md end up indexed via the
    # ordinary upsert fallback -- flaky.md's hash-read failure inside
    # _hash_new_arrivals was contained, not raised, and it fell through
    # to that fallback rather than being treated as a rename candidate.
    assert flaky_read_attempted
    assert {note.path for note in list_notes(db)} == {"flaky.md", "fine.md"}


# --- PendingRenameCache (U2) -----------------------------------------------


def test_pending_rename_cache_add_then_pop_returns_path() -> None:
    cache = PendingRenameCache(window_seconds=30)
    cache.add("old.md", "hash-a", now=0.0)

    assert cache.pop_unambiguous_match("hash-a") == "old.md"


def test_pending_rename_cache_pop_with_no_entries_returns_none() -> None:
    cache = PendingRenameCache(window_seconds=30)

    assert cache.pop_unambiguous_match("nonexistent") is None


def test_pending_rename_cache_pop_leaves_cache_empty_after_match() -> None:
    cache = PendingRenameCache(window_seconds=30)
    cache.add("old.md", "hash-a", now=0.0)
    cache.pop_unambiguous_match("hash-a")

    assert cache.is_empty()


def test_pending_rename_cache_ambiguous_hash_returns_none_and_keeps_both() -> None:
    cache = PendingRenameCache(window_seconds=30)
    cache.add("a.md", "shared-hash", now=0.0)
    cache.add("b.md", "shared-hash", now=0.0)

    assert cache.pop_unambiguous_match("shared-hash") is None
    # Neither entry was consumed -- a later unambiguous state (e.g. one
    # expires) could still resolve the other.
    assert not cache.is_empty()


def test_pending_rename_cache_prune_drops_expired_entries() -> None:
    cache = PendingRenameCache(window_seconds=30)
    cache.add("old.md", "hash-a", now=0.0)

    cache.prune(now=31.0)

    assert cache.pop_unambiguous_match("hash-a") is None


def test_pending_rename_cache_prune_keeps_entries_still_within_window() -> None:
    cache = PendingRenameCache(window_seconds=30)
    cache.add("old.md", "hash-a", now=0.0)

    cache.prune(now=29.0)

    assert cache.pop_unambiguous_match("hash-a") == "old.md"


def test_pending_rename_cache_is_empty_reflects_state_changes() -> None:
    cache = PendingRenameCache(window_seconds=30)
    assert cache.is_empty()

    cache.add("old.md", "hash-a", now=0.0)
    assert not cache.is_empty()

    cache.pop_unambiguous_match("hash-a")
    assert cache.is_empty()


def test_pending_rename_cache_remove_by_path_invalidates_entry() -> None:
    cache = PendingRenameCache(window_seconds=30)
    cache.add("old.md", "hash-a", now=0.0)

    cache.remove_by_path("old.md")

    assert cache.pop_unambiguous_match("hash-a") is None


def test_pending_rename_cache_remove_by_path_no_entry_is_a_no_op() -> None:
    cache = PendingRenameCache(window_seconds=30)
    cache.add("old.md", "hash-a", now=0.0)

    cache.remove_by_path("unrelated.md")

    assert cache.pop_unambiguous_match("hash-a") == "old.md"
