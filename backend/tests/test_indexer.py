from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from cerebrum.graph.service import get_backlinks, get_graph
from cerebrum.index import indexer
from cerebrum.index.db import list_notes, search_notes
from cerebrum.index.indexer import (
    PendingRenameCache,
    apply_watch_batch,
    rebuild_index,
    remove_note,
    upsert_note,
)
from cerebrum.notes.service import read_note, write_note


def test_rebuild_index_populates_notes_and_links(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "---\ntitle: A\n---\nSee [B](b.md).\n")
    write_note(vault, "b.md", "---\ntitle: B\n---\nNo links here.\n")

    rebuild_index(db, vault)

    notes = list_notes(db)
    assert {note.path for note in notes} == {"a.md", "b.md"}

    graph = get_graph(db)
    assert {edge.source: edge.target for edge in graph.edges} == {"a.md": "b.md"}


def test_rebuild_index_removes_deleted_notes(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "content")
    rebuild_index(db, vault)

    (vault / "a.md").unlink()
    rebuild_index(db, vault)

    assert list_notes(db) == []


def test_upsert_note_updates_backlinks(vault: Path, db: sqlite3.Connection) -> None:
    write_note(vault, "a.md", "See [B](b.md).")
    write_note(vault, "b.md", "content")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    backlinks = get_backlinks(db, "b.md")

    assert [note.path for note in backlinks] == ["a.md"]


def test_remove_note_drops_its_outgoing_links(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "See [B](b.md).")
    write_note(vault, "b.md", "content")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    remove_note(db, "a.md")

    assert get_backlinks(db, "b.md") == []
    assert {note.path for note in list_notes(db)} == {"b.md"}


def test_broken_link_surfaces_as_ghost_node(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "See [Missing](missing.md).")
    upsert_note(db, vault, "a.md")

    graph = get_graph(db)

    nodes_by_path = {node.path: node for node in graph.nodes}
    assert nodes_by_path["a.md"].exists is True
    assert nodes_by_path["missing.md"].exists is False


def test_upsert_note_dedupes_duplicate_links(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "See [Home](b.md) and again [Home](b.md).")
    write_note(vault, "b.md", "content")

    upsert_note(db, vault, "a.md")  # must not raise sqlite3.IntegrityError
    upsert_note(db, vault, "b.md")

    backlinks = get_backlinks(db, "b.md")
    assert [note.path for note in backlinks] == ["a.md"]


def test_get_backlinks_dedupes_multiple_distinct_links_from_same_note(
    vault: Path, db: sqlite3.Connection
) -> None:
    # Two DIFFERENT links (different text/fragment) from the same note to
    # the same target are two rows in `links`, but still one backlink.
    write_note(vault, "a.md", "See [Home](b.md) and also [Elsewhere](b.md#section).")
    write_note(vault, "b.md", "content")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    backlinks = get_backlinks(db, "b.md")

    assert [note.path for note in backlinks] == ["a.md"]


def test_get_graph_dedupes_multiple_distinct_links_between_same_notes(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "See [Home](b.md) and also [Elsewhere](b.md#section).")
    write_note(vault, "b.md", "content")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    graph = get_graph(db)

    assert [(edge.source, edge.target) for edge in graph.edges] == [("a.md", "b.md")]


