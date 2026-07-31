from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrum.graph.service import get_backlinks, get_graph
from cerebrum.index import indexer
from cerebrum.index.db import list_notes
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
