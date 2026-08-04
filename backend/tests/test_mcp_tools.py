from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastmcp import Client, FastMCP

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
