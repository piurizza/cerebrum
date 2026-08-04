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
