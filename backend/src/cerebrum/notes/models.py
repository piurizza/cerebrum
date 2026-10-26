from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NoteMeta(BaseModel):
    path: str
    title: str
    tags: list[str]
    created: datetime | None
    updated: datetime | None


class Note(NoteMeta):
    content: str
    # The sha256 of the file's raw bytes as they are on disk. A client
    # sends it back with a save so a file that changed since it loaded
    # the note is refused rather than overwritten.
    version: str


class ParsedLink(BaseModel):
    target_path: str
    link_text: str | None


class ParsedWikilink(BaseModel):
    """A `[[wikilink]]` to a note, as written -- resolved when read, since
    what it points at depends on the rest of the vault."""

    target: str
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
    wikilinks: list[ParsedWikilink] = Field(default_factory=list)
    # Frontmatter keys Cerebrum doesn't manage (e.g. Obsidian's `aliases`,
    # `cssclasses`, custom properties), written back unchanged on save.
    extra_metadata: dict[str, object] = Field(default_factory=dict)
    # Whether `title` came from the file's frontmatter rather than the
    # file-name fallback. A note without a `title` key keeps having none,
    # so its displayed title keeps following the file name.
    title_in_frontmatter: bool = True
