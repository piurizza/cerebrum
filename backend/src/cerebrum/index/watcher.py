from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from watchfiles import BaseFilter, Change, awatch

# `WatchfilesRustInternalError` is watchfiles' catch-all for unexpected
# errors surfaced by the underlying Rust `notify` watcher (installed
# 1.2.0 does not re-export it from the public `watchfiles` namespace, only
# from `watchfiles._rust_notify` -- see its `.pyi` stub's `__all__`).
from watchfiles._rust_notify import (  # noqa: PLC2701  # pylint: disable=no-name-in-module
    WatchfilesRustInternalError,
)

from cerebrum.index.indexer import apply_watch_batch
from cerebrum.settings import Settings

logger = logging.getLogger(__name__)


class VaultFilter(BaseFilter):
    """Restricts watched changes to vault markdown content.

    Mirrors `notes/service.py`'s `iter_note_paths` exclusion rule
    (skip `.cerebrum/`, only `.md` files) but applied at the
    `watch_filter` level instead of a glob -- `.cerebrum/` subdirectories
    are still watched at the OS level (see KTD8), just filtered out of
    the events `awatch` yields.
    """

    ignore_dirs = (*BaseFilter.ignore_dirs, ".cerebrum")

    def __call__(self, change: Change, path: str) -> bool:
        return path.endswith(".md") and super().__call__(change, path)


async def watch_vault(
    conn: sqlite3.Connection,
    vault_root: Path,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Watch `vault_root` for `.md` changes and keep the index in sync.

    Runs until `stop_event` is set or the enclosing task is cancelled --
    both are let to propagate normally. Errors raised by the underlying
    watcher (vault root removed/inaccessible, or an internal Rust-notify
    failure) are caught, logged, and cause this coroutine to return
    rather than raise, so a supervising task can treat a finished watcher
    task as "stopped", not "crashed".
    """
    # `awatch()` always yields absolute paths regardless of the watch root
    # given to it. `vault_root` defaults to a relative path (see
    # Settings.cerebrum_vault_path), and computing a relative path from an
    # absolute one against a non-resolved relative root raises
    # `ValueError` -- mirrors `notes/service.py`'s `resolve_note_path`.
    vault_root = vault_root.resolve()

    try:
        async for changes in awatch(
            vault_root,
            watch_filter=VaultFilter(),
            debounce=settings.watcher_debounce_ms,
            stop_event=stop_event,
        ):
            # `changes` is a set, not chronologically ordered -- a rapid
            # delete-then-recreate (or vice versa) of the same path within
            # one debounce window can yield both a `deleted` and an
            # `added`/`modified` entry for it. Trusting each entry's own
            # `Change` value could apply them out of order and leave a
            # wrong index row until the next backstop rescan. Instead,
            # collapse to one decisive action per distinct path, based on
            # whether the file actually exists right now.
            rel_paths = {
                Path(abs_path).relative_to(vault_root).as_posix()
                for _, abs_path in changes
            }
            # `apply_watch_batch` (index/indexer.py) classifies the whole
            # batch at once: a delete+create pair sharing a content hash is
            # treated as a same-batch rename (repointing other notes'
            # links), everything else is applied as independent
            # deletes/upserts. It contains its own per-path/per-pair
            # errors (transient races included), mirroring the containment
            # this loop used to do itself.
            await asyncio.to_thread(apply_watch_batch, conn, vault_root, rel_paths)
    except (OSError, WatchfilesRustInternalError) as exc:
        # OSError also covers FileNotFoundError/PermissionError raised by
        # awatch() itself (vault root removed/inaccessible), not just the
        # two named subclasses -- e.g. an inotify watch-limit error.
        logger.warning("vault watcher stopped: %s", exc)
