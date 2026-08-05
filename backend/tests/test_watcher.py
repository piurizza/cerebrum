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

from cerebrum.index import watcher
from cerebrum.index.db import list_notes
from cerebrum.index.indexer import upsert_note
from cerebrum.index.watcher import VaultFilter, watch_vault
from cerebrum.notes.service import write_note
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


def test_burst_of_rapid_writes_dispatches_once(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Several writes to the same file within the debounce window must
    collapse into a single dispatched index write -- proving
    `watcher_debounce_ms` is actually wired through to `awatch`, not just
    present in config."""
    calls: list[str] = []
    real_upsert_note = watcher.upsert_note

    def counting_upsert_note(
        conn: sqlite3.Connection, vault_root: Path, path: str
    ) -> None:
        calls.append(path)
        real_upsert_note(conn, vault_root, path)

    monkeypatch.setattr(watcher, "upsert_note", counting_upsert_note)
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
