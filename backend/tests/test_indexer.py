from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from cerebrum.graph.models import GraphEdge
from cerebrum.graph.service import get_backlinks, get_graph
from cerebrum.index import indexer
from cerebrum.index.db import list_notes, search_notes
from cerebrum.index.indexer import (
    _SCHEMA_BACKFILL_VERSION,
    PendingRenameCache,
    apply_watch_batch,
    rebuild_index,
    remove_note,
    upsert_note,
)
from cerebrum.notes.service import InvalidNotePathError, write_note
from cerebrum.tasks.service import list_open_tasks


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


def test_upsert_note_raw_content_skips_disk_read(
    vault: Path, db: sqlite3.Connection
) -> None:
    """upsert_note's optional raw_content param uses the supplied content
    instead of reading the file -- used by rebuild_index's cache-aware
    branch to avoid a redundant read+hash for content it already read to
    check for a cross-window rename match."""
    write_note(vault, "a.md", "on-disk content")

    upsert_note(db, vault, "a.md", raw_content="See [B](b.md).")

    # The index reflects the SUPPLIED content, not what's on disk.
    assert [note.path for note in get_backlinks(db, "b.md")] == ["a.md"]


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


def _task_rows(db: sqlite3.Connection, path: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT line, checked, text FROM tasks WHERE source_path = ? ORDER BY line",
        (path,),
    ).fetchall()


def test_upsert_note_persists_open_and_closed_tasks(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "- [ ] Open one\n- [x] Closed one\n- [ ] Open two\n")

    upsert_note(db, vault, "a.md")

    rows = _task_rows(db, "a.md")
    assert [(row["checked"], row["text"]) for row in rows] == [
        (0, "Open one"),
        (1, "Closed one"),
        (0, "Open two"),
    ]


def test_upsert_note_replaces_stale_task_rows_on_reupsert(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "- [ ] First\n- [ ] Second\n")
    upsert_note(db, vault, "a.md")

    # Remove "Second", add "Third", and check off "First" -- the old rows
    # must not linger alongside the new ones.
    write_note(vault, "a.md", "- [x] First\n- [ ] Third\n")
    upsert_note(db, vault, "a.md")

    rows = _task_rows(db, "a.md")
    assert [(row["checked"], row["text"]) for row in rows] == [
        (1, "First"),
        (0, "Third"),
    ]


def test_remove_note_drops_its_task_rows(vault: Path, db: sqlite3.Connection) -> None:
    write_note(vault, "a.md", "- [ ] A task\n")
    upsert_note(db, vault, "a.md")

    # Regression proof for the source_path-not-path fix: this must not
    # raise sqlite3.OperationalError, and must actually delete the rows.
    remove_note(db, "a.md")

    assert _task_rows(db, "a.md") == []


def test_upsert_note_with_no_checkboxes_persists_no_task_rows(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "Just prose, no checkboxes here.\n")

    upsert_note(db, vault, "a.md")

    assert _task_rows(db, "a.md") == []


def test_rebuild_index_force_backfills_tasks_after_schema_version_reset(
    vault: Path, db: sqlite3.Connection
) -> None:
    """Regression test: rebuild_index normally skips a note whose mtime
    hasn't changed since it was last indexed -- correct on an ordinary
    startup, but wrong the first time a schema change adds a new kind of
    derived row (the tasks table): a note that was indexed before that
    change was never upserted under the new schema, so it never got the
    new rows, and its unchanged mtime would otherwise hide that gap
    forever. Simulates an upgrade by resetting PRAGMA user_version back
    to 0 without touching the note file (so its mtime is genuinely
    unchanged) and clearing its task rows the way an old database would
    never have had them."""
    write_note(vault, "a.md", "- [ ] Existing task\n")
    rebuild_index(db, vault)  # first pass: fresh db, user_version -> current

    db.execute("PRAGMA user_version = 0")
    db.execute("DELETE FROM tasks WHERE source_path = 'a.md'")
    db.commit()
    assert _task_rows(db, "a.md") == []

    rebuild_index(db, vault)

    assert [row["text"] for row in _task_rows(db, "a.md")] == ["Existing task"]
    assert db.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_BACKFILL_VERSION


