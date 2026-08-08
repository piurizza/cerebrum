from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest

import cerebrum.notes.service as notes_service
from cerebrum.attachments.service import attachment_dir_for_note
from cerebrum.notes.file_lock import file_lock
from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteAlreadyExistsError,
    NoteNotFoundError,
    delete_note,
    iter_note_paths,
    move_note,
    read_note,
    resolve_note_path,
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


# --- U2: per-path locking on write_note/delete_note/move_note ---------


def test_write_note_blocks_until_other_lock_holder_releases(vault: Path) -> None:
    """A `write_note` call for a path already locked by someone else
    waits for that lock to be released before doing its own read-modify-
    write -- proven via a strict enter/exit/write-done event ordering, not
    just a "did it eventually finish" check."""
    file_path = resolve_note_path(vault, "note.md")
    events: list[str] = []
    events_lock = threading.Lock()
    holder_entered = threading.Event()

    def hold_lock() -> None:
        with file_lock(file_path):
            with events_lock:
                events.append("holder-enter")
            holder_entered.set()
            time.sleep(0.1)
            with events_lock:
                events.append("holder-exit")

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert holder_entered.wait(timeout=5)

    def do_write() -> None:
        write_note(vault, "note.md", "content")
        with events_lock:
            events.append("write-done")

    writer = threading.Thread(target=do_write)
    writer.start()

    holder.join(timeout=5)
    writer.join(timeout=5)
    assert not holder.is_alive()
    assert not writer.is_alive()

    assert events == ["holder-enter", "holder-exit", "write-done"]
    assert file_path.is_file()


def test_delete_note_blocks_until_in_progress_write_finishes(vault: Path) -> None:
    """`delete_note` waits for a concurrent holder of the same path's
    lock (standing in for an in-progress write) before checking
    existence and unlinking."""
    write_note(vault, "note.md", "content")
    file_path = resolve_note_path(vault, "note.md")
    events: list[str] = []
    events_lock = threading.Lock()
    holder_entered = threading.Event()

    def hold_lock() -> None:
        with file_lock(file_path):
            with events_lock:
                events.append("writer-enter")
            holder_entered.set()
            time.sleep(0.1)
            with events_lock:
                events.append("writer-exit")

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert holder_entered.wait(timeout=5)

    def do_delete() -> None:
        delete_note(vault, "note.md")
        with events_lock:
            events.append("delete-done")

    deleter = threading.Thread(target=do_delete)
    deleter.start()

    holder.join(timeout=5)
    deleter.join(timeout=5)
    assert not holder.is_alive()
    assert not deleter.is_alive()

    assert events == ["writer-enter", "writer-exit", "delete-done"]
    assert not file_path.exists()


