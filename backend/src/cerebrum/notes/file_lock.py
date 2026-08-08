"""Per-note-path locking so concurrent mutations of the SAME file serialize.

Every note-file mutation (API PUT/DELETE/move handlers, MCP's create/update
tools, and the filesystem watcher's rename-triggered link retargeting)
touches the filesystem directly -- read-modify-write, or a multi-step
relocation -- with no coordination between callers. Two concurrent writers
to the same path can interleave their reads and writes (e.g. both read the
old content, both compute an update, and the second write silently clobbers
the first's), which is the same category of race `index/db.py`'s
`write_lock` documents for the sqlite connection, just at the filesystem
layer instead. `file_lock` gives each mutation site a lock to hold around
its own read-modify-write sequence so only one such sequence runs against a
given path at a time.

This is a *per-path* registry, not one global lock like `index/db.py`'s
(a single sqlite Connection is one shared resource, so one lock is
correct there) -- two callers mutating different notes have nothing to
contend over, so serializing them too would be pure lost concurrency.
`_locks` hands out one `threading.Lock` per path, created lazily; disjoint
paths get disjoint locks and never block each other. `_registry_lock`
guards only the get-or-create step against that dict itself -- it is held
just long enough to look up or insert an entry, then released *before*
the caller's own path lock is acquired, so it never sits blocked for the
duration of another caller's critical section.

**Callers must pass an already-`resolve_note_path`-resolved `Path`.** This
module does not resolve, normalize, or canonicalize what it's given -- it
locks on `Path` equality/hash alone. Two call sites that lock the "same"
file via different spellings (a relative path vs. its resolved absolute
form, or two paths differing only in trailing separators/case on a
case-insensitive filesystem) will hash to different dict keys and end up
with two different locks guarding the same file, which defeats locking
entirely without raising anything to say so.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_locks: dict[Path, threading.Lock] = {}
_registry_lock = threading.Lock()


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Serialize access to `path` against every other caller locking the
    same (already-resolved) `Path`. Callers locking different paths do
    not block each other -- see module docstring.
    """
    with _registry_lock:
        lock = _locks.setdefault(path, threading.Lock())

    with lock:
        yield
