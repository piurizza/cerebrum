from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from cerebrum.index.indexer import sync_note_in_index
from cerebrum.index.search_query import ParsedQuery, normalize_tag
from cerebrum.mcp.context import INDEX_LAG_WARNING, get_db
from cerebrum.notes.parser import InvalidNoteContentError
from cerebrum.notes.service import InvalidNotePathError, NoteNotFoundError
from cerebrum.settings import get_settings
from cerebrum.tasks.models import TaskItem, parse_iso_day
from cerebrum.tasks.service import (
    EmptyTaskTextError,
    TaskConflictError,
    add_task,
    daily_note_path,
    list_done_tasks,
    list_open_tasks,
    set_task_done,
)

_READ_ONLY_ANNOTATIONS = {"readOnlyHint": True, "idempotentHint": True}
_ADD_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
}
_SET_DONE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
}
_DATE_GUIDANCE = (
    "`date` is the user's today as YYYY-MM-DD; pass it when you know it. "
    "Without it, today in the vault's time zone is used. The result's "
    "date_used says which day was used."
)


class TaskList(BaseModel):
    tasks: list[TaskItem]
    # How many tasks matched before `limit` cut the list short.
    total: int
    # Done lists only: the today the window ends on, and its first day.
    date_used: date | None
    since: date | None


class TaskWrite(BaseModel):
    task: TaskItem
    # The day the task was added under, or the tick recorded; None for an
    # untick.
    date_used: date | None


def _now() -> datetime:
    # Its own function so tests can stand in a fixed moment.
    return datetime.now(UTC)


def _day(raw: str | None) -> date:
    """The day an assistant gave, or today in the vault's time zone."""
    if raw is None:
        return get_settings().vault_date(_now())
    try:
        return parse_iso_day(raw)
    except ValueError as exc:
        raise ToolError(f"date {raw!r} must be a date written as YYYY-MM-DD") from exc


def register_task_tools(mcp: FastMCP, app: FastAPI) -> None:
    """Register the task tools against `mcp`, closing over `app` the way
    `register_notes_tools` does. A read-only vault gets only list-tasks."""
    # Read once at registration: changing it needs a restart.
    _register_task_read_tools(mcp, app)
    if not get_settings().cerebrum_vault_read_only:
        _register_task_write_tools(mcp, app)