def test_rebuild_index_skips_version_bump_when_backfill_has_a_failure(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A note that fails during the one-shot backfill pass must not be
    silently orphaned: its mtime never changes again on its own, so if
    the version were bumped anyway, the ordinary mtime-skip path would
    never retry it on any later rescan. Leaving the version un-bumped
    means the next rebuild_index call retries the whole backfill instead
    of permanently losing that one note's tasks."""
    write_note(vault, "a.md", "- [ ] Task A\n")
    write_note(vault, "b.md", "- [ ] Task B\n")
    rebuild_index(db, vault)  # user_version -> current, both notes indexed

    db.execute("PRAGMA user_version = 0")
    db.execute("DELETE FROM tasks")
    db.commit()

    original_upsert = indexer.upsert_note

    def failing_upsert(conn: sqlite3.Connection, vault_root: Path, path: str) -> None:
        if path == "b.md":
            raise RuntimeError("simulated transient failure")
        original_upsert(conn, vault_root, path)

    monkeypatch.setattr(indexer, "upsert_note", failing_upsert)

    rebuild_index(db, vault)

    # a.md's backfill succeeded; the version was NOT bumped because b.md
    # failed -- otherwise b.md's tasks would be lost forever.
    assert [row["text"] for row in _task_rows(db, "a.md")] == ["Task A"]
    assert _task_rows(db, "b.md") == []
    assert db.execute("PRAGMA user_version").fetchone()[0] == 0

    monkeypatch.setattr(indexer, "upsert_note", original_upsert)
    rebuild_index(db, vault)  # retried on the next pass, now succeeds

    assert [row["text"] for row in _task_rows(db, "b.md")] == ["Task B"]
    assert db.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_BACKFILL_VERSION


def test_rebuild_index_resumes_mtime_skip_after_schema_backfill(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backfill in the test above must be one-time, not perpetual --
    once user_version is current, an unchanged note's mtime should skip
    upsert_note again, same as before the tasks feature existed."""
    write_note(vault, "a.md", "content")
    rebuild_index(db, vault)  # user_version -> current

    calls: list[str] = []
    original_upsert = indexer.upsert_note

    def spy_upsert(conn: sqlite3.Connection, vault_root: Path, path: str) -> None:
        calls.append(path)
        original_upsert(conn, vault_root, path)

    monkeypatch.setattr(indexer, "upsert_note", spy_upsert)

    rebuild_index(db, vault)

    assert not calls


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


def _index(vault: Path, db: sqlite3.Connection, notes: dict[str, str]) -> None:
    for path, content in notes.items():
        write_note(vault, path, content)
        upsert_note(db, vault, path)


def _edges(db: sqlite3.Connection) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in get_graph(db).edges}


def test_wikilink_becomes_a_graph_edge_and_a_backlink(
    vault: Path, db: sqlite3.Connection
) -> None:
    _index(vault, db, {"a.md": "See [[B|the B note]].", "folder/B.md": "content"})

    assert _edges(db) == {("a.md", "folder/B.md")}
    assert [note.path for note in get_backlinks(db, "folder/B.md")] == ["a.md"]


def test_same_named_notes_each_get_only_their_own_wikilink_backlinks(
    vault: Path, db: sqlite3.Connection
) -> None:
    _index(
        vault,
        db,
        {
            "x/B.md": "x",
            "y/B.md": "y",
            "x/linker.md": "[[B]]",
            "y/linker.md": "[[B]]",
            "z/qualified.md": "[[y/B]]",
        },
    )

    assert [note.path for note in get_backlinks(db, "x/B.md")] == ["x/linker.md"]
    assert [note.path for note in get_backlinks(db, "y/B.md")] == [
        "y/linker.md",
        "z/qualified.md",
    ]


def test_markdown_link_and_wikilink_to_one_note_are_one_edge(
    vault: Path, db: sqlite3.Connection
) -> None:
    _index(vault, db, {"a.md": "[B](b.md) and [[b]] and [[B#Part]]", "b.md": "x"})

    assert get_graph(db).edges == [GraphEdge(source="a.md", target="b.md")]
    assert [note.path for note in get_backlinks(db, "b.md")] == ["a.md"]


def test_unresolved_wikilink_is_a_ghost_until_the_note_exists(
    vault: Path, db: sqlite3.Connection
) -> None:
    _index(vault, db, {"a.md": "[[Missing]] and ![[photo.png]] and [[#Top]]"})

    graph = get_graph(db)
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("a.md", "Missing.md")
    }
    ghost = next(node for node in graph.nodes if node.path == "Missing.md")
    assert ghost.exists is False

    # Creating the note resolves the link without reindexing `a.md`.
    _index(vault, db, {"notes/missing.md": "now here"})

    assert _edges(db) == {("a.md", "notes/missing.md")}
    assert [note.path for note in get_backlinks(db, "notes/missing.md")] == ["a.md"]


def test_removing_a_note_removes_its_wikilinks(
    vault: Path, db: sqlite3.Connection
) -> None:
    _index(vault, db, {"a.md": "[[B]]", "B.md": "x"})

    remove_note(db, "a.md")

    assert db.execute("SELECT COUNT(*) FROM wikilinks").fetchone()[0] == 0
    assert get_backlinks(db, "B.md") == []


def test_rebuild_index_backfills_wikilinks_from_an_older_index(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "[[B]]")
    write_note(vault, "B.md", "x")
    rebuild_index(db, vault)
    # An index built before wikilinks existed: no rows, older version.
    db.execute("DELETE FROM wikilinks")
    db.execute("PRAGMA user_version = 1")

    rebuild_index(db, vault)

    assert _edges(db) == {("a.md", "B.md")}
    assert db.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_BACKFILL_VERSION


def test_upsert_note_stores_task_lines_counted_from_the_top_of_the_file(
    vault: Path, db: sqlite3.Connection
) -> None:
    # Written as is: write_note would rewrite the frontmatter.
    (vault / "a.md").write_text(
        "---\ntitle: A\ntags: []\n---\n\n# Today\n- [ ] Water\n", encoding="utf-8"
    )

    upsert_note(db, vault, "a.md")

    assert [(row["line"], row["text"]) for row in _task_rows(db, "a.md")] == [
        (7, "Water")
    ]


def test_rebuild_index_reindexes_every_note_from_a_version_2_index(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A version-2 index counted task lines from the note body, after the
    frontmatter. Every note goes through upsert_note once more so its task
    rows carry file lines, even though no file changed."""
    (vault / "a.md").write_text("---\ntitle: A\n---\n- [ ] Water\n", encoding="utf-8")
    (vault / "b.md").write_text("No tasks.\n", encoding="utf-8")
    rebuild_index(db, vault)
    db.execute("UPDATE tasks SET line = 1 WHERE source_path = 'a.md'")
    db.execute("PRAGMA user_version = 2")
    db.commit()

    calls: list[str] = []
    original_upsert = indexer.upsert_note

    def spy_upsert(conn: sqlite3.Connection, vault_root: Path, path: str) -> None:
        calls.append(path)
        original_upsert(conn, vault_root, path)

    monkeypatch.setattr(indexer, "upsert_note", spy_upsert)

    rebuild_index(db, vault)

    assert sorted(calls) == ["a.md", "b.md"]
    assert [row["line"] for row in _task_rows(db, "a.md")] == [4]
    assert db.execute("PRAGMA user_version").fetchone()[0] == 3


def _index_row_from_before_hidden_folders_were_skipped(
    db: sqlite3.Connection, path: str
) -> None:
    with db:
        db.execute(
            "INSERT INTO notes (path, title, content_hash, mtime) "
            "VALUES (?, 'Old', '', 0)",
            (path,),
        )
        db.execute(
            "INSERT INTO notes_fts (path, title, body) VALUES (?, 'Old', 'stale')",
            (path,),
        )


def test_rebuild_index_drops_a_previously_indexed_hidden_note(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "content")
    write_note(vault, ".trash/x.md", "stale")
    _index_row_from_before_hidden_folders_were_skipped(db, ".trash/x.md")

    rebuild_index(db, vault)

    assert [note.path for note in list_notes(db)] == ["a.md"]
    assert search_notes(db, "stale") == []


def test_upsert_note_on_a_hidden_path_removes_it_from_the_index(
    vault: Path, db: sqlite3.Connection
) -> None:
    # The write paths (save, move, MCP) upsert directly, never through a
    # vault scan, so a note saved or moved into .obsidian/ or .trash/ must
    # be dropped here.
    write_note(vault, ".obsidian/x.md", "- [ ] hidden task")
    _index_row_from_before_hidden_folders_were_skipped(db, ".obsidian/x.md")

    upsert_note(db, vault, ".obsidian/x.md")

    assert list_notes(db) == []
    assert search_notes(db, "stale") == []
    assert list_open_tasks(db) == []


def _symlinks_out_of_the_vault(vault: Path, tmp_path: Path) -> list[str]:
    """`escape.md` points at a non-note secret outside the vault (think
    /proc/self/environ), `sibling.md` at a note in a folder whose name
    starts with the vault's. Returns their vault-relative paths."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.env").write_text(
        "SECRETTOKEN\n- [ ] leaked task\n", encoding="utf-8"
    )
    sibling = tmp_path / "vault-sibling"
    sibling.mkdir()
    (sibling / "other.md").write_text(
        "SIBLINGTOKEN\n- [ ] sibling task\n", encoding="utf-8"
    )
    (vault / "escape.md").symlink_to(outside / "secret.env")
    (vault / "sibling.md").symlink_to(sibling / "other.md")
    return ["escape.md", "sibling.md"]


def _assert_nothing_from_outside_is_indexed(db: sqlite3.Connection) -> None:
    assert search_notes(db, "SECRETTOKEN") == []
    assert search_notes(db, "SIBLINGTOKEN") == []
    assert {task.text for task in list_open_tasks(db)} <= {"real task"}


def test_rebuild_index_skips_symlinks_out_of_the_vault(
    vault: Path, db: sqlite3.Connection, tmp_path: Path
) -> None:
    _symlinks_out_of_the_vault(vault, tmp_path)
    write_note(vault, "real.md", "- [ ] real task")
    (vault / "alias.md").symlink_to(vault / "real.md")

    rebuild_index(db, vault)

    assert [note.path for note in list_notes(db)] == ["alias.md", "real.md"]
    _assert_nothing_from_outside_is_indexed(db)
    assert {task.path for task in list_open_tasks(db)} == {"alias.md", "real.md"}


def test_upsert_note_refuses_symlinks_out_of_the_vault(
    vault: Path, db: sqlite3.Connection, tmp_path: Path
) -> None:
    for path in _symlinks_out_of_the_vault(vault, tmp_path):
        with pytest.raises(InvalidNotePathError):
            upsert_note(db, vault, path)

    assert list_notes(db) == []
    _assert_nothing_from_outside_is_indexed(db)


def test_watch_batch_never_reads_symlinks_out_of_the_vault(
    vault: Path, db: sqlite3.Connection, tmp_path: Path
) -> None:
    paths = _symlinks_out_of_the_vault(vault, tmp_path)
    write_note(vault, "real.md", "- [ ] real task")
    # A pending deletion makes the batch hash every new arrival for
    # rename pairing -- that read must not follow the links either.
    pending_renames = PendingRenameCache(window_seconds=30)
    pending_renames.add("gone.md", "0" * 64, time.monotonic())

    apply_watch_batch(db, vault, {*paths, "real.md"}, pending_renames)

    assert [note.path for note in list_notes(db)] == ["real.md"]
    _assert_nothing_from_outside_is_indexed(db)
    hashes = indexer._hash_new_arrivals(  # pylint: disable=protected-access
        vault, {*paths, "real.md"}
    )
    assert set(hashes) == {"real.md"}
