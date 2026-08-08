from __future__ import annotations

from pathlib import Path

import pytest

from cerebrum.attachments.service import attachment_dir_for_note
from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteAlreadyExistsError,
    NoteNotFoundError,
    delete_note,
    iter_note_paths,
    move_note,
    read_note,
    retarget_note_links,
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


def test_move_note_updates_title_alongside_path(vault: Path) -> None:
    write_note(vault, "a.md", "---\ntitle: Old Title\n---\nBody.\n")

    moved, _ = move_note(vault, "a.md", "folder/a.md", title="New Title")

    assert moved.title == "New Title"
    assert read_note(vault, "folder/a.md").title == "New Title"


def test_move_note_can_update_title_only_without_relocating(vault: Path) -> None:
    write_note(vault, "a.md", "---\ntitle: Old Title\n---\nBody.\n")

    moved, retargeted = move_note(vault, "a.md", "a.md", title="New Title")

    assert moved.path == "a.md"
    assert moved.title == "New Title"
    assert not retargeted
    assert read_note(vault, "a.md").title == "New Title"


def test_move_note_title_only_does_not_raise_already_exists(vault: Path) -> None:
    write_note(vault, "a.md", "content")

    # Same path is not a collision when nothing is relocating.
    move_note(vault, "a.md", "a.md", title="Renamed")


def test_move_note_relocates_attachment_dir_when_stem_unchanged(vault: Path) -> None:
    write_note(vault, "a.md", "![](a.attachments/abc123.png)")
    attachment_dir = attachment_dir_for_note(vault, "a.md")
    attachment_dir.mkdir(parents=True)
    (attachment_dir / "abc123.png").write_bytes(b"fake-png-bytes")

    moved, _ = move_note(vault, "a.md", "folder/a.md")

    # Same stem, only the directory changed -- the attachment dir moves
    # alongside it under the same name, and the note's embedded relative
    # reference (relative to the note's own folder) is still correct
    # without any rewrite.
    old_dir = attachment_dir_for_note(vault, "a.md")
    new_dir = attachment_dir_for_note(vault, "folder/a.md")
    assert not old_dir.exists()
    assert new_dir.is_dir()
    assert (new_dir / "abc123.png").read_bytes() == b"fake-png-bytes"
    assert "![](a.attachments/abc123.png)" in moved.content


def test_move_note_renaming_stem_renames_attachment_dir_and_rewrites_body(
    vault: Path,
) -> None:
    write_note(vault, "idea.md", "![](idea.attachments/abc123.png)")
    attachment_dir = attachment_dir_for_note(vault, "idea.md")
    attachment_dir.mkdir(parents=True)
    (attachment_dir / "abc123.png").write_bytes(b"fake-png-bytes")

    moved, _ = move_note(vault, "idea.md", "better-idea.md")

    old_dir = attachment_dir_for_note(vault, "idea.md")
    new_dir = attachment_dir_for_note(vault, "better-idea.md")
    assert not old_dir.exists()
    assert new_dir.is_dir()
    assert (new_dir / "abc123.png").read_bytes() == b"fake-png-bytes"
    assert "better-idea.attachments/abc123.png" in moved.content
    assert "](idea.attachments/abc123.png)" not in moved.content
    # Persisted to disk too, not just the returned in-memory note.
    assert (
        "better-idea.attachments/abc123.png"
        in read_note(vault, "better-idea.md").content
    )


def test_move_note_renaming_stem_does_not_corrupt_unrelated_suffix_match(
    vault: Path,
) -> None:
    """Regression: a blind (non-anchored) substring replace of
    `<old-stem>.attachments/` would also mangle an unrelated reference
    whose own folder name merely *ends with* the old stem -- e.g. renaming
    idea.md must not touch a cross-note reference to
    `other-idea.attachments/...`, since `"idea.attachments/"` is a
    substring of `"other-idea.attachments/"`."""
    write_note(
        vault,
        "idea.md",
        "![](idea.attachments/abc123.png)\nSee also ![](other-idea.attachments/x.png).",
    )
    attachment_dir = attachment_dir_for_note(vault, "idea.md")
    attachment_dir.mkdir(parents=True)
    (attachment_dir / "abc123.png").write_bytes(b"fake-png-bytes")

    moved, _ = move_note(vault, "idea.md", "better-idea.md")

    # The note's own reference is rewritten...
    assert "better-idea.attachments/abc123.png" in moved.content
    # ...but the unrelated cross-note reference is untouched.
    assert "other-idea.attachments/x.png" in moved.content
    assert "other-better-idea.attachments" not in moved.content


def test_move_note_without_attachment_dir_does_not_raise_or_create_one(
    vault: Path,
) -> None:
    write_note(vault, "a.md", "content")

    move_note(vault, "a.md", "folder/a.md")

    assert not attachment_dir_for_note(vault, "a.md").exists()
    assert not attachment_dir_for_note(vault, "folder/a.md").exists()


def test_retarget_note_links_rebases_its_own_relative_links(vault: Path) -> None:
    # "folder/a.md" links to "target.md", meaning "folder/target.md".
    write_note(vault, "folder/a.md", "See [T](target.md).")
    write_note(vault, "folder/target.md", "content")

    # Simulate the file already having been moved externally (e.g. `mv`)
    # before retarget_note_links is called.
    (vault / "folder" / "a.md").rename(vault / "a.md")

    moved, _ = retarget_note_links(vault, "folder/a.md", "a.md")

    # Now at the root, the same absolute target needs the full path.
    assert "[T](folder/target.md)" in moved.content
    assert "[T](folder/target.md)" in read_note(vault, "a.md").content