def test_rebuild_index_skips_unchanged_note(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_note(vault, "a.md", "content")
    rebuild_index(db, vault)

    calls: list[str] = []
    original_upsert = indexer.upsert_note

    def spy_upsert(conn: sqlite3.Connection, vault_root: Path, path: str) -> None:
        calls.append(path)
        original_upsert(conn, vault_root, path)

    monkeypatch.setattr(indexer, "upsert_note", spy_upsert)

    rebuild_index(db, vault)

    assert not calls


def test_rebuild_index_reprocesses_changed_note(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "---\ntitle: Old\n---\nBody.\n")
    rebuild_index(db, vault)

    write_note(vault, "a.md", "---\ntitle: New\n---\nBody.\n")
    rebuild_index(db, vault)

    notes = list_notes(db)
    assert notes[0].title == "New"


def test_search_notes_matches_body_content(vault: Path, db: sqlite3.Connection) -> None:
    write_note(vault, "a.md", "---\ntitle: Recipe\n---\nHow to bake bread.\n")
    write_note(vault, "b.md", "---\ntitle: Travel\n---\nNotes about Japan.\n")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    results = search_notes(db, "bread")

    assert [note.path for note in results] == ["a.md"]


def test_search_notes_matches_title(vault: Path, db: sqlite3.Connection) -> None:
    write_note(vault, "a.md", "---\ntitle: Recipe\n---\nBody.\n")
    upsert_note(db, vault, "a.md")

    assert [note.path for note in search_notes(db, "Recipe")] == ["a.md"]


def test_search_notes_is_prefix_match(vault: Path, db: sqlite3.Connection) -> None:
    write_note(vault, "a.md", "---\ntitle: Recipe\n---\nBaking instructions.\n")
    upsert_note(db, vault, "a.md")

    assert [note.path for note in search_notes(db, "bak")] == ["a.md"]


def test_search_notes_requires_all_terms(vault: Path, db: sqlite3.Connection) -> None:
    write_note(vault, "a.md", "---\ntitle: A\n---\nbread and butter.\n")
    write_note(vault, "b.md", "---\ntitle: B\n---\njust bread.\n")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    assert [note.path for note in search_notes(db, "bread butter")] == ["a.md"]


def test_search_notes_empty_query_returns_nothing(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "content")
    upsert_note(db, vault, "a.md")

    assert search_notes(db, "") == []
    assert search_notes(db, "   ") == []


def test_search_notes_ignores_deleted_notes(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "---\ntitle: Recipe\n---\nBread.\n")
    upsert_note(db, vault, "a.md")
    remove_note(db, "a.md")

    assert search_notes(db, "bread") == []


_CHURN_ITERATIONS = 30


def _run_rebuild(
    vault: Path,
    db: sqlite3.Connection,
    outcomes: list[Exception | None],
    index: int,
) -> None:
    try:
        for _ in range(_CHURN_ITERATIONS):
            rebuild_index(db, vault)
        outcomes[index] = None
    except Exception as exc:  # noqa: BLE001 -- captured for the test to inspect
        outcomes[index] = exc


def _run_write_churn(
    target: tuple[Path, sqlite3.Connection, str],
    outcomes: list[Exception | None],
    index: int,
) -> None:
    vault, db, path = target
    try:
        for _ in range(_CHURN_ITERATIONS):
            upsert_note(db, vault, path)
            remove_note(db, path)
        outcomes[index] = None
    except Exception as exc:  # noqa: BLE001 -- captured for the test to inspect
        outcomes[index] = exc


def _run_read_churn(
    db: sqlite3.Connection,
    outcomes: list[Exception | None],
    index: int,
) -> None:
    try:
        for _ in range(_CHURN_ITERATIONS):
            list_notes(db)
            search_notes(db, "content")
        outcomes[index] = None
    except Exception as exc:  # noqa: BLE001 -- captured for the test to inspect
        outcomes[index] = exc


def _run_graph_read_churn(
    db: sqlite3.Connection,
    outcomes: list[Exception | None],
    index: int,
) -> None:
    try:
        for _ in range(_CHURN_ITERATIONS):
            get_graph(db)
            get_backlinks(db, "a.md")
        outcomes[index] = None
    except Exception as exc:  # noqa: BLE001 -- captured for the test to inspect
        outcomes[index] = exc


def test_concurrent_rebuild_index_and_writes_do_not_raise(
    vault: Path, db: sqlite3.Connection
) -> None:
    """Regression test for KTD5: rebuild_index's unlocked
    `SELECT path, mtime FROM notes` used to be able to race a concurrent
    upsert_note/remove_note write against the same shared connection and
    surface as a raw sqlite3.InterfaceError instead of a clean exception
    (or no exception at all). Several threads hammer rebuild_index and
    per-note writes concurrently; none of them should raise anything, and
    the index should still correctly reflect the vault once the dust
    settles.
    """
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")
    write_note(vault, "c.md", "content c")
    rebuild_index(db, vault)

    outcomes: list[Exception | None] = [None] * 4
    threads = [
        threading.Thread(target=_run_rebuild, args=(vault, db, outcomes, 0)),
        threading.Thread(target=_run_rebuild, args=(vault, db, outcomes, 1)),
        threading.Thread(
            target=_run_write_churn, args=((vault, db, "a.md"), outcomes, 2)
        ),
        threading.Thread(
            target=_run_write_churn, args=((vault, db, "b.md"), outcomes, 3)
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes == [None, None, None, None]

    # Settle: a final rebuild must correctly reflect the vault's actual
    # contents, regardless of which writer "won" the race above -- every
    # note file still exists on disk, none were unlinked.
    rebuild_index(db, vault)
    assert {note.path for note in list_notes(db)} == {"a.md", "b.md", "c.md"}


def test_concurrent_list_and_search_notes_with_writes_do_not_raise(
    vault: Path, db: sqlite3.Connection
) -> None:
    """Regression test for KTD5: list_notes and search_notes's unlocked
    reads used to be able to race a concurrent upsert_note/remove_note
    write against the same shared connection and surface as a raw
    sqlite3.InterfaceError instead of running to completion cleanly.
    """
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")
    rebuild_index(db, vault)

    outcomes: list[Exception | None] = [None] * 4
    threads = [
        threading.Thread(target=_run_read_churn, args=(db, outcomes, 0)),
        threading.Thread(target=_run_read_churn, args=(db, outcomes, 1)),
        threading.Thread(
            target=_run_write_churn, args=((vault, db, "a.md"), outcomes, 2)
        ),
        threading.Thread(
            target=_run_write_churn, args=((vault, db, "b.md"), outcomes, 3)
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes == [None, None, None, None]


def test_concurrent_graph_reads_with_writes_do_not_raise(
    vault: Path, db: sqlite3.Connection
) -> None:
    """Regression test: get_graph/get_backlinks (graph/service.py) had the
    same unlocked-read hazard as list_notes/search_notes/rebuild_index
    before the review fix that added write_lock there too -- code review
    found this second instance after the primary KTD5 fix landed.
    """
    write_note(vault, "a.md", "See [B](b.md).")
    write_note(vault, "b.md", "content b")
    rebuild_index(db, vault)

    outcomes: list[Exception | None] = [None] * 4
    threads = [
        threading.Thread(target=_run_graph_read_churn, args=(db, outcomes, 0)),
        threading.Thread(target=_run_graph_read_churn, args=(db, outcomes, 1)),
        threading.Thread(
            target=_run_write_churn, args=((vault, db, "a.md"), outcomes, 2)
        ),
        threading.Thread(
            target=_run_write_churn, args=((vault, db, "b.md"), outcomes, 3)
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes == [None, None, None, None]


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
