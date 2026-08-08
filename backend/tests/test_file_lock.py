from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from cerebrum.notes.file_lock import file_lock


def test_same_path_serializes_two_threads(tmp_path: Path) -> None:
    """Two threads locking the SAME path never have their critical
    sections interleaved: one fully enters-and-exits before the other
    enters."""
    path = tmp_path / "note.md"
    events: list[tuple[int, str]] = []
    events_lock = threading.Lock()

    def worker(thread_id: int) -> None:
        with file_lock(path):
            with events_lock:
                events.append((thread_id, "enter"))
            # Give the other thread a chance to (incorrectly) interleave
            # if locking isn't actually serializing access.
            time.sleep(0.05)
            with events_lock:
                events.append((thread_id, "exit"))

    threads = [
        threading.Thread(target=worker, args=(0,)),
        threading.Thread(target=worker, args=(1,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert len(events) == 4
    # Each thread's "enter" must be immediately followed by its own
    # "exit" -- no other thread's enter can appear in between.
    for index in range(0, len(events), 2):
        enter_id, enter_kind = events[index]
        exit_id, exit_kind = events[index + 1]
        assert enter_kind == "enter"
        assert exit_kind == "exit"
        assert enter_id == exit_id


def test_different_paths_do_not_block_each_other(tmp_path: Path) -> None:
    """Two threads locking DIFFERENT paths run concurrently -- both are
    inside their critical section at the same time, proven via a
    barrier both must reach before either is allowed to leave."""
    path_a = tmp_path / "a.md"
    path_b = tmp_path / "b.md"
    barrier = threading.Barrier(2, timeout=5)
    results: dict[str, bool] = {}

    def worker(name: str, path: Path) -> None:
        with file_lock(path):
            try:
                barrier.wait()
                results[name] = True
            except threading.BrokenBarrierError:
                results[name] = False

    threads = [
        threading.Thread(target=worker, args=("a", path_a)),
        threading.Thread(target=worker, args=("b", path_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    # If the two locks contended with each other (e.g. a bug that made
    # the registry lock global), the second thread would never reach the
    # barrier while the first is still holding its lock, and the
    # barrier would time out / break for both.
    assert results == {"a": True, "b": True}


def test_lock_released_on_exception(tmp_path: Path) -> None:
    """A wrapped block that raises must still release the path lock --
    a second acquirer isn't left blocked forever."""
    path = tmp_path / "note.md"

    with pytest.raises(RuntimeError, match="boom"), file_lock(path):
        raise RuntimeError("boom")

    # Attempt a second acquisition from a separate thread with a bounded
    # join timeout, so a regression (lock never released) fails the test
    # instead of hanging the suite forever.
    acquired = threading.Event()

    def second_acquirer() -> None:
        with file_lock(path):
            acquired.set()

    thread = threading.Thread(target=second_acquirer)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert acquired.is_set()


def test_registry_lock_is_not_held_for_whole_critical_section(
    tmp_path: Path,
) -> None:
    """The registry lock only guards the brief get-or-create step, not
    the caller's whole critical section -- a get-or-create for a
    DIFFERENT, new path must complete quickly even while another thread
    is deep inside an existing path's (long-running) critical section."""
    busy_path = tmp_path / "busy.md"
    other_path = tmp_path / "other.md"
    entered_busy = threading.Event()
    release_busy = threading.Event()

    def hold_busy_path() -> None:
        with file_lock(busy_path):
            entered_busy.set()
            # Block here, well past what the other-path lookup below
            # should ever need to wait.
            release_busy.wait(timeout=5)

    thread = threading.Thread(target=hold_busy_path)
    thread.start()
    assert entered_busy.wait(timeout=5)

    start = time.monotonic()
    with file_lock(other_path):
        pass
    elapsed = time.monotonic() - start

    release_busy.set()
    thread.join(timeout=5)
    assert not thread.is_alive()

    # A registry-lock-held-too-long bug would make this wait for
    # release_busy (up to its 5s timeout); a correct implementation
    # returns almost immediately.
    assert elapsed < 1.0
