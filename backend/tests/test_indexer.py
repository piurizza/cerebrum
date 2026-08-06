from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from cerebrum.graph.service import get_backlinks, get_graph
from cerebrum.index import indexer
from cerebrum.index.db import list_notes, search_notes
from cerebrum.index.indexer import rebuild_index, remove_note, upsert_note
from cerebrum.notes.service import write_note


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
