from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path

from cerebrum.index.db import write_lock
from cerebrum.notes.models import Note
from cerebrum.notes.parser import extract_tasks
from cerebrum.notes.service import edit_note_text, normalize_newlines
from cerebrum.tasks.markers import (
    parse_task_line,
    split_done_marker,
    tick_line,
    untick_line,
)
from cerebrum.tasks.models import TaskItem

# A checkbox typed into the add box along with the text.
_LEADING_CHECKBOX = re.compile(r"(?:- )?\[ \]\s*")

_CHANGED = "The note changed since the task was loaded"


class EmptyTaskTextError(ValueError):
    """The text given for a new task is empty once cleaned."""


class TaskConflictError(Exception):
    """The task isn't where the caller said it was, or can't be written
    there: the note changed since the task was listed. `add_task` raises
    it too when the daily note ends inside an unclosed code block, where
    an appended line wouldn't be a task."""


def list_open_tasks(conn: sqlite3.Connection, templates_folder: str) -> list[TaskItem]:
    """Every unticked task, by note path and line, leaving out notes under
    `templates_folder`."""
    return _list_tasks(conn, checked=False, templates_folder=templates_folder)


def list_done_tasks(
    conn: sqlite3.Connection, since: date, templates_folder: str
) -> list[TaskItem]:
    """Every task ticked with a done marker dated `since` or later, newest
    first, leaving out notes under `templates_folder`. A task ticked
    without a done marker has no date to list it under."""
    tasks = _list_tasks(
        conn, checked=True, templates_folder=templates_folder, min_done=since
    )
    # Stable, so a day's tasks keep their path and line order.
    tasks.sort(key=lambda task: task.done_date or since, reverse=True)
    return tasks


def _list_tasks(
    conn: sqlite3.Connection,
    *,
    checked: bool,
    templates_folder: str,
    min_done: date | None = None,
) -> list[TaskItem]:
    """The tasks the index holds in state `checked`, by note path and line,
    leaving out notes under `templates_folder`. `min_done` is for ticked
    tasks: with it, only those done on that day or later, so a task
    without a done marker is left out."""
    # write_lock: this read races the filesystem watcher/backstop rescan's
    # sustained writes against the same shared connection -- see
    # index/db.py's write_lock docstring for the exact hazard
    # (sqlite3.InterfaceError) an unlocked read can hit here (mirrors
    # graph/service.py's identical reasoning for its own reads).
    with write_lock:
        rows = conn.execute(
            """
            SELECT t.source_path, n.title, n.tags, t.line, t.text
            FROM tasks t
            JOIN notes n ON n.path = t.source_path
            WHERE t.checked = ?
            ORDER BY n.path, t.line
            """,
            (checked,),
        ).fetchall()
    templates_prefix = f"{templates_folder}/"
    tasks: list[TaskItem] = []
    # The cheap rejections come first, so a skipped row's tags are never
    # parsed.
    for row in rows:
        if row["source_path"].startswith(templates_prefix):
            continue
        text, marker_date = split_done_marker(row["text"])
        if min_done is not None and (marker_date is None or marker_date < min_done):
            continue
        tasks.append(
            _task_item(
                path=row["source_path"],
                title=row["title"],
                tags=json.loads(row["tags"]),
                line=row["line"],
                checked=checked,
                text=text,
                marker_date=marker_date,
            )
        )
    return tasks


# The arguments are the task's fields, each named at every call site.
def _task_item(  # pylint: disable=too-many-arguments
    *,
    path: str,
    title: str,
    tags: list[str],
    line: int,
    checked: bool,
    text: str,
    marker_date: date | None,
) -> TaskItem:
    """A task as the lists return it, from its text as the index stores
    it split by `split_done_marker`: `text` without the done marker and
    `marker_date` the marker's date. Only a ticked task has a done date; a
    marker left on an open one is still dropped from the text, as a tick
    replaces it anyway."""
    return TaskItem(
        path=path,
        title=title,
        tags=tags,
        line=line,
        text=text,
        done=checked,
        done_date=marker_date if checked else None,
    )


def default_daily_heading(day: date) -> str:
    """The heading of a daily note created where no browser supplies one,
    such as over MCP: an English long date, e.g. "Monday, 26 October
    2026". Built by hand, as `%-d` isn't portable."""
    return f"{day:%A}, {day.day} {day:%B %Y}"


def daily_heading_line(heading: str) -> str:
    """The `# <heading>` line a new daily note starts with, from heading
    text that may hold line breaks."""
    return f"# {_one_line(heading)}"


def daily_note_body(heading: str) -> str:
    """A new daily note's body, the same shape the Today button saves
    (`getDailyNoteDefaultBody` in frontend/src/lib/dailyNote.ts)."""
    return f"{daily_heading_line(heading)}\n\n"


def daily_note_path(daily_note_folder: str, day: date) -> str:
    """The daily note for `day`, as `getTodayNotePath` in
    frontend/src/lib/dailyNote.ts builds it."""
    return f"{daily_note_folder}/{day.isoformat()}.md"


