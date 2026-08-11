from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class NoteMeta(BaseModel):
    path: str
    title: str
    tags: list[str]
    created: datetime | None
    updated: datetime | None


class Note(NoteMeta):
    content: str


class ParsedLink(BaseModel):
    target_path: str
    link_text: str | None


class ParsedTask(BaseModel):
    line: int
    checked: bool
    text: str


class ParsedNote(BaseModel):
    title: str
    tags: list[str]
    created: datetime | None
    updated: datetime | None
    body: str
    links: list[ParsedLink]
    tasks: list[ParsedTask]
