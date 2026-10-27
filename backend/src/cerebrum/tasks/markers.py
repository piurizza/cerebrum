"""The done marker a ticked task carries, `✅ YYYY-MM-DD`, as the Obsidian
Tasks plugin writes it, so a note's history stays readable in other tools.

This is the one place that reads or writes the marker: the task list, the
tick and untick writes and the MCP tools all go through it, and the
frontend gets the text and the date already split apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# The same task grammar as `_TASK_LINE_PATTERN` in notes/parser.py, with
# the parts a rewrite keeps captured.
_TASK_LINE = re.compile(r"([ \t]*)([-*+]) \[([ xX])\] (.*)")
# A `\r` before the `\n` belongs to the line, so a rewrite keeps it.
_LINE_ENDING = re.compile(r"\r?\n?\Z")
# The lookbehinds let a match start only where a whitespace run starts.
# Without them, a search retries from every space of a long run that ends
# in other text, and each try scans the rest of the run: quadratic time.
# The leftmost match starts at the run's start either way.
_BLOCK_ID = re.compile(r"(?<![ \t])[ \t]+(\^[A-Za-z0-9-]+)\Z")
# `✅`, an optional emoji presentation selector, one or more spaces and a
# date, at the very end of the text once any block id is set aside. Only
# the last marker counts, and one followed by other text is just text.
_DONE_MARKER = re.compile(r"(?<![ \t])[ \t]*✅️? +([0-9]{4}-[0-9]{2}-[0-9]{2})\Z")


@dataclass(frozen=True)
class TaskLine:
    """One task line of a file, split into the parts a rewrite keeps.
    `text` is everything after the checkbox, trailing whitespace removed,
    as the index stores it."""

    indent: str
    bullet: str
    checked: bool
    text: str
    ending: str


@dataclass(frozen=True)
class _TaskText:
    description: str
    done: date | None
    block_id: str


def parse_task_line(line: str) -> TaskLine | None:
    """The task on `line`, or None when it isn't a task line. `line` may
    end with its line ending, which is kept in `ending`."""
    ending = _LINE_ENDING.search(line)
    assert ending is not None  # the pattern matches the empty string
    match = _TASK_LINE.fullmatch(line[: ending.start()])
    if match is None:
        return None
    indent, bullet, state, text = match.groups()
    return TaskLine(indent, bullet, state.lower() == "x", text.rstrip(), ending[0])


def _split_text(text: str) -> _TaskText:
    rest = text.rstrip()
    block_id = ""
    block = _BLOCK_ID.search(rest)
    if block is not None:
        block_id, rest = f" {block[1]}", rest[: block.start()]
    marker = _DONE_MARKER.search(rest)
    if marker is not None:
        try:
            # fromisoformat rejects impossible dates like 2026-02-30, which
            # leaves the would-be marker as part of the text.
            done = date.fromisoformat(marker[1])
        except ValueError:
            pass
        else:
            return _TaskText(rest[: marker.start()], done, block_id)
    return _TaskText(rest, None, block_id)


def split_done_marker(text: str) -> tuple[str, date | None]:
    """A task's text without its done marker, and the marker's date.
    Text without a valid marker comes back as it is, with no date. A block
    id after the marker stays at the end of the text."""
    parts = _split_text(text)
    if parts.done is None:
        return text, None
    return f"{parts.description}{parts.block_id}", parts.done


def _rebuild(line: str, checked: bool, done: date | None) -> str:
    task = parse_task_line(line)
    if task is None:
        raise ValueError(f"not a task line: {line!r}")
    parts = _split_text(task.text)
    pieces = [parts.description]
    if done is not None:
        pieces.append(f"✅ {done.isoformat()}")
    text = " ".join(piece for piece in pieces if piece)
    box = "x" if checked else " "
    return f"{task.indent}{task.bullet} [{box}] {text}{parts.block_id}{task.ending}"


def tick_line(line: str, done: date) -> str:
    """`line` ticked on `done`: a lowercase `x` and a done marker for that
    date, replacing any marker already there. The indentation, bullet,
    block id and line ending stay as they were. Raises ValueError when
    `line` isn't a task line."""
    return _rebuild(line, checked=True, done=done)


def untick_line(line: str) -> str:
    """`line` unticked: an empty checkbox and no done marker. The
    indentation, bullet, block id and line ending stay as they were.
    Raises ValueError when `line` isn't a task line."""
    return _rebuild(line, checked=False, done=None)
