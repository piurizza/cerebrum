from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from cerebrum.graph.service import get_backlinks, get_graph
from cerebrum.index import indexer
from cerebrum.index.db import list_notes, search_notes
from cerebrum.index.indexer import (
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
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "x.md", "content")
    write_note(vault, "old.md", "See [X](x.md).")
    upsert_note(db, vault, "x.md")
    upsert_note(db, vault, "old.md")

    (vault / "old.md").rename(vault / "new.md")

    apply_watch_batch(db, vault, {"old.md", "new.md"})

    assert {note.path for note in list_notes(db)} == {"x.md", "new.md"}
    stale_rows = db.execute(
        "SELECT * FROM links WHERE source_path = 'old.md'"
    ).fetchall()
    assert stale_rows == []
    assert [note.path for note in get_backlinks(db, "x.md")] == ["new.md"]


def test_apply_watch_batch_relinks_third_note_on_rename(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [T](target.md).")
    upsert_note(db, vault, "target.md")
    upsert_note(db, vault, "linker.md")

    (vault / "target.md").rename(vault / "renamed.md")

    apply_watch_batch(db, vault, {"target.md", "renamed.md"})

    assert {note.path for note in list_notes(db)} == {"renamed.md", "linker.md"}
    linker = read_note(vault, "linker.md")
    assert "[T](renamed.md)" in linker.content
    assert [note.path for note in get_backlinks(db, "renamed.md")] == ["linker.md"]


def test_apply_watch_batch_pairs_multiple_independent_renames(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")

    (vault / "a.md").rename(vault / "a2.md")
    (vault / "b.md").rename(vault / "b2.md")

    apply_watch_batch(db, vault, {"a.md", "a2.md", "b.md", "b2.md"})

    assert {note.path for note in list_notes(db)} == {"a2.md", "b2.md"}


def test_apply_watch_batch_ambiguous_hash_falls_back_to_independent_ops(
    vault: Path, db: sqlite3.Connection
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

    apply_watch_batch(db, vault, {"x.md", "y.md", "z.md"})

    assert {note.path for note in list_notes(db)} == {"z.md"}


def test_apply_watch_batch_never_treats_already_indexed_path_as_rename_target(
    vault: Path, db: sqlite3.Connection
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

    apply_watch_batch(db, vault, {"deleted.md", "b.md"})

    assert {note.path for note in list_notes(db)} == {"b.md", "linker.md"}
    # No relinking happened -- linker.md's link still points at the
    # (now-ghost) old target, not at "b.md".
    linker = read_note(vault, "linker.md")
    assert "[D](deleted.md)" in linker.content


def test_apply_watch_batch_different_content_not_paired(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "old.md", "content")
    write_note(vault, "linker.md", "See [Old](old.md).")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "linker.md")

    (vault / "old.md").unlink()
    (vault / "new.md").write_text("totally different content", encoding="utf-8")

    apply_watch_batch(db, vault, {"old.md", "new.md"})

    assert {note.path for note in list_notes(db)} == {"new.md", "linker.md"}
    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content  # untouched -- not treated as a rename


def test_apply_watch_batch_no_cross_call_pairing(
    vault: Path, db: sqlite3.Connection
) -> None:
    (vault / "old.md").write_text("shared body", encoding="utf-8")
    write_note(vault, "linker.md", "See [Old](old.md).")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "linker.md")

    (vault / "old.md").unlink()
    apply_watch_batch(db, vault, {"old.md"})  # delete-only batch

    (vault / "new.md").write_text("shared body", encoding="utf-8")
    apply_watch_batch(db, vault, {"new.md"})  # separate, later, create-only batch

    assert {note.path for note in list_notes(db)} == {"new.md", "linker.md"}
    linker = read_note(vault, "linker.md")
    assert "[Old](old.md)" in linker.content  # not retargeted -- no cross-call pairing


def test_apply_watch_batch_retarget_failure_falls_back_to_independent_ops(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_note(vault, "old.md", "content")
    write_note(vault, "other.md", "unrelated content")
    upsert_note(db, vault, "old.md")
    upsert_note(db, vault, "other.md")

    (vault / "old.md").rename(vault / "new.md")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(indexer, "retarget_note_links", boom)

    apply_watch_batch(db, vault, {"old.md", "new.md", "other.md"})

    # Falls back to independent remove/upsert for the failed pair; an
    # unrelated path in the same batch is still processed correctly.
    assert {note.path for note in list_notes(db)} == {"new.md", "other.md"}


def test_apply_watch_batch_contains_upsert_failure_for_one_retargeted_path(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
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

    apply_watch_batch(db, vault, {"target.md", "renamed.md"})

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
