from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from watchfiles import Change
from watchfiles._rust_notify import (  # pylint: disable=no-name-in-module
    WatchfilesRustInternalError,
)

from cerebrum.graph.service import get_backlinks
from cerebrum.index import indexer, watcher
from cerebrum.index.db import list_notes
from cerebrum.index.indexer import upsert_note
from cerebrum.index.watcher import VaultFilter, watch_vault
from cerebrum.notes.service import read_note, write_note
from cerebrum.settings import Settings


def _settings(debounce_ms: int = 100) -> Settings:
    return Settings(
        auth_jwt_secret="x" * 32,
        auth_setup_token="y" * 32,
        watcher_debounce_ms=debounce_ms,
    )


async def _wait_until(check: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if check():
            return
        await asyncio.sleep(0.05)
    pytest.fail("condition not met before timeout")


async def _run_and_wait(
    conn: sqlite3.Connection,
    vault_root: Path,
    settings: Settings,
    mutate: Callable[[], None],
    check: Callable[[], bool],
) -> None:
    """Run `watch_vault` in the background, apply `mutate`, then poll
    `check` until it passes (or fail the test on timeout), stopping the
    watcher task cleanly either way."""
    stop_event = asyncio.Event()
    task = asyncio.create_task(watch_vault(conn, vault_root, settings, stop_event))
    try:
        await asyncio.sleep(0.2)  # let the OS-level watch attach before mutating
        mutate()
        await _wait_until(check)
    finally:
        stop_event.set()
        await task


def test_vault_filter_allows_only_markdown_outside_cerebrum() -> None:
    vault_filter = VaultFilter()
    assert vault_filter(Change.added, "/vault/notes/a.md") is True
    assert vault_filter(Change.added, "/vault/notes/a.txt") is False
    assert vault_filter(Change.added, "/vault/.cerebrum/index.sqlite3") is False
    assert vault_filter(Change.added, "/vault/.cerebrum/decoy.md") is False


def test_creating_md_file_indexes_it(vault: Path, db: sqlite3.Connection) -> None:
    settings = _settings()

    def mutate() -> None:
        write_note(vault, "a.md", "---\ntitle: A\n---\nbody")

    def check() -> bool:
        return [note.path for note in list_notes(db)] == ["a.md"]

    asyncio.run(_run_and_wait(db, vault, settings, mutate, check))


def test_deleting_md_file_removes_index_row(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "a.md", "content")
    upsert_note(db, vault, "a.md")
    settings = _settings()

    def mutate() -> None:
        (vault / "a.md").unlink()

    def check() -> bool:
        return list_notes(db) == []

    asyncio.run(_run_and_wait(db, vault, settings, mutate, check))


def test_non_md_and_dotcerebrum_changes_are_ignored(
    vault: Path, db: sqlite3.Connection
) -> None:
    settings = _settings()

    async def run() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(watch_vault(db, vault, settings, stop_event))
        try:
            await asyncio.sleep(0.2)
            (vault / "notes.txt").write_text("not markdown", encoding="utf-8")
            (vault / ".cerebrum").mkdir(exist_ok=True)
            (vault / ".cerebrum" / "decoy.md").write_text("decoy", encoding="utf-8")
            # Give the watcher ample time (well past debounce+step) to have
            # processed -- and correctly ignored -- both changes before we
            # assert nothing landed in the index.
            await asyncio.sleep(settings.watcher_debounce_ms / 1000 + 1.0)
            assert list_notes(db) == []
        finally:
            stop_event.set()
            await task

    asyncio.run(run())


def test_external_rename_removes_old_and_indexes_new(
    vault: Path, db: sqlite3.Connection
) -> None:
    write_note(vault, "old.md", "content")
    upsert_note(db, vault, "old.md")
    settings = _settings()

    def mutate() -> None:
        (vault / "old.md").unlink()
        write_note(vault, "new.md", "content")

    def check() -> bool:
        return {note.path for note in list_notes(db)} == {"new.md"}

    asyncio.run(_run_and_wait(db, vault, settings, mutate, check))


def test_external_rename_relinks_third_note(
    vault: Path, db: sqlite3.Connection
) -> None:
    """End-to-end complement to `test_apply_watch_batch_relinks_third_note_on_rename`
    (test_indexer.py) -- proves the same rename-pairing + link-repointing
    behavior through the REAL `watch_vault`/`awatch` loop, not by calling
    `apply_watch_batch` directly.
    """
    write_note(vault, "target.md", "content")
    write_note(vault, "linker.md", "See [T](target.md).")
    upsert_note(db, vault, "target.md")
    upsert_note(db, vault, "linker.md")
    settings = _settings()

    def mutate() -> None:
        (vault / "target.md").rename(vault / "renamed.md")

    def check() -> bool:
        return {note.path for note in list_notes(db)} == {"renamed.md", "linker.md"}

    asyncio.run(_run_and_wait(db, vault, settings, mutate, check))

    linker = read_note(vault, "linker.md")
    assert "[T](renamed.md)" in linker.content
    assert [note.path for note in get_backlinks(db, "renamed.md")] == ["linker.md"]


def test_unrelated_delete_and_create_in_same_batch_stay_independent(
    vault: Path, db: sqlite3.Connection
) -> None:
    """A plain delete and a plain create with DIFFERENT content landing in
    the same debounce batch must not be mistaken for a rename -- both are
    applied as independent remove/upsert through the real watch loop.
    """
    write_note(vault, "gone.md", "content that is going away")
    upsert_note(db, vault, "gone.md")
    settings = _settings()

    def mutate() -> None:
        (vault / "gone.md").unlink()
        write_note(vault, "fresh.md", "totally different content")

    def check() -> bool:
        return {note.path for note in list_notes(db)} == {"fresh.md"}

    asyncio.run(_run_and_wait(db, vault, settings, mutate, check))


def test_awatch_file_not_found_error_is_caught(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_awatch(  # pylint: disable=unreachable
        *_args: object, **_kwargs: object
    ):
        raise FileNotFoundError("vault root missing")
        yield  # pragma: no cover -- unreachable, keeps this an async generator

    monkeypatch.setattr(watcher, "awatch", fake_awatch)
    settings = _settings()

    async def run() -> None:
        stop_event = asyncio.Event()
        # Must return normally (not raise) within a tight timeout.
        await asyncio.wait_for(
            watch_vault(db, vault, settings, stop_event), timeout=2.0
        )

    asyncio.run(run())


def test_awatch_rust_internal_error_is_caught_midstream(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_awatch(*_args: object, **_kwargs: object):
        yield set()
        raise WatchfilesRustInternalError("boom")

    monkeypatch.setattr(watcher, "awatch", fake_awatch)
    settings = _settings()

    async def run() -> None:
        stop_event = asyncio.Event()
        await asyncio.wait_for(
            watch_vault(db, vault, settings, stop_event), timeout=2.0
        )

    asyncio.run(run())


def test_relative_vault_root_does_not_raise(
    tmp_path: Path,
    vault: Path,
    db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: `watch_vault` must `.resolve()` `vault_root` itself.

    `awatch()` always yields absolute paths regardless of the watch root
    given to it. Passing a *non-resolved* relative root (as
    `cerebrum_vault_path`'s own default, `./vault`, would be) makes
    `Path.relative_to` raise `ValueError` on the very first event unless
    `watch_vault` resolves the root before comparing against it.
    """
    monkeypatch.chdir(tmp_path)
    relative_root = Path(os.path.relpath(vault, start=tmp_path))
    assert not relative_root.is_absolute()
    settings = _settings()

    def mutate() -> None:
        write_note(vault, "a.md", "content")

    def check() -> bool:
        return [note.path for note in list_notes(db)] == ["a.md"]

    asyncio.run(_run_and_wait(db, relative_root, settings, mutate, check))


def test_debounce_setting_is_forwarded_to_awatch(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_awatch(  # pylint: disable=unreachable
        *_args: object, **kwargs: object
    ):
        captured.update(kwargs)
        return
        yield  # pragma: no cover -- unreachable, keeps this an async generator

    monkeypatch.setattr(watcher, "awatch", fake_awatch)
    settings = _settings(debounce_ms=1234)

    async def run() -> None:
        stop_event = asyncio.Event()
        await watch_vault(db, vault, settings, stop_event)

    asyncio.run(run())

    assert captured["debounce"] == 1234


def test_per_file_processing_error_does_not_kill_watcher(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a single file's transient processing error (e.g. an
    `upsert_note` race) must not end the whole `watch_vault` coroutine --
    only the file that errored is skipped; a later, unrelated change is
    still processed. Code review found the original implementation's
    outer `try/except` swallowed per-file errors and returned, silently
    downgrading live sync to the 300s backstop rescan for the rest of the
    process's life.
    """
    real_upsert_note = indexer.upsert_note
    calls: list[str] = []

    def flaky_upsert_note(
        conn: sqlite3.Connection, vault_root: Path, path: str
    ) -> None:
        calls.append(path)
        if path == "a.md":
            raise FileNotFoundError("simulated delete-race")
        real_upsert_note(conn, vault_root, path)

    monkeypatch.setattr(indexer, "upsert_note", flaky_upsert_note)
    settings = _settings()

    async def run() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(watch_vault(db, vault, settings, stop_event))
        try:
            await asyncio.sleep(0.2)
            write_note(vault, "a.md", "content a")  # triggers the simulated error
            await _wait_until(lambda: "a.md" in calls)

            # The watcher must still be running (not returned/crashed) and
            # must still process a subsequent, unrelated change.
            assert not task.done()
            write_note(vault, "b.md", "content b")
            await _wait_until(
                lambda: {note.path for note in list_notes(db)} == {"b.md"}
            )
        finally:
            stop_event.set()
            await task

    asyncio.run(run())


def test_same_path_conflicting_events_resolved_by_file_existence(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: `awatch()` yields a `set`, not a chronologically ordered
    sequence -- a rapid delete-then-recreate of the same path within one
    debounce window can land both a `deleted` and an `added` entry for it
    in the same batch, in arbitrary iteration order. `watch_vault` must
    resolve the final action from the file's actual current existence,
    not from whichever entry happens to be applied last.
    """
    write_note(vault, "a.md", "content")
    abs_path = str((vault / "a.md").resolve())

    async def fake_awatch(*_args: object, **_kwargs: object):
        # The file exists on disk (written above) -- both a `deleted` and
        # an `added` entry appear for it in one batch, deliberately in the
        # "wrong" order (deleted last) to prove order isn't what decides
        # the outcome.
        yield {(Change.added, abs_path), (Change.deleted, abs_path)}

    monkeypatch.setattr(watcher, "awatch", fake_awatch)
    settings = _settings()

    async def run() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(watch_vault(db, vault, settings, stop_event))
        try:
            await _wait_until(lambda: [n.path for n in list_notes(db)] == ["a.md"])
        finally:
            stop_event.set()
            await task

    asyncio.run(run())


def test_burst_of_rapid_writes_dispatches_once(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Several writes to the same file within the debounce window must
    collapse into a single dispatched index write -- proving
    `watcher_debounce_ms` is actually wired through to `awatch`, not just
    present in config."""
    calls: list[str] = []
    real_upsert_note = indexer.upsert_note

    def counting_upsert_note(
        conn: sqlite3.Connection, vault_root: Path, path: str
    ) -> None:
        calls.append(path)
        real_upsert_note(conn, vault_root, path)

    monkeypatch.setattr(indexer, "upsert_note", counting_upsert_note)
    settings = _settings(debounce_ms=400)

    async def run() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(watch_vault(db, vault, settings, stop_event))
        try:
            await asyncio.sleep(0.2)
            # Fire the whole burst back-to-back, with no `await` between
            # writes, so the underlying OS events land solidly inside a
            # single quiet-period/debounce grouping window regardless of
            # scheduler jitter.
            for i in range(5):
                write_note(vault, "a.md", f"content {i}")
            # Wait comfortably past the debounce cap so the whole burst has
            # had a chance to flush as one grouped batch.
            await asyncio.sleep(settings.watcher_debounce_ms / 1000 + 1.0)
        finally:
            stop_event.set()
            await task

    asyncio.run(run())

    assert calls == ["a.md"]