def _register_task_read_tools(mcp: FastMCP, app: FastAPI) -> None:
    @mcp.tool(
        name="list-tasks",
        description=(
            "Call this to see the vault's tasks (markdown `- [ ]` checkboxes) "
            "before ticking one with set-task-done. `status` 'open' lists "
            "every unticked task; 'done' lists tasks ticked in the last "
            "`days` days, today included, newest first. Narrow with `tags` "
            "(the note's tags: 'garden' also matches 'garden/herbs', '-wip' "
            "drops a tag, all must match, case is ignored), `folder` "
            "(subfolders included) and `text` (every word must appear in the "
            "task, any case). Returns each task's path, line, text, done and "
            "done_date, the note's title and tags, and the total before "
            f"`limit`. {INDEX_LAG_WARNING}"
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    # The arguments are the filters the tool offers, each optional.
    def list_tasks(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        status: Literal["open", "done"] = "open",
        # Ten years at most, which also keeps the window's first day a date.
        days: Annotated[int, Field(ge=1, le=3650)] = 14,
        tags: list[str] | None = None,
        folder: str = "",
        text: str = "",
        limit: Annotated[int, Field(ge=1)] = 100,
    ) -> TaskList:
        templates_folder = get_settings().cerebrum_templates_folder
        today: date | None = None
        since: date | None = None
        if status == "done":
            today = _day(None)
            since = today - timedelta(days=days - 1)
            tasks = list_done_tasks(get_db(app), since, templates_folder)
        else:
            tasks = list_open_tasks(get_db(app), templates_folder)
        matching = _filter(tasks, tags or [], folder, text)
        return TaskList(
            tasks=matching[:limit],
            total=len(matching),
            date_used=today,
            since=since,
        )


def _filter(
    tasks: list[TaskItem], tags: list[str], folder: str, text: str
) -> list[TaskItem]:
    """The tasks the filters keep: tags matched against the note's tags
    the way search matches them, a folder with its subfolders, and words
    that must all appear in the task's text."""
    include: list[str] = []
    exclude: list[str] = []
    for raw in tags:
        tag = raw.strip()
        excluded = tag.startswith("-")
        tag = normalize_tag(tag.removeprefix("-"))
        if tag:
            (exclude if excluded else include).append(tag)
    tag_query = ParsedQuery(text="", include=tuple(include), exclude=tuple(exclude))
    folder = folder.strip().strip("/")
    words = text.lower().split()
    return [
        task
        for task in tasks
        if tag_query.matches(task.tags)
        and (not folder or task.path.startswith(f"{folder}/"))
        and all(word in task.text.lower() for word in words)
    ]


def _register_task_write_tools(mcp: FastMCP, app: FastAPI) -> None:
    @mcp.tool(
        name="add-task",
        description=(
            "Call this to add a task to the end of a day's daily note, "
            "creating the note when it doesn't exist yet. `text` is the task "
            f"on one line, without the `- [ ]`. {_DATE_GUIDANCE} Returns the "
            "new task with its path and line."
        ),
        annotations=_ADD_ANNOTATIONS,
    )
    def add_task_tool(text: str, date: str | None = None) -> TaskWrite:
        settings = get_settings()
        day = _day(date)
        path = daily_note_path(settings.cerebrum_daily_note_folder, day)
        with _refusals_as_tool_errors(path):
            note, task = add_task(
                settings.cerebrum_vault_path,
                settings.cerebrum_daily_note_folder,
                day,
                text,
                heading=None,
            )
        _sync_index(app, note.path)
        return TaskWrite(task=task, date_used=day)

    @mcp.tool(
        name="set-task-done",
        description=(
            "Call this to tick a task (`done` true) or untick it (false). "
            "Take `path`, `line` and `text` exactly as list-tasks returned "
            "them: the task is changed only if that line still holds that "
            "text, and nothing else in the note is touched. A tick adds a "
            f"done date to the line. {_DATE_GUIDANCE} Fails without writing "
            "if the note changed since you listed it; call list-tasks again "
            "then."
        ),
        annotations=_SET_DONE_ANNOTATIONS,
    )
    # The arguments are the task's locator and the change.
    def set_task_done_tool(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        path: str, line: int, text: str, done: bool, date: str | None = None
    ) -> TaskWrite:
        day = _day(date) if done else None
        with _refusals_as_tool_errors(path):
            try:
                _, task = set_task_done(
                    get_settings().cerebrum_vault_path,
                    path,
                    line,
                    text,
                    done=done,
                    day=day,
                )
            # The index listed the task where it no longer is: bring the
            # note's rows up to date, so list-tasks is right next time.
            except TaskConflictError as exc:
                _sync_index(app, path)
                raise ToolError(
                    f"'{path}' changed since its tasks were listed, so nothing "
                    "was written; call list-tasks again and use the line and "
                    "text it returns now"
                ) from exc
            except NoteNotFoundError as exc:
                _sync_index(app, path)
                raise ToolError(
                    f"No note exists at '{path}' any more; call list-tasks again"
                ) from exc
        _sync_index(app, path)
        return TaskWrite(task=task, date_used=day)


@contextmanager
def _refusals_as_tool_errors(path: str) -> Iterator[None]:
    """A task write's refusals about `path` as ToolErrors."""
    try:
        yield
    except (TaskConflictError, EmptyTaskTextError) as exc:
        raise ToolError(str(exc)) from exc
    except InvalidNotePathError as exc:
        raise ToolError(f"'{path}' is not a valid note path") from exc
    except InvalidNoteContentError as exc:
        raise ToolError(str(exc)) from exc


def _sync_index(app: FastAPI, path: str) -> None:
    """Re-read `path` into the index, or drop it when the file is gone;
    an index failure is logged, not reported (see `sync_note_in_index`)."""
    sync_note_in_index(get_db(app), get_settings().cerebrum_vault_path, path)