def _one_line(text: str) -> str:
    """`text` with every line break and control character turned into a
    space, trimmed: it goes into the file as part of a single line."""
    return "".join(
        " " if unicodedata.category(char) in ("Cc", "Zl", "Zp") else char
        for char in text
    ).strip()


def clean_task_text(text: str) -> str:
    """Typed text as one task line's text: on one line, trimmed, and
    without a checkbox typed in front of it. Raises EmptyTaskTextError
    when nothing is left."""
    cleaned = _one_line(text)
    checkbox = _LEADING_CHECKBOX.match(cleaned)
    if checkbox is not None:
        cleaned = cleaned[checkbox.end() :]
    if not cleaned:
        raise EmptyTaskTextError("A task needs some text")
    return cleaned


def add_task(
    vault_root: Path,
    daily_note_folder: str,
    day: date,
    text: str,
    heading: str | None,
) -> tuple[Note, TaskItem]:
    """Append `- [ ] <text>` to `day`'s daily note, creating the note
    first when it doesn't exist, with `heading` as its heading, or the
    English default when that is blank. The rest of the file is left byte
    for byte as it is. Raises EmptyTaskTextError for text that is empty
    once cleaned."""
    task_text = clean_task_text(text)
    path = daily_note_path(daily_note_folder, day)
    body = daily_note_body(_one_line(heading or "") or default_daily_heading(day))
    task_line = 0

    def append(content: str) -> str:
        nonlocal task_line
        new_content = _append_task_line(content, f"- [ ] {task_text}")
        # The line the indexer will list it on: it reads the file with
        # universal newlines, so count the way it does.
        task_line = normalize_newlines(new_content).count("\n")
        listed = {
            task.line: task for task in extract_tasks(normalize_newlines(new_content))
        }
        added = listed.get(task_line)
        if added is None or added.text != task_text:
            # Only an unclosed code block at the end of the note does this.
            raise TaskConflictError(
                f"The task can't be added: {path} ends inside a code block"
            )
        return new_content

    note = edit_note_text(vault_root, path, append, create_with=body)
    listed_text, marker_date = split_done_marker(task_text)
    return note, _task_item(
        path=path,
        title=note.title,
        tags=note.tags,
        line=task_line,
        checked=False,
        text=listed_text,
        marker_date=marker_date,
    )


def _append_task_line(content: str, line: str) -> str:
    """`content` with `line` appended: right after a task, so a list stays
    one list, and after a blank line otherwise, so the task doesn't run
    into a paragraph. The file's line ending (LF or CRLF) is kept."""
    last_break = content.rfind("\n")
    ending = "\r\n" if content[last_break - 1 : last_break] == "\r" else "\n"
    if content and not content.endswith("\n"):
        content += ending
    lines = content.split("\n")[:-1]
    last = next((text for text in reversed(lines) if text.strip()), None)
    needs_blank_line = (
        last is not None and parse_task_line(last) is None and lines[-1].strip() != ""
    )
    return f"{content}{ending if needs_blank_line else ''}{line}{ending}"


# The arguments are the task's identity and the change, each named at
# every call site.
def set_task_done(  # pylint: disable=too-many-arguments
    vault_root: Path,
    path: str,
    line: int,
    text: str,
    *,
    done: bool,
    day: date | None,
) -> tuple[Note, TaskItem]:
    """Tick the task on `line` of `path` with a done marker for `day`, or
    untick it, changing that one line and nothing else in the file.

    The task is found only where the caller says it is: `line` must hold
    a task whose text, without its done marker, is `text`, which may carry
    the marker too (the note preview sends the line as it is). Anything else
    raises TaskConflictError and writes nothing; the task is never looked
    for elsewhere. A task already in the state asked for is left as it is.
    """
    if done and day is None:
        raise ValueError("A tick needs the day it was done")
    if not done:
        day = None
    expected = split_done_marker(text)[0]
    written = ""

    def change(content: str) -> str | None:
        nonlocal written
        lines = content.split("\n")
        # The indexer reads files with universal newlines, so for it a `\r`
        # not followed by `\n` ends a line; split on `\n` alone, it doesn't.
        # One above or on the task's line means the two number lines
        # differently, and the line asked for could hold a different task
        # with the same text. Refused rather than guessed at.
        if not 1 <= line <= len(lines) or any(
            "\r" in earlier.removesuffix("\r") for earlier in lines[:line]
        ):
            raise TaskConflictError(_CHANGED)
        # extract_tasks skips frontmatter and fenced code, as the index does.
        listed = {task.line: task for task in extract_tasks(content)}
        current = listed.get(line)
        if current is None or split_done_marker(current.text)[0] != expected:
            raise TaskConflictError(_CHANGED)
        written = lines[line - 1]
        if current.checked == done:
            return None
        written = tick_line(written, day) if day is not None else untick_line(written)
        lines[line - 1] = written
        return "\n".join(lines)

    note = edit_note_text(vault_root, path, change)
    task = parse_task_line(written)
    assert task is not None  # the line was checked to hold a task
    listed_text, marker_date = split_done_marker(task.text)
    return note, _task_item(
        path=path,
        title=note.title,
        tags=note.tags,
        line=line,
        checked=task.checked,
        text=listed_text,
        marker_date=marker_date,
    )
