from __future__ import annotations

from pathlib import Path

import pytest

from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteNotFoundError,
    delete_note,
    iter_note_paths,
    read_note,
    write_note,
)


def test_write_then_read_note(vault: Path) -> None:
    write_note(vault, "note.md", "---\ntitle: Hello\n---\nBody.\n")

    note = read_note(vault, "note.md")

    assert note.title == "Hello"
    assert note.created is not None
    assert note.updated is not None
    assert "Body." in note.content


def test_write_note_creates_parent_directories(vault: Path) -> None:
    write_note(vault, "folder/nested/note.md", "content")

    assert (vault / "folder" / "nested" / "note.md").is_file()


def test_write_note_sets_created_once_and_updates_updated(vault: Path) -> None:
    first = write_note(vault, "note.md", "---\ntitle: A\n---\nBody")
    second = write_note(vault, "note.md", first.content.replace("Body", "Body v2"))

    assert second.created == first.created
    assert second.updated >= first.updated  # type: ignore[operator]


def test_read_note_missing_raises(vault: Path) -> None:
    with pytest.raises(NoteNotFoundError):
        read_note(vault, "missing.md")


def test_resolve_note_path_rejects_traversal(vault: Path) -> None:
    with pytest.raises(InvalidNotePathError):
        read_note(vault, "../outside.md")


def test_resolve_note_path_rejects_non_markdown(vault: Path) -> None:
    with pytest.raises(InvalidNotePathError):
        read_note(vault, "note.txt")


def test_delete_note_removes_file(vault: Path) -> None:
    write_note(vault, "note.md", "content")

    delete_note(vault, "note.md")

    with pytest.raises(NoteNotFoundError):
        read_note(vault, "note.md")


def test_delete_missing_note_raises(vault: Path) -> None:
    with pytest.raises(NoteNotFoundError):
        delete_note(vault, "missing.md")


def test_iter_note_paths_lists_only_markdown(vault: Path) -> None:
    write_note(vault, "a.md", "content")
    write_note(vault, "sub/b.md", "content")
    (vault / "not-a-note.txt").write_text("ignored")

    assert set(iter_note_paths(vault)) == {"a.md", "sub/b.md"}