def test_move_note_disjoint_moves_do_not_block_each_other(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two `move_note` calls whose source/destination paths are entirely
    disjoint run concurrently -- proven with a barrier both must reach
    together from inside their own locked critical section. If disjoint
    moves wrongly serialized (e.g. a single global lock), the second
    thread would never reach the barrier while the first is still inside
    its critical section, and the barrier would time out for both."""
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")

    barrier = threading.Barrier(2, timeout=5)
    original_rebase_links = notes_service.rebase_links

    def barrier_rebase_links(body: str, old_path: str, new_path: str) -> str:
        barrier.wait()
        return original_rebase_links(body, old_path, new_path)

    monkeypatch.setattr(notes_service, "rebase_links", barrier_rebase_links)

    errors: dict[str, BaseException] = {}

    def do_move(name: str, old: str, new: str) -> None:
        try:
            move_note(vault, old, new)
        except BaseException as exc:  # noqa: BLE001 -- capture across threads
            errors[name] = exc

    t1 = threading.Thread(target=do_move, args=("a", "a.md", "moved-a.md"))
    t2 = threading.Thread(target=do_move, args=("b", "b.md", "moved-b.md"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert not errors
    assert (vault / "moved-a.md").is_file()
    assert (vault / "moved-b.md").is_file()


def test_write_note_must_not_exist_succeeds_when_path_is_free(vault: Path) -> None:
    note = write_note(vault, "note.md", "content", must_not_exist=True)

    assert note.path == "note.md"
    assert (vault / "note.md").is_file()


def test_write_note_must_not_exist_raises_and_preserves_existing_content(
    vault: Path,
) -> None:
    write_note(vault, "note.md", "---\ntitle: Original\n---\nOriginal body.\n")
    original_content = (vault / "note.md").read_text(encoding="utf-8")

    with pytest.raises(NoteAlreadyExistsError):
        write_note(
            vault,
            "note.md",
            "---\ntitle: New\n---\nNew body.\n",
            must_not_exist=True,
        )

    assert (vault / "note.md").read_text(encoding="utf-8") == original_content


def test_write_note_must_exist_succeeds_when_path_is_present(vault: Path) -> None:
    write_note(vault, "note.md", "---\ntitle: A\n---\nBody.\n")

    updated = write_note(vault, "note.md", "new content", must_exist=True)

    assert "new content" in updated.content


def test_write_note_must_exist_raises_and_does_not_create_file(vault: Path) -> None:
    with pytest.raises(NoteNotFoundError):
        write_note(vault, "missing.md", "content", must_exist=True)

    assert not (vault / "missing.md").exists()


def test_write_note_default_parameters_are_unaffected(vault: Path) -> None:
    """Neither existing caller passes `must_not_exist`/`must_exist`; both
    default to False, so pre-existing overwrite-in-place behavior is
    unchanged."""
    write_note(vault, "note.md", "first")
    write_note(vault, "note.md", "second")

    assert "second" in read_note(vault, "note.md").content


def test_move_note_swap_race_both_raise_already_exists_without_hanging(
    vault: Path,
) -> None:
    """Two threads racing `move_note("a.md", "b.md")` and
    `move_note("b.md", "a.md")` when both files already exist must both
    raise `NoteAlreadyExistsError` deterministically -- not hang. Before
    the fixed, sorted lock-acquisition order, one thread could lock
    `a.md` while wanting `b.md` at the same moment the other locks
    `b.md` while wanting `a.md`, a classic AB-BA deadlock. Bounded
    `join(timeout=...)` + `is_alive()` makes a regression fail loudly
    instead of hanging the suite."""
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")

    errors: dict[str, BaseException] = {}

    def do_move(name: str, old: str, new: str) -> None:
        try:
            move_note(vault, old, new)
        except BaseException as exc:  # noqa: BLE001 -- capture across threads
            errors[name] = exc

    t1 = threading.Thread(target=do_move, args=("a-to-b", "a.md", "b.md"))
    t2 = threading.Thread(target=do_move, args=("b-to-a", "b.md", "a.md"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert set(errors) == {"a-to-b", "b-to-a"}
    assert isinstance(errors["a-to-b"], NoteAlreadyExistsError)
    assert isinstance(errors["b-to-a"], NoteAlreadyExistsError)
    # Neither file was touched by the rejected swap.
    assert read_note(vault, "a.md").content is not None
    assert read_note(vault, "b.md").content is not None


def test_move_note_relocation_lock_released_before_retarget_call(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defining correctness property of this unit: `move_note` must
    release its source/destination locks BEFORE `_retarget_other_notes`
    runs, or two concurrent cross-linked moves can AB-BA deadlock -- move
    `a.md`->`c.md` needing to retarget links that pointed at `b.md`,
    concurrently with move `b.md`->`d.md` needing to retarget links that
    pointed at `a.md`. `_retarget_other_notes` doesn't lock anything of
    its own yet (a later unit adds that), so this test simulates what
    that later unit will do -- locking the "other" move's source path --
    to verify the release-before-retarget scoping holds up under it.
    A scratch script reproducing the naive (pre-fix) scoping -- holding
    source+destination across an equivalent simulated retarget call --
    was run separately and did deadlock (verified via a bounded thread
    join); this test proves the implemented scoping does not."""
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")

    a_path = resolve_note_path(vault, "a.md")
    b_path = resolve_note_path(vault, "b.md")
    both_mid_retarget = threading.Barrier(2, timeout=5)
    real_retarget_other_notes = (
        notes_service._retarget_other_notes  # pylint: disable=protected-access
    )  # noqa: SLF001

    def simulated_retarget(
        vault_root: Path, old_target: str, new_target: str
    ) -> list[str]:
        other = b_path if old_target == "a.md" else a_path
        # Both moves must be here together -- if either were still
        # holding its own source/destination lock, the other's attempt
        # below to lock that same path would block before both could
        # reach this barrier, timing it out for both instead of hanging
        # quietly, so a regression fails fast rather than hanging.
        both_mid_retarget.wait()
        with file_lock(other):
            pass
        return real_retarget_other_notes(vault_root, old_target, new_target)

    monkeypatch.setattr(notes_service, "_retarget_other_notes", simulated_retarget)

    results: dict[str, BaseException | None] = {}

    def do_move(name: str, old: str, new: str) -> None:
        try:
            move_note(vault, old, new)
            results[name] = None
        except BaseException as exc:  # noqa: BLE001 -- capture across threads
            results[name] = exc

    t1 = threading.Thread(target=do_move, args=("a", "a.md", "c.md"))
    t2 = threading.Thread(target=do_move, args=("b", "b.md", "d.md"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert results.get("a") is None
    assert results.get("b") is None
    assert (vault / "c.md").is_file()
    assert (vault / "d.md").is_file()


def test_write_note_and_move_note_destination_race_never_leaves_mixed_content(
    vault: Path,
) -> None:
    """`write_note` targeting a path, and `move_note`'s relocation branch
    making that SAME path its destination, run concurrently many times.
    `target.md`'s per-path lock serializes the two, so exactly one clean
    outcome is possible on every interleaving: `write_note` never checks
    existence (this test doesn't pass `must_not_exist`), so it always
    ends up as the operation that determines the final content --
    either by writing after the move landed (overwriting it) or by
    writing first and causing the move to see an occupied destination
    and raise instead of writing. Either way `target.md` must end up as
    exactly the direct write's clean, parseable content -- never
    truncated or concatenated with the moved note's bytes."""
    for i in range(20):
        source_content = f"---\ntitle: Source {i}\n---\nSource body {i}.\n"
        write_note(vault, "source.md", source_content)
        (vault / "target.md").unlink(missing_ok=True)

        write_started = threading.Event()

        def do_write(idx: int, event: threading.Event = write_started) -> None:
            event.set()
            write_note(
                vault, "target.md", f"---\ntitle: Direct {idx}\n---\nDirect body.\n"
            )

        def do_move(event: threading.Event = write_started) -> None:
            event.wait(timeout=5)
            with contextlib.suppress(NoteAlreadyExistsError):
                move_note(vault, "source.md", "target.md")

        writer = threading.Thread(target=do_write, args=(i,))
        mover = threading.Thread(target=do_move)
        writer.start()
        mover.start()
        writer.join(timeout=5)
        mover.join(timeout=5)
        assert not writer.is_alive()
        assert not mover.is_alive()

        # Whichever order the two ran in, `target.md` must be a single,
        # cleanly parseable note with exactly the direct write's title
        # and body -- never a mix of both operations' bytes.
        note = read_note(vault, "target.md")
        assert note.title == f"Direct {i}"
        assert "Direct body." in note.content
        assert "Source" not in note.content


def test_move_note_relocation_does_not_block_unrelated_write_note(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`move_note`'s relocation branch, mid-flight, does not block a
    plain `write_note` targeting a third, unrelated path -- demonstrating
    that releasing source/destination before the retarget call (rather
    than, say, holding a broader lock for the whole function) doesn't
    accidentally serialize unrelated work either. Hooked via
    monkeypatching a call inside move_note's own locked critical section
    so the unrelated write is attempted while move_note provably still
    holds its locks."""
    write_note(vault, "a.md", "content a")
    write_note(vault, "unrelated.md", "original")

    move_mid_flight = threading.Event()
    release_move = threading.Event()
    original_rebase_links = notes_service.rebase_links

    def blocking_rebase_links(body: str, old_path: str, new_path: str) -> str:
        move_mid_flight.set()
        release_move.wait(timeout=5)
        return original_rebase_links(body, old_path, new_path)

    monkeypatch.setattr(notes_service, "rebase_links", blocking_rebase_links)

    mover = threading.Thread(target=move_note, args=(vault, "a.md", "b.md"))
    mover.start()
    assert move_mid_flight.wait(timeout=5)

    # move_note is now blocked mid-critical-section, still holding its
    # own locks on a.md/b.md. A write to a wholly unrelated path must
    # complete promptly rather than waiting on move_note.
    start = time.monotonic()
    write_note(vault, "unrelated.md", "updated while move is mid-flight")
    elapsed = time.monotonic() - start

    release_move.set()
    mover.join(timeout=5)
    assert not mover.is_alive()

    assert elapsed < 1.0
    updated_note = read_note(vault, "unrelated.md")
    assert "updated while move is mid-flight" in updated_note.content
