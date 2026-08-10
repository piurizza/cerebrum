from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

import pytest

from cerebrum import main as main_module
from cerebrum.index.db import list_notes
from cerebrum.main import _run_backstop_rescan
from cerebrum.settings import Settings
from tests.mcp_test_support import issue_test_access_token, mcp_test_client


def _wait_until(check, timeout: float = 5.0, interval: float = 0.05) -> None:
    """Sync-world equivalent of test_watcher.py's `_wait_until` -- polls
    `check` (a plain callable, not a coroutine) until it passes or the
    timeout expires, since these tests drive the app through a synchronous
    `TestClient`, not `asyncio.run`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(interval)
    pytest.fail("condition not met before timeout")


def _settings(vault: Path, **overrides: object) -> Settings:
    return Settings(
        auth_jwt_secret="x" * 32,
        auth_setup_token="y" * 32,
        cerebrum_vault_path=vault,
        **overrides,  # type: ignore[arg-type]
    )


def test_watcher_task_indexes_externally_written_file(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path (R3): with watcher_enabled=True (default), `lifespan()`
    actually starts a live `watch_vault` task, not just imports it -- a
    file written directly to disk (not through the API) shows up in
    `GET /api/notes` without a restart. Integration-level complement to
    U3's unit-level `test_watcher.py` tests, which exercise `watch_vault`
    in isolation rather than through the app's own startup path."""
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "50")
    with mcp_test_client(vault, monkeypatch) as client:
        token = issue_test_access_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        (vault / "external.md").write_text(
            "---\ntitle: External\n---\nbody", encoding="utf-8"
        )

        def check() -> bool:
            response = client.get("/api/notes", headers=headers)
            return response.status_code == 200 and any(
                note["path"] == "external.md" for note in response.json()
            )

        _wait_until(check)


def test_watcher_disabled_does_not_index_externally_written_file(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configuration: `watcher_enabled=False` starts the app with neither
    background task running -- verified by the absence of the effect the
    happy-path test above checks for."""
    monkeypatch.setenv("WATCHER_ENABLED", "false")
    with mcp_test_client(vault, monkeypatch) as client:
        token = issue_test_access_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        (vault / "external.md").write_text("body", encoding="utf-8")

        # No reasonable wait should ever make this appear; give it
        # comfortably longer than the happy-path test's debounce window,
        # then assert it never landed.
        time.sleep(1.0)
        response = client.get("/api/notes", headers=headers)
        assert response.status_code == 200
        assert response.json() == []


def test_backstop_rescan_indexes_externally_written_file(
    vault: Path, db: sqlite3.Connection
) -> None:
    """Backstop rescan (R4): calling `_run_backstop_rescan` directly with a
    short interval (rather than sleeping the real 300s default) picks up a
    file written straight to disk, exercising the backstop path on its
    own, independent of the live watcher."""
    settings = _settings(vault, watcher_backstop_interval_seconds=1)

    async def run() -> None:
        task = asyncio.create_task(_run_backstop_rescan(db, vault, settings))
        try:
            (vault / "a.md").write_text("content", encoding="utf-8")
            await asyncio.sleep(1.5)
            assert [note.path for note in list_notes(db)] == ["a.md"]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())


def test_watcher_task_creation_failure_still_starts_app(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Graceful degradation -- the *minor* defensive backstop from the
    Approach's step 3, NOT the same protection
    `test_mcp_mount.py::test_lifespan_teardown_on_startup_failure` proves
    for `rebuild_index`. That test proves the `AsyncExitStack` unwinds
    correctly when a startup step raises; this proves the opposite: a
    failure constructing the watcher/backstop tasks is swallowed so the
    app keeps starting at all. R4's actual, primary protection (a
    missing/unreadable vault path) lives inside `watch_vault`'s own
    `awatch()` error handling, already covered by `test_watcher.py`, not
    here."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("watcher task creation boom")

    monkeypatch.setattr(main_module, "watch_vault", _boom)

    with (
        caplog.at_level(logging.WARNING, logger="cerebrum.main"),
        mcp_test_client(vault, monkeypatch) as client,
    ):
        assert client.get("/api/health").status_code == 200
        # app.state.db still functions -- proves the failure was
        # contained to watcher-task startup, not the whole lifespan.
        client.app.state.db.execute("SELECT 1")
    assert "watcher task creation boom" in caplog.text


def test_backstop_rescan_survives_iteration_failure(
    vault: Path,
    db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """KTD9's core guarantee: one `rebuild_index` failure inside a single
    backstop iteration must not permanently kill the backstop task -- a
    subsequent tick still calls `rebuild_index` again rather than the loop
    (and the task) dying outright."""
    calls: list[int] = []
    real_rebuild_index = main_module.rebuild_index

    def flaky_rebuild_index(
        conn: sqlite3.Connection, vault_root: Path, pending_renames: object = None
    ) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        real_rebuild_index(conn, vault_root, pending_renames)

    monkeypatch.setattr(main_module, "rebuild_index", flaky_rebuild_index)
    settings = _settings(vault, watcher_backstop_interval_seconds=1)

    async def run() -> None:
        task = asyncio.create_task(_run_backstop_rescan(db, vault, settings))
        try:
            with caplog.at_level(logging.WARNING, logger="cerebrum.main"):
                await asyncio.sleep(2.5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())

    assert len(calls) >= 2
    assert "backstop rescan iteration failed" in caplog.text


def test_shutdown_cancels_and_awaits_both_tasks(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: pytest.WarningsRecorder,
) -> None:
    """Shutdown: after the `TestClient` context exits, both the watcher and
    backstop tasks are finished (no dangling tasks) and neither leaves an
    unretrieved exception behind -- the `asyncio.gather(...,
    return_exceptions=True)` shutdown path (KTD9) already consumed
    whatever each task raised."""
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "50")

    created_tasks: list[asyncio.Task[None]] = []
    real_create_task = asyncio.create_task

    def recording_create_task(
        coro: object, *args: object, **kwargs: object
    ) -> asyncio.Task[None]:
        task = real_create_task(coro, *args, **kwargs)  # type: ignore[arg-type]
        created_tasks.append(task)
        return task

    monkeypatch.setattr(main_module.asyncio, "create_task", recording_create_task)

    with mcp_test_client(vault, monkeypatch):
        pass

    watcher_tasks = [
        task
        for task in created_tasks
        if task.get_coro().__qualname__  # type: ignore[union-attr]
        in ("watch_vault", "_run_backstop_rescan")
    ]
    assert len(watcher_tasks) == 2
    for task in watcher_tasks:
        assert task.done()
        if task.cancelled():
            continue
        # Retrieving the result/exception here must not raise, and a task
        # that exited on its own (e.g. watch_vault noticing stop_event
        # before its cancellation lands) must have exited cleanly.
        assert task.exception() is None

    assert not any(
        "Task was destroyed but it is pending" in str(warning.message)
        for warning in recwarn.list
    )
