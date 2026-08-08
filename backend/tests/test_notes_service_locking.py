"""Concurrency/locking tests for notes/service.py's write_note, delete_note,
move_note, retarget_note_links, and _retarget_other_notes -- split out of
test_notes_service.py (which covers the same module's CRUD/move/retarget
behavior) once the combined file crossed 1000 lines. Both files share the
`vault` fixture from conftest.py."""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import cerebrum.notes.service as notes_service
from cerebrum.attachments.service import attachment_dir_for_note
from cerebrum.notes.file_lock import file_lock
from cerebrum.notes.service import (
    NoteAlreadyExistsError,
    NoteNotFoundError,
    delete_note,
    move_note,
    read_note,
    resolve_note_path,
    retarget_note_links,
    write_note,
)


def test_delete_note_attachment_cleanup_blocks_concurrent_move_onto_same_path(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`delete_note`'s attachment-dir cleanup runs INSIDE the same lock as
    the unlink, not after it -- otherwise a concurrent `move_note` onto
    the just-deleted path could relocate a different note's attachments
    there first, and the delete's now-late, unlocked cleanup would
    `shutil.rmtree` them out from under the just-moved-in note (silent
    attachment data loss). Proven here by pausing INSIDE
    `delete_attachment_dir` and confirming a concurrent `move_note`
    targeting the same path is still blocked (it can't have started
    relocating `b.md`'s attachments there yet) until the pause is
    released -- i.e. delete's lock covers the attachment cleanup too."""
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "content b")
    b_attachment_dir = attachment_dir_for_note(vault, "b.md")
    b_attachment_dir.mkdir(parents=True)
    (b_attachment_dir / "abc123.png").write_bytes(b"fake-png-bytes")

    events: list[str] = []
    events_lock = threading.Lock()
    cleanup_entered = threading.Event()
    release_cleanup = threading.Event()
    original_delete_attachment_dir = notes_service.delete_attachment_dir

    def paused_delete_attachment_dir(vault_root: Path, path: str) -> None:
        with events_lock:
            events.append("cleanup-enter")
        cleanup_entered.set()
        release_cleanup.wait(timeout=5)
        original_delete_attachment_dir(vault_root, path)
        with events_lock:
            events.append("cleanup-exit")

    monkeypatch.setattr(
        notes_service, "delete_attachment_dir", paused_delete_attachment_dir
    )

    def do_delete() -> None:
        delete_note(vault, "a.md")

    deleter = threading.Thread(target=do_delete)
    deleter.start()
    assert cleanup_entered.wait(timeout=5)

    def do_move() -> None:
        move_note(vault, "b.md", "a.md")
        with events_lock:
            events.append("move-done")

    mover = threading.Thread(target=do_move)
    mover.start()
    # The mover must still be blocked on a.md's lock -- delete_note is
    # paused mid-cleanup but still holding it. A short, generous wait
    # keeps this deterministic without depending on exact scheduling.
    time.sleep(0.1)
    assert mover.is_alive()

    release_cleanup.set()
    deleter.join(timeout=5)
    mover.join(timeout=5)
    assert not deleter.is_alive()
    assert not mover.is_alive()

    assert events == ["cleanup-enter", "cleanup-exit", "move-done"]
    # b.md's attachments landed at a.attachments/ only after delete's
    # cleanup (of the OLD a.attachments/, which never existed here) fully
    # finished -- so they survive intact, not clobbered by a late rmtree.
    new_attachment_dir = attachment_dir_for_note(vault, "a.md")
    assert (new_attachment_dir / "abc123.png").read_bytes() == b"fake-png-bytes"


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
    pointed at `a.md`. `_retarget_other_notes` locks its own paths one at
    a time as it discovers them; this test simulates the "other" move
    already holding its source path's lock when `_retarget_other_notes`
    tries to acquire it, to verify the release-before-retarget scoping
    holds up under that contention.
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


_retarget_other_notes = (
    notes_service._retarget_other_notes  # pylint: disable=protected-access
)  # noqa: SLF001


def _pause_retarget_links(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[threading.Event, threading.Event]:
    """Patch `retarget_links` (called inside `_retarget_other_notes`'s
    locked critical section, after its read and before its write) so a
    caller can pause a retarget mid-flight, controlling the interleaving
    instead of relying on timing alone."""
    entered = threading.Event()
    release = threading.Event()
    original_retarget_links = notes_service.retarget_links

    def paused_retarget_links(
        body: str, note_path: str, old_target: str, new_target: str
    ) -> str:
        entered.set()
        release.wait(timeout=5)
        return original_retarget_links(body, note_path, old_target, new_target)

    monkeypatch.setattr(notes_service, "retarget_links", paused_retarget_links)
    return entered, release


def _run_against_paused_retarget(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    old_target: str,
    new_target: str,
    second_op: Callable[[], None],
) -> None:
    """Pause `_retarget_other_notes(vault, old_target, new_target)`'s
    critical section mid-flight, run `second_op` concurrently once the
    pause is confirmed entered, then release and join both threads with
    a bounded timeout -- the shared shape behind this unit's
    paused-interleaving tests."""
    retarget_entered, release_retarget = _pause_retarget_links(monkeypatch)

    retargeter = threading.Thread(
        target=_retarget_other_notes, args=(vault, old_target, new_target)
    )
    retargeter.start()
    assert retarget_entered.wait(timeout=5)

    second = threading.Thread(target=second_op)
    second.start()
    time.sleep(0.2)  # let second_op reach (and, if fixed, block on) the lock

    release_retarget.set()
    retargeter.join(timeout=5)
    second.join(timeout=5)
    assert not retargeter.is_alive()
    assert not second.is_alive()


def test_retarget_other_notes_skips_one_unresolvable_note_without_aborting(
    vault: Path, tmp_path: Path
) -> None:
    """Regression for the lock-key resolve sitting outside its own
    try/except: if computing an OTHER note's lock key itself raises
    (e.g. a note file that's a symlink resolving outside the vault), that
    failure must be caught and logged like every other per-note failure
    in this loop, not escape and abort retargeting for every remaining
    note. `escaped.md` here is exactly such a note; `move_note` must
    still succeed and still retarget the resolvable `b.md`."""
    write_note(vault, "a.md", "content a")
    write_note(vault, "b.md", "See [A](a.md).")

    outside_file = tmp_path / "outside.md"
    outside_file.write_text("outside content")
    (vault / "escaped.md").symlink_to(outside_file)

    note, retargeted = move_note(vault, "a.md", "c.md")

    assert note.path == "c.md"
    assert retargeted == ["b.md"]
    assert "[A](c.md)" in read_note(vault, "b.md").content
    assert not (vault / "a.md").exists()
    assert (vault / "c.md").is_file()


def test_retarget_other_notes_relative_vault_root_lock_key_matches_write_note(
    tmp_path: Path, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the lock-key bug this unit exists to fix: a bare
    `vault_root / other_path` join (instead of
    `resolve_note_path(vault_root, other_path)`) produces a RELATIVE
    `Path` when `vault_root` itself is relative (a real local-dev config
    -- `backend/.env.example` documents `CEREBRUM_VAULT_PATH=../vault`),
    while every other call site's lock key is absolute -- two different
    `Path` objects for the same physical file, so the lock silently
    no-ops. Same shape as the lost-update test below, but with a
    relative `vault_root`: if the lock keys don't collide, the
    concurrent `write_note` races ahead unblocked, and the paused
    retargeter's later, stale-read write reverts it on release.
    """
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [T](target.md).")
    (vault / "folder").mkdir()
    (vault / "target.md").rename(vault / "folder" / "target.md")

    monkeypatch.chdir(tmp_path)
    relative_root = Path(os.path.relpath(vault, start=tmp_path))
    assert not relative_root.is_absolute()

    def do_write() -> None:
        write_note(relative_root, "linker.md", "overwritten by concurrent write")

    _run_against_paused_retarget(
        relative_root, monkeypatch, "target.md", "folder/target.md", do_write
    )

    final = read_note(vault, "linker.md").content
    assert "overwritten by concurrent write" in final
    assert "[T](" not in final


def test_retarget_other_notes_and_write_note_lost_update_closed(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces the plan's lost-update scenario end-to-end:
    `_retarget_other_notes`'s critical section for `linker.md`, paused
    mid-flight, runs concurrently with a `write_note` for the SAME path.
    Locking must serialize the two so the second-run operation's effect
    fully lands -- not a hybrid, and not `write_note`'s content silently
    reverted by the retargeter's stale-read write landing afterward."""
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [T](target.md).")
    (vault / "folder").mkdir()
    (vault / "target.md").rename(vault / "folder" / "target.md")

    def do_write() -> None:
        write_note(vault, "linker.md", "Overwritten directly, no link at all.")

    _run_against_paused_retarget(
        vault, monkeypatch, "target.md", "folder/target.md", do_write
    )

    # write_note ran second (blocked until the retargeter released), so
    # its content is the final, complete state -- not reverted by a
    # stale retarget write landing afterward, nor a byte hybrid.
    final = read_note(vault, "linker.md").content
    assert "Overwritten directly, no link at all." in final
    assert "[T](" not in final


def test_retarget_other_notes_and_delete_note_resurrection_closed(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces the plan's resurrection scenario end-to-end:
    `_retarget_other_notes`'s critical section for `linker.md`, paused
    mid-flight, runs concurrently with a `delete_note` for the SAME
    path. Locking must serialize the two so `linker.md` stays deleted --
    the retargeter's write (from its earlier, pre-delete read) must not
    resurrect a file a concurrent delete removed."""
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [T](target.md).")
    (vault / "folder").mkdir()
    (vault / "target.md").rename(vault / "folder" / "target.md")

    delete_errors: dict[str, BaseException] = {}

    def do_delete() -> None:
        try:
            delete_note(vault, "linker.md")
        except BaseException as exc:  # noqa: BLE001 -- capture across threads
            delete_errors["error"] = exc

    _run_against_paused_retarget(
        vault, monkeypatch, "target.md", "folder/target.md", do_delete
    )

    # delete_note ran second (blocked until the retargeter released,
    # which lands its write first since the file still existed at read
    # time) -- its unlink runs after, so the file stays gone rather than
    # being resurrected by the retargeter's stale-read write.
    assert "error" not in delete_errors
    assert not (vault / "linker.md").exists()


def test_retarget_other_notes_does_not_block_unrelated_write_note(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_retarget_other_notes`'s critical section for `linker.md`, paused
    mid-flight, does not block a concurrent `write_note` for a wholly
    unrelated, path-disjoint note -- the per-note locking added in this
    unit must not accidentally serialize unrelated work."""
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [T](target.md).")
    write_note(vault, "unrelated.md", "original")
    (vault / "folder").mkdir()
    (vault / "target.md").rename(vault / "folder" / "target.md")

    elapsed: list[float] = []

    def do_write() -> None:
        start = time.monotonic()
        write_note(vault, "unrelated.md", "updated while retarget is mid-flight")
        elapsed.append(time.monotonic() - start)

    _run_against_paused_retarget(
        vault, monkeypatch, "target.md", "folder/target.md", do_write
    )

    assert elapsed[0] < 1.0
    assert (
        "updated while retarget is mid-flight"
        in read_note(vault, "unrelated.md").content
    )


def test_move_note_cross_linked_concurrent_moves_do_not_deadlock(
    vault: Path,
) -> None:
    """Two concurrent `move_note` calls, `a.md -> c.md` and `b.md ->
    d.md`, where `a.md` links to `b.md` and vice versa (so each move's
    retarget phase touches the other move's original path), must both
    complete without hanging under REAL, fully-wired locking --
    `_retarget_other_notes` now takes its own per-note locks (this
    unit), unlike the monkeypatch simulation
    `test_move_note_relocation_lock_released_before_retarget_call` used
    when that locking didn't exist yet. Proves U2's release-before-
    retarget scoping actually holds end-to-end."""
    write_note(vault, "a.md", "See [B](b.md).")
    write_note(vault, "b.md", "See [A](a.md).")

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
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert results.get("a") is None
    assert results.get("b") is None
    assert (vault / "c.md").is_file()
    assert (vault / "d.md").is_file()


def test_retarget_note_links_cross_linked_concurrent_calls_do_not_deadlock(
    vault: Path,
) -> None:
    """`retarget_note_links` shares `move_note`'s release-before-retarget
    scoping (see the comment above its own `_retarget_other_notes` call),
    for the identical AB-BA deadlock reason -- it is the watcher's
    rename-repointing entry point (`index/indexer.py`'s pairing path), so
    it can run concurrently with another watcher batch or an API/MCP move
    touching a cross-linked note. `move_note` has two dedicated
    concurrency tests for this property; this is `retarget_note_links`'s
    equivalent real, fully-wired (no monkeypatching) proof: `a.md` and
    `b.md` link to each other, both are externally renamed (`a.md->c.md`,
    `b.md->d.md`, simulating a same-batch watcher-detected rename pair),
    and both notes' `retarget_note_links` calls -- each of which must
    retarget the OTHER note's now-stale incoming link -- run concurrently."""
    write_note(vault, "a.md", "See [B](b.md).")
    write_note(vault, "b.md", "See [A](a.md).")
    (vault / "a.md").rename(vault / "c.md")
    (vault / "b.md").rename(vault / "d.md")

    results: dict[str, BaseException | None] = {}

    def do_retarget(name: str, old: str, new: str) -> None:
        try:
            retarget_note_links(vault, old, new)
            results[name] = None
        except BaseException as exc:  # noqa: BLE001 -- capture across threads
            results[name] = exc

    t1 = threading.Thread(target=do_retarget, args=("a", "a.md", "c.md"))
    t2 = threading.Thread(target=do_retarget, args=("b", "b.md", "d.md"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert results.get("a") is None
    assert results.get("b") is None
    assert "[B](d.md)" in read_note(vault, "c.md").content
    assert "[A](c.md)" in read_note(vault, "d.md").content
