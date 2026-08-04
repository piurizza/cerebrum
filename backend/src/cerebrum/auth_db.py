from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "auth_schema.sql"

# A new, separate lock from index/db.py's write_lock -- that one is scoped
# to serializing writers on *that* module's own connection object, and
# reusing it here would serialize unrelated index and auth writes against
# each other for no benefit. Same rationale as write_lock otherwise: this
# connection is shared across request handlers (some in Starlette's
# threadpool, one on the event loop), and WAL + busy_timeout alone don't
# make SQLite's per-connection "in a transaction" state safe across
# threads -- every multi-statement auth write sequence must take this lock
# for the duration of its `with auth_write_lock, conn:` block (see
# index/indexer.py for the idiom later units mirror here).
#
# This guards single-statement READS too, not just multi-statement
# writes -- confirmed by direct reproduction (30x concurrent-registration
# runs, ~15% failure rate) that an unlocked read against this connection
# can race a concurrent thread's locked write and surface as a raw
# `sqlite3.InterfaceError('bad parameter or other API misuse')`, not a
# clean application-level exception. Python's sqlite3 driver does not
# support true concurrent statement execution from multiple threads
# against one Connection object, even when the SQL itself is read-only and
# logically safe to interleave -- every `auth_db.execute()` call from
# application code, read or write, must be wrapped `with auth_write_lock:`
# (or `with auth_write_lock, conn:` when it also needs the transaction
# commit/rollback that context manager provides).
auth_write_lock = threading.Lock()


def connect(db_path: Path) -> sqlite3.Connection:
    # pylint: disable=duplicate-code
    # The opening lines mirror index/db.py's connect() (WAL mode,
    # busy_timeout, row_factory) by design -- a genuinely separate
    # database deliberately kept structurally parallel, not a shared
    # helper to dedupe, since it then diverges on purpose (see the
    # PRAGMAs below).
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    # Unlike index/db.py's database (a disposable cache, rebuildable from
    # the vault at any time -- see SPEC.md), this one is the sole record of
    # accounts, sessions, and tokens; there is no source to rebuild it
    # from. FULL (rather than WAL's usual NORMAL) forces an fsync on every
    # commit, so an OS crash or power loss can't silently roll back an
    # already-acknowledged write -- e.g. a revoked refresh token coming
    # back to life after an unclean shutdown. Auth writes (login, token
    # rotation, invite consumption) are low-frequency, so the extra fsync
    # latency this costs is immaterial next to that guarantee.
    conn.execute("PRAGMA synchronous = FULL")
    # Declared per-column in auth_schema.sql, but SQLite does not enforce
    # foreign keys unless this is set on every connection that touches
    # them -- unlike index/schema.sql, which has no cross-table references
    # and so never needed this.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn
