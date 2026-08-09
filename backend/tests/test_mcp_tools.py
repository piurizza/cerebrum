from __future__ import annotations

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult

from cerebrum.index.indexer import upsert_note
from cerebrum.mcp.server import create_mcp_server
from cerebrum.settings import get_settings


def _write_note(vault: Path, path: str, content: str) -> None:
    file_path = vault / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _mcp_server(db: sqlite3.Connection) -> FastMCP:
    app = FastAPI()
    app.state.db = db
    return create_mcp_server(app)


def test_list_notes_returns_current_notes(vault: Path, db: sqlite3.Connection) -> None:
    _write_note(vault, "a.md", "---\ntitle: A\n---\nbody")
    upsert_note(db, vault, "a.md")
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("list-notes", {})
            assert [item.path for item in result.data] == ["a.md"]

    asyncio.run(run())


def test_list_notes_on_empty_vault_returns_empty_list(db: sqlite3.Connection) -> None:
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("list-notes", {})
            assert result.data == []

    asyncio.run(run())


def test_get_note_on_existing_path_returns_content(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # get_note() reads via get_settings().cerebrum_vault_path (not the index),
    # so the settings cache must point at this test's tmp vault.
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    _write_note(vault, "a.md", "---\ntitle: A\n---\nhello world")
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("get-note", {"path": "a.md"})
            assert "hello world" in result.data.content

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_get_note_on_missing_path_returns_clear_tool_error(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get-note", {"path": "missing.md"}, raise_on_error=False
            )
            assert result.is_error
            assert "missing.md" in result.content[0].text

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_search_notes_with_matching_query_returns_hits(
    vault: Path, db: sqlite3.Connection
) -> None:
    _write_note(vault, "a.md", "---\ntitle: A\n---\nunique-search-term here")
    upsert_note(db, vault, "a.md")
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "search-notes", {"query": "unique-search-term"}
            )
            assert [item.path for item in result.data] == ["a.md"]

    asyncio.run(run())


def test_search_notes_with_no_matches_returns_empty_list(
    db: sqlite3.Connection,
) -> None:
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("search-notes", {"query": "nothing"})
            assert result.data == []

    asyncio.run(run())


def test_get_graph_and_get_backlinks_roundtrip_a_linked_fixture_vault(
    vault: Path, db: sqlite3.Connection
) -> None:
    _write_note(vault, "a.md", "---\ntitle: A\n---\nlinks to [B](b.md)")
    _write_note(vault, "b.md", "---\ntitle: B\n---\nno outgoing links")
    upsert_note(db, vault, "a.md")
    upsert_note(db, vault, "b.md")
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            graph_result = await client.call_tool("get-graph", {})
            node_paths = {node.path for node in graph_result.data.nodes}
            assert node_paths == {"a.md", "b.md"}
            assert any(
                edge.source == "a.md" and edge.target == "b.md"
                for edge in graph_result.data.edges
            )

            backlinks_result = await client.call_tool("get-backlinks", {"path": "b.md"})
            assert [item.path for item in backlinks_result.data] == ["a.md"]

    asyncio.run(run())


