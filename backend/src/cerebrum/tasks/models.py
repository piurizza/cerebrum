from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, model_validator

from cerebrum.notes.models import Note

_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_iso_day(value: object) -> date:
    """A calendar day written exactly as `YYYY-MM-DD`. Pydantic's own date
    parsing also takes timestamps and other ISO forms, and a day becomes
    part of a note path, so only this one form is let through."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DAY.fullmatch(value):
        raise ValueError("must be a date written as YYYY-MM-DD")
    return date.fromisoformat(value)


IsoDay = Annotated[date, BeforeValidator(parse_iso_day)]


class TaskItem(BaseModel):
    path: str
    title: str
    # The task's 1-based line in the file, frontmatter included.
    line: int
    # Without the done marker, which `done_date` carries instead.
    text: str
    # The note's tags.
    tags: list[str]
    done: bool
    done_date: date | None


class AddTaskRequest(BaseModel):
    text: str
    # The day whose daily note the task goes to: the client's today.
    date: IsoDay
    # The heading text, without `# `, for a daily note that doesn't exist
    # yet; ignored when it does. Left out, an English long date is used.
    heading: str | None = None


class SetTaskDoneRequest(BaseModel):
    path: str
    line: int
    # The task's text as the list returned it, without a done marker.
    text: str
    done: bool
    # The day a tick records in its done marker: the client's today.
    # Needed to tick, ignored when unticking.
    date: IsoDay | None = None

    @model_validator(mode="after")
    def _tick_needs_a_date(self) -> Self:
        if self.done and self.date is None:
            raise ValueError("date is required to tick a task")
        return self


class TaskWriteResponse(BaseModel):
    """The note as it is after the write, and the task it wrote."""

    note: Note
    task: TaskItem