def test_retarget_note_links_retargets_other_notes_incoming_links(
    vault: Path,
) -> None:
    write_note(vault, "linker.md", "See [B](b.md) for details.")
    write_note(vault, "b.md", "content")
    (vault / "folder").mkdir()
    (vault / "b.md").rename(vault / "folder" / "b.md")

    _, retargeted = retarget_note_links(vault, "b.md", "folder/b.md")

    assert retargeted == ["linker.md"]
    linker = read_note(vault, "linker.md")
    assert "[B](folder/b.md)" in linker.content
    assert "for details" in linker.content


def test_retarget_note_links_preserves_link_fragment(vault: Path) -> None:
    write_note(vault, "linker.md", "See [B](b.md#section).")
    write_note(vault, "b.md", "content")
    (vault / "folder").mkdir()
    (vault / "b.md").rename(vault / "folder" / "b.md")

    retarget_note_links(vault, "b.md", "folder/b.md")

    linker = read_note(vault, "linker.md")
    assert "[B](folder/b.md#section)" in linker.content


def test_retarget_note_links_same_directory_needs_no_self_rebase(
    vault: Path,
) -> None:
    write_note(vault, "old-name.md", "See [T](target.md).")
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [B](old-name.md).")

    (vault / "old-name.md").rename(vault / "new-name.md")

    moved, retargeted = retarget_note_links(vault, "old-name.md", "new-name.md")

    # Same directory -- the note's own relative link needed no rewrite.
    assert "[T](target.md)" in moved.content
    # But other notes still get retargeted.
    assert retargeted == ["linker.md"]
    assert "[B](new-name.md)" in read_note(vault, "linker.md").content


def test_retarget_note_links_does_not_touch_unrelated_links(vault: Path) -> None:
    write_note(vault, "linker.md", "See [C](c.md).")
    write_note(vault, "b.md", "content")
    write_note(vault, "c.md", "content")
    (vault / "folder").mkdir()
    (vault / "b.md").rename(vault / "folder" / "b.md")

    _, retargeted = retarget_note_links(vault, "b.md", "folder/b.md")

    assert not retargeted
    assert "[C](c.md)" in read_note(vault, "linker.md").content


def test_retarget_note_links_missing_destination_raises(vault: Path) -> None:
    with pytest.raises(NoteNotFoundError):
        retarget_note_links(vault, "old.md", "new.md")


def test_retarget_note_links_skips_unreadable_other_note(vault: Path) -> None:
    write_note(vault, "b.md", "content")
    (vault / "bad.md").write_bytes(b"\xff\xfe not valid utf-8")
    (vault / "folder").mkdir()
    (vault / "b.md").rename(vault / "folder" / "b.md")

    # An unreadable sibling note must not abort the whole operation.
    _, retargeted = retarget_note_links(vault, "b.md", "folder/b.md")

    assert not retargeted


def test_retarget_note_links_write_failure_keeps_already_written_linkers(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a write failure partway through retargeting must not
    discard the `retargeted` entries already earned by linkers processed
    before it -- the caller (the watcher's rename-pairing path) relies on
    that list to know exactly which notes' files actually changed on
    disk, so it can keep their index rows in sync."""
    write_note(vault, "target.md", "content")
    write_note(vault, "linker-a.md", "See [A](target.md).")
    write_note(vault, "linker-b.md", "See [B](target.md).")
    (vault / "target.md").rename(vault / "renamed.md")

    real_write_text = Path.write_text

    def flaky_write_text(self: Path, *args: object, **kwargs: object) -> int:
        if self.name == "linker-b.md":
            raise OSError("simulated write failure")
        return real_write_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    _, retargeted = retarget_note_links(vault, "target.md", "renamed.md")

    # linker-a.md's write succeeded and is reported; linker-b.md's write
    # failed and is skipped (logged), but does not abort the loop or
    # discard linker-a.md's already-earned entry.
    assert retargeted == ["linker-a.md"]
    assert "[A](renamed.md)" in read_note(vault, "linker-a.md").content
    assert "[B](target.md)" in read_note(vault, "linker-b.md").content


def test_retarget_note_links_leaves_attachment_dir_untouched(vault: Path) -> None:
    write_note(vault, "idea.md", "![](idea.attachments/abc123.png)")
    attachment_dir = attachment_dir_for_note(vault, "idea.md")
    attachment_dir.mkdir(parents=True)
    (attachment_dir / "abc123.png").write_bytes(b"fake-png-bytes")

    (vault / "idea.md").rename(vault / "better-idea.md")

    moved, _ = retarget_note_links(vault, "idea.md", "better-idea.md")

    # R6: attachment folders/references are explicitly out of scope here
    # -- unlike move_note, the folder stays put under its old name and
    # the note's embedded reference is left as-is.
    assert attachment_dir.is_dir()
    assert (attachment_dir / "abc123.png").read_bytes() == b"fake-png-bytes"
    assert not attachment_dir_for_note(vault, "better-idea.md").exists()
    assert "![](idea.attachments/abc123.png)" in moved.content


def test_delete_note_removes_attachment_dir(vault: Path) -> None:
    write_note(vault, "a.md", "content")
    attachment_dir = attachment_dir_for_note(vault, "a.md")
    attachment_dir.mkdir(parents=True)
    (attachment_dir / "abc123.png").write_bytes(b"fake-png-bytes")

    delete_note(vault, "a.md")

    assert not attachment_dir.exists()


def test_delete_note_without_attachment_dir_does_not_raise(vault: Path) -> None:
    write_note(vault, "a.md", "content")

    delete_note(vault, "a.md")

    assert not attachment_dir_for_note(vault, "a.md").exists()