def test_create_note_on_fresh_path_is_immediately_visible(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            create_result = await client.call_tool(
                "create-note", {"path": "new.md", "content": "hello"}
            )
            assert "hello" in create_result.data.content
            assert (vault / "new.md").exists()

            # Exercises the index-sync call, not just the filesystem write.
            list_result = await client.call_tool("list-notes", {})
            assert [item.path for item in list_result.data] == ["new.md"]
            search_result = await client.call_tool("search-notes", {"query": "hello"})
            assert [item.path for item in search_result.data] == ["new.md"]

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_create_note_on_existing_path_fails_without_modifying_it(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    _write_note(vault, "a.md", "---\ntitle: A\n---\noriginal content")
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "create-note",
                {"path": "a.md", "content": "clobbered"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "already exists" in result.content[0].text

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()
    assert "original content" in (vault / "a.md").read_text(encoding="utf-8")


def test_create_note_on_existing_malformed_note_fails_without_overwriting(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    malformed = "---\ntitle: [unterminated\n---\nbody"
    _write_note(vault, "a.md", malformed)
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "create-note",
                {"path": "a.md", "content": "clobbered"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "already exists" in result.content[0].text

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()
    assert (vault / "a.md").read_text(encoding="utf-8") == malformed


def test_update_note_on_existing_path_replaces_content_and_is_visible(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    _write_note(vault, "a.md", "---\ntitle: A\n---\noriginal")
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            update_result = await client.call_tool(
                "update-note", {"path": "a.md", "content": "replaced"}
            )
            assert "replaced" in update_result.data.content
            assert "original" not in update_result.data.content

            list_result = await client.call_tool("list-notes", {})
            assert [item.path for item in list_result.data] == ["a.md"]
            search_result = await client.call_tool(
                "search-notes", {"query": "replaced"}
            )
            assert [item.path for item in search_result.data] == ["a.md"]

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_update_note_on_missing_path_fails_without_creating_a_file(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "update-note",
                {"path": "missing.md", "content": "x"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "missing.md" in result.content[0].text

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()
    assert not (vault / "missing.md").exists()


def test_update_note_on_malformed_existing_note_succeeds(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    _write_note(vault, "a.md", "---\ntitle: [unterminated\n---\nbody")
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "update-note", {"path": "a.md", "content": "---\ntitle: A\n---\nfixed"}
            )
            assert "fixed" in result.data.content

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_update_note_full_document_replace_round_trips_frontmatter(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    _write_note(vault, "a.md", "---\ntitle: A\n---\noriginal")
    mcp = _mcp_server(db)
    new_content = "---\ntitle: Renamed\ntags:\n  - kept\n---\nnew body"

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "update-note", {"path": "a.md", "content": new_content}
            )
            assert result.data.title == "Renamed"
            assert result.data.tags == ["kept"]
            assert "new body" in result.data.content

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_get_note_on_invalid_path_returns_clear_tool_error(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get-note", {"path": "not-markdown.txt"}, raise_on_error=False
            )
            assert result.is_error
            assert "not a valid note path" in result.content[0].text

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_create_note_on_invalid_path_returns_clear_tool_error(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "create-note",
                {"path": "not-markdown.txt", "content": "x"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "not a valid note path" in result.content[0].text

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()
    assert not (vault / "not-markdown.txt").exists()


def test_update_note_on_invalid_path_returns_clear_tool_error(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "update-note",
                {"path": "not-markdown.txt", "content": "x"},
                raise_on_error=False,
            )
            assert result.is_error
            assert "not a valid note path" in result.content[0].text

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()


def test_create_note_succeeds_even_when_index_sync_fails(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file (source of truth) is already saved by the time the index
    sync runs; a failure there must not turn a successful write into a
    tool-level error -- the index is a disposable, rebuildable cache (see
    SPEC.md and the swallow-and-log comment in _write_and_sync_index)."""
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("index boom")

    monkeypatch.setattr("cerebrum.mcp.notes_tools.upsert_note_in_index", _boom)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "create-note", {"path": "new.md", "content": "hello"}
            )
            assert not result.is_error
            assert "hello" in result.data.content

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()
    assert (vault / "new.md").read_text(encoding="utf-8").endswith("hello\n")


@dataclass
class _RaceState:
    """Bundles one race attempt's shared objects so `_race_create_note`
    only needs three arguments instead of threading each one through
    separately, and so each attempt gets fresh `results`/`results_lock`
    without leaking into the next."""

    mcp: FastMCP
    barrier: threading.Barrier
    results: dict[int, CallToolResult] = field(default_factory=dict)
    results_lock: threading.Lock = field(default_factory=threading.Lock)


def _race_create_note(state: _RaceState, thread_id: int, note_path: str) -> None:
    """Run one side of a create-note race: wait at `state.barrier` so both
    callers issue their `call_tool` at essentially the same instant, then
    record the outcome under `state.results_lock`. A plain top-level
    function (rather than a closure defined inside the per-attempt loop
    below) so each call captures its own arguments by value, not by
    reference to a loop variable a later iteration will reassign."""

    async def run() -> None:
        async with Client(state.mcp) as client:
            state.barrier.wait(timeout=5)
            result = await client.call_tool(
                "create-note",
                {"path": note_path, "content": f"content-{thread_id}"},
                raise_on_error=False,
            )
            with state.results_lock:
                state.results[thread_id] = result

    asyncio.run(run())


def test_create_note_concurrent_calls_for_same_new_path_only_one_succeeds(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent create-note calls racing for the SAME brand-new path
    must never both succeed: exactly one wins, the other gets the
    documented "already exists" ToolError, and the file on disk ends up
    with the winner's content -- never a silent overwrite.

    This is the scenario that exposed the original bug: create_note() used
    to do its existence check via an unlocked read_note() call *before*
    separately calling write_note(). Two threads could both observe
    "nothing here yet" from that unlocked check before either had written
    anything, then both proceed to write -- the second write silently
    clobbering the first with no error raised to either caller, directly
    contradicting the tool's documented contract.

    A `threading.Barrier(2)` makes both threads issue their `call_tool`
    request at essentially the same instant (rather than one strictly
    after the other), which is exactly the interleaving needed to expose
    that race: under the old code, both threads' unlocked pre-checks would
    race to run before either write_note() call. Manually reverting
    create_note()/update_note() to the old unlocked-pre-check
    implementation and running this test reproduces the bug (both calls
    report success, and the file ends up with whichever content happened
    to be written last) -- confirming this test would have caught it.

    Under the fix, write_note()'s own file_lock critical section
    evaluates `must_not_exist` atomically with the write, so the outcome
    is deterministic regardless of scheduling -- this loops several times
    (fresh path per attempt) purely to build confidence that no timing
    window slipped through, not because any single run is expected to be
    flaky.
    """
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    mcp = _mcp_server(db)

    try:
        for attempt in range(15):
            path = f"race-{attempt}.md"
            state = _RaceState(mcp=mcp, barrier=threading.Barrier(2, timeout=5))

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(_race_create_note, state, thread_id, path)
                    for thread_id in (0, 1)
                ]
                for future in futures:
                    future.result(timeout=10)

            successes = [
                tid for tid, result in state.results.items() if not result.is_error
            ]
            failures = [tid for tid, result in state.results.items() if result.is_error]
            assert len(successes) == 1, (
                f"attempt {attempt}: expected exactly one winner, got "
                f"successes={successes} failures={failures}"
            )
            assert len(failures) == 1
            assert "already exists" in state.results[failures[0]].content[0].text

            winner_id = successes[0]
            loser_id = failures[0]
            final_content = (vault / path).read_text(encoding="utf-8")
            assert f"content-{winner_id}" in final_content
            assert f"content-{loser_id}" not in final_content
    finally:
        get_settings.cache_clear()
