from __future__ import annotations

from pathlib import Path

import pytest

from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteAlreadyExistsError,
    NoteNotFoundError,
    delete_note,
    iter_note_paths,
    move_note,
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


def test_move_note_relocates_file_and_preserves_content(vault: Path) -> None:
    written = write_note(vault, "a.md", "---\ntitle: A\n---\nBody.\n")

    moved, retargeted = move_note(vault, "a.md", "folder/b.md")

    assert moved.path == "folder/b.md"
    assert moved.content == written.content
    assert moved.created == written.created
    assert not retargeted
    with pytest.raises(NoteNotFoundError):
        read_note(vault, "a.md")
    assert read_note(vault, "folder/b.md").content == written.content


def test_move_note_creates_destination_parent_directories(vault: Path) -> None:
    write_note(vault, "a.md", "content")

    move_note(vault, "a.md", "deep/nested/b.md")

    assert (vault / "deep" / "nested" / "b.md").is_file()


def test_move_note_missing_source_raises(vault: Path) -> None:
    with pytest.raises(NoteNotFoundError):
        move_note(vault, "missing.md", "target.md")


def test_move_note_existing_destination_raises(vault: Path) -> None:
    write_note(vault, "a.md", "content")
    write_note(vault, "b.md", "content")

    with pytest.raises(NoteAlreadyExistsError):
        move_note(vault, "a.md", "b.md")

    # The source must be untouched after a rejected move.
    assert read_note(vault, "a.md").content is not None


def test_move_note_rejects_invalid_destination(vault: Path) -> None:
    write_note(vault, "a.md", "content")

    with pytest.raises(InvalidNotePathError):
        move_note(vault, "a.md", "not-markdown.txt")


def test_move_note_rebases_its_own_relative_links(vault: Path) -> None:
    # "folder/a.md" links to "target.md", meaning "folder/target.md".
    write_note(vault, "folder/a.md", "See [T](target.md).")
    write_note(vault, "folder/target.md", "content")

    moved, _ = move_note(vault, "folder/a.md", "a.md")

    # Now at the root, the same absolute target needs the full path.
    assert "[T](folder/target.md)" in moved.content


def test_move_note_retargets_other_notes_incoming_links(vault: Path) -> None:
    write_note(vault, "linker.md", "See [B](b.md) for details.")
    write_note(vault, "b.md", "content")

    _, retargeted = move_note(vault, "b.md", "folder/b.md")

    assert retargeted == ["linker.md"]
    linker = read_note(vault, "linker.md")
    assert "[B](folder/b.md)" in linker.content
    assert "for details" in linker.content


def test_move_note_preserves_link_fragment(vault: Path) -> None:
    write_note(vault, "linker.md", "See [B](b.md#section).")
    write_note(vault, "b.md", "content")

    move_note(vault, "b.md", "folder/b.md")

    linker = read_note(vault, "linker.md")
    assert "[B](folder/b.md#section)" in linker.content


def test_move_note_does_not_touch_unrelated_links(vault: Path) -> None:
    write_note(vault, "linker.md", "See [C](c.md).")
    write_note(vault, "b.md", "content")
    write_note(vault, "c.md", "content")

    _, retargeted = move_note(vault, "b.md", "folder/b.md")

    assert not retargeted
    assert "[C](c.md)" in read_note(vault, "linker.md").content
