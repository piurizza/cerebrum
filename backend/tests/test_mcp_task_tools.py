"""The MCP task tools: list-tasks, add-task and set-task-done."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult

from cerebrum.index.indexer import upsert_note
from cerebrum.mcp import task_tools
from cerebrum.settings import get_settings
from tests.test_mcp_tools import _call, _mcp_server, _write_note


def test_read_only_vault_still_lists_tasks(
    vault: Path,
    db: sqlite3.Connection,
    read_only_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del read_only_env
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    get_settings.cache_clear()
    _write_note(vault, "a.md", "- [ ] Water the herbs\n")
    upsert_note(db, vault, "a.md")

    listed = _call(_mcp_server(db), "list-tasks", {})

    assert [task["text"] for task in listed.structured_content["tasks"]] == [
        "Water the herbs"
    ]


@pytest.fixture
def task_mcp(
    vault: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastMCP]:
    """The MCP server over `vault`, with "now" fixed at 23:30 UTC on
    26 October 2026 and the vault's time zone UTC unless a test sets
    another."""
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    monkeypatch.setenv("CEREBRUM_TIMEZONE", "UTC")
    monkeypatch.setattr(
        task_tools, "_now", lambda: datetime(2026, 10, 26, 23, 30, tzinfo=UTC)
    )
    get_settings.cache_clear()
    yield _mcp_server(db)
    get_settings.cache_clear()


def _indexed(vault: Path, db: sqlite3.Connection, path: str, content: str) -> None:
    _write_note(vault, path, content)
    upsert_note(db, vault, path)


def _tasks(result: CallToolResult) -> list[dict[str, object]]:
    assert result.structured_content is not None
    tasks: list[dict[str, object]] = result.structured_content["tasks"]
    return tasks


def test_add_task_without_a_date_uses_today_in_the_vault_time_zone(
    vault: Path, task_mcp: FastMCP, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 23:30 UTC on the 26th is already the 27th in Rome.
    monkeypatch.setenv("CEREBRUM_TIMEZONE", "Europe/Rome")
    get_settings.cache_clear()

    result = _call(task_mcp, "add-task", {"text": "Order timber"})

    assert result.structured_content is not None
    assert result.structured_content["date_used"] == "2026-10-27"
    written = (vault / "daily" / "2026-10-27.md").read_text(encoding="utf-8")
    assert written.endswith("\n# Tuesday, 27 October 2026\n\n- [ ] Order timber\n")
    task = result.structured_content["task"]
    assert task["path"] == "daily/2026-10-27.md"
    assert task["line"] == written.count("\n")
    assert task["text"] == "Order timber"
    assert task["done"] is False


def test_add_task_appends_to_the_given_days_note_and_is_listed(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(vault, db, "daily/2026-10-20.md", "# Mine\n\n- [ ] First\n")

    result = _call(task_mcp, "add-task", {"text": "Second", "date": "2026-10-20"})

    assert result.structured_content is not None
    assert result.structured_content["date_used"] == "2026-10-20"
    assert (vault / "daily" / "2026-10-20.md").read_text(encoding="utf-8") == (
        "# Mine\n\n- [ ] First\n- [ ] Second\n"
    )
    listed = _tasks(_call(task_mcp, "list-tasks", {}))
    assert [(task["text"], task["line"]) for task in listed] == [
        ("First", 3),
        ("Second", 4),
    ]


@pytest.mark.parametrize(
    ("args", "expected_error"),
    [
        ({"text": "  "}, "A task needs some text"),
        ({"text": "x", "date": "2026-10-26T10:00"}, "YYYY-MM-DD"),
        ({"text": "x", "date": "26/10/2026"}, "YYYY-MM-DD"),
    ],
)
def test_add_task_refuses_empty_text_or_a_loose_date(
    vault: Path, task_mcp: FastMCP, args: dict[str, object], expected_error: str
) -> None:
    result = _call(task_mcp, "add-task", args, raise_on_error=False)

    assert result.is_error
    assert expected_error in result.content[0].text
    assert not (vault / "daily").exists()


def test_set_task_done_ticks_with_today_and_unticks(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(vault, db, "a.md", "# A\n- [ ] Water the herbs\n")
    locator = {"path": "a.md", "line": 2, "text": "Water the herbs"}

    ticked = _call(task_mcp, "set-task-done", {**locator, "done": True})

    assert (vault / "a.md").read_text(encoding="utf-8") == (
        "# A\n- [x] Water the herbs ✅ 2026-10-26\n"
    )
    assert ticked.structured_content is not None
    assert ticked.structured_content["date_used"] == "2026-10-26"
    assert ticked.structured_content["task"]["done_date"] == "2026-10-26"
    assert _tasks(_call(task_mcp, "list-tasks", {})) == []

    unticked = _call(task_mcp, "set-task-done", {**locator, "done": False})

    assert (vault / "a.md").read_text(
        encoding="utf-8"
    ) == "# A\n- [ ] Water the herbs\n"
    assert unticked.structured_content is not None
    assert unticked.structured_content["date_used"] is None
    assert unticked.structured_content["task"]["done"] is False
    assert [task["text"] for task in _tasks(_call(task_mcp, "list-tasks", {}))] == [
        "Water the herbs"
    ]


def test_set_task_done_records_the_date_given(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(vault, db, "a.md", "- [ ] Call the plumber\n")

    result = _call(
        task_mcp,
        "set-task-done",
        {
            "path": "a.md",
            "line": 1,
            "text": "Call the plumber",
            "done": True,
            "date": "2026-10-24",
        },
    )

    assert result.structured_content is not None
    assert result.structured_content["date_used"] == "2026-10-24"
    assert "✅ 2026-10-24" in (vault / "a.md").read_text(encoding="utf-8")


def test_set_task_done_on_a_changed_line_fails_naming_the_note(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(vault, db, "a.md", "- [ ] Call the plumber\n")
    # Edited behind the index's back: the task moved down a line.
    _write_note(vault, "a.md", "- [ ] Something else\n- [ ] Call the plumber\n")
    before = (vault / "a.md").read_text(encoding="utf-8")

    result = _call(
        task_mcp,
        "set-task-done",
        {"path": "a.md", "line": 1, "text": "Call the plumber", "done": True},
        raise_on_error=False,
    )

    assert result.is_error
    message = result.content[0].text
    assert "'a.md' changed" in message
    assert "list-tasks" in message
    assert (vault / "a.md").read_text(encoding="utf-8") == before
    # The index was brought up to date, so listing again finds it.
    listed = _tasks(_call(task_mcp, "list-tasks", {}))
    assert [(task["line"], task["text"]) for task in listed] == [
        (1, "Something else"),
        (2, "Call the plumber"),
    ]


def test_set_task_done_on_a_deleted_note_fails_and_drops_its_tasks(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(vault, db, "a.md", "- [ ] Call the plumber\n")
    (vault / "a.md").unlink()

    result = _call(
        task_mcp,
        "set-task-done",
        {"path": "a.md", "line": 1, "text": "Call the plumber", "done": True},
        raise_on_error=False,
    )

    assert result.is_error
    assert "a.md" in result.content[0].text
    assert "list-tasks" in result.content[0].text
    assert _tasks(_call(task_mcp, "list-tasks", {})) == []


def test_list_done_tasks_covers_today_and_the_days_before_it(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(
        vault,
        db,
        "a.md",
        "# A\n"
        "- [x] Too old ✅ 2026-10-19\n"
        "- [x] Oldest kept ✅ 2026-10-20\n"
        "- [x] Undated\n"
        "- [x] Today ✅ 2026-10-26\n"
        "- [ ] Still open\n",
    )

    result = _call(task_mcp, "list-tasks", {"status": "done", "days": 7})

    assert result.structured_content is not None
    assert result.structured_content["date_used"] == "2026-10-26"
    assert result.structured_content["since"] == "2026-10-20"
    assert [
        (task["path"], task["line"], task["text"], task["done"], task["done_date"])
        for task in _tasks(result)
    ] == [
        ("a.md", 5, "Today", True, "2026-10-26"),
        ("a.md", 3, "Oldest kept", True, "2026-10-20"),
    ]


def test_list_open_tasks_does_not_use_a_date(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(vault, db, "a.md", "---\ntitle: Chores\n---\n- [ ] Mow\n")

    result = _call(task_mcp, "list-tasks", {})

    assert result.structured_content == {
        "tasks": [
            {
                "path": "a.md",
                "title": "Chores",
                "line": 4,
                "text": "Mow",
                "tags": [],
                "done": False,
                "done_date": None,
            }
        ],
        "total": 1,
        "date_used": None,
        "since": None,
    }


def test_list_tasks_filters_by_tags_folder_and_words(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(
        vault,
        db,
        "garden/beds.md",
        "---\ntags: [Garden/Herbs]\n---\n- [ ] Water the herbs\n- [ ] Weed the beds\n",
    )
    _indexed(
        vault,
        db,
        "garden/shed.md",
        "---\ntags: [garden, wip]\n---\n- [ ] Order timber for the shed\n",
    )
    _indexed(
        vault, db, "gardening.md", "---\ntags: [garden]\n---\n- [ ] Water the lawn\n"
    )
    _indexed(vault, db, "home.md", "- [ ] Water the plants\n")

    def texts(args: dict[str, object]) -> list[object]:
        return [task["text"] for task in _tasks(_call(task_mcp, "list-tasks", args))]

    # Nested tags match and case is ignored, as in search.
    assert texts({"tags": ["#garden"]}) == [
        "Water the herbs",
        "Weed the beds",
        "Order timber for the shed",
        "Water the lawn",
    ]
    assert texts({"tags": ["garden/herbs"]}) == ["Water the herbs", "Weed the beds"]
    # Several tags must all match; a leading `-` drops a tag.
    assert texts({"tags": ["garden", "WIP"]}) == ["Order timber for the shed"]
    assert texts({"tags": ["garden", "-#wip"]}) == [
        "Water the herbs",
        "Weed the beds",
        "Water the lawn",
    ]
    # A folder includes its subfolders but not a sibling sharing its name.
    assert texts({"folder": "/garden/"}) == [
        "Water the herbs",
        "Weed the beds",
        "Order timber for the shed",
    ]
    # Every word must appear in the task text, in any case and order.
    assert texts({"text": "WATER the"}) == [
        "Water the herbs",
        "Water the lawn",
        "Water the plants",
    ]
    assert texts({"text": "herbs water", "folder": "garden"}) == ["Water the herbs"]


def test_list_tasks_limit_keeps_the_first_and_reports_the_total(
    vault: Path, db: sqlite3.Connection, task_mcp: FastMCP
) -> None:
    _indexed(vault, db, "a.md", "- [ ] One\n- [ ] Two\n- [ ] Three\n")

    result = _call(task_mcp, "list-tasks", {"limit": 2})

    assert [task["text"] for task in _tasks(result)] == ["One", "Two"]
    assert result.structured_content is not None
    assert result.structured_content["total"] == 3


@pytest.mark.parametrize("args", [{"limit": 0}, {"days": 0}, {"status": "all"}])
def test_list_tasks_refuses_out_of_range_arguments(
    task_mcp: FastMCP, args: dict[str, object]
) -> None:
    result = _call(task_mcp, "list-tasks", args, raise_on_error=False)

    assert result.is_error


def test_task_writing_tools_say_to_take_the_locator_from_list_tasks(
    task_mcp: FastMCP,
) -> None:
    async def run() -> None:
        async with Client(task_mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            description = tools["set-task-done"].description or ""
            assert description.startswith("Call this to ")
            assert "list-tasks" in description
            assert tools["list-tasks"].annotations is not None
            assert tools["list-tasks"].annotations.readOnlyHint
            assert tools["add-task"].annotations is not None
            assert tools["add-task"].annotations.readOnlyHint is False

    asyncio.run(run())
