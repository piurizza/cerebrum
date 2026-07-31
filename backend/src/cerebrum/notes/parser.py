from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath

import frontmatter
import yaml

from cerebrum.notes.models import ParsedLink, ParsedNote

_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


class InvalidNoteContentError(Exception):
    """Raised when a note's frontmatter can't be parsed (bad YAML, or a
    non-ISO-8601 created/updated value). This is user-editable content --
    a typo made directly in the editor -- not a server bug, so it should
    surface as a 400, never an unhandled 500."""


def resolve_link_target(source_path: str, target: str) -> str | None:
    """Resolve a link target relative to the linking note's directory.

    Returns the normalized vault-relative path if it points at a `.md`
    file, or None if it's external/non-markdown and should be ignored for
    graph purposes. The target need not exist yet (broken links are valid
    data — see SPEC.md).
    """
    if target.startswith(_EXTERNAL_PREFIXES):
        return None

    target = target.split("#", 1)[0]
    if not target.endswith(".md"):
        return None

    source_dir = PurePosixPath(source_path).parent
    combined = source_dir / target

    parts: list[str] = []
    for part in combined.parts:
        if part in (".", ""):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)

    return str(PurePosixPath(*parts)) if parts else None


def extract_links(source_path: str, body: str) -> list[ParsedLink]:
    links: list[ParsedLink] = []
    for match in _LINK_PATTERN.finditer(body):
        link_text, target = match.group(1), match.group(2)
        resolved = resolve_link_target(source_path, target)
        if resolved is not None:
            links.append(ParsedLink(target_path=resolved, link_text=link_text or None))
    return links


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise InvalidNoteContentError(f"invalid date value: {value!r}") from exc


def parse_note(path: str, raw_content: str) -> ParsedNote:
    try:
        post = frontmatter.loads(raw_content)
    except yaml.YAMLError as exc:
        raise InvalidNoteContentError(f"malformed frontmatter: {exc}") from exc
    metadata = post.metadata

    fallback_title = PurePosixPath(path).stem
    title = str(metadata.get("title", fallback_title))
    raw_tags = metadata.get("tags", [])
    tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []

    return ParsedNote(
        title=title,
        tags=tags,
        created=_parse_datetime(metadata.get("created")),
        updated=_parse_datetime(metadata.get("updated")),
        body=post.content,
        links=extract_links(path, post.content),
    )


def render_note(parsed: ParsedNote) -> str:
    metadata: dict[str, object] = {"title": parsed.title, "tags": parsed.tags}
    if parsed.created is not None:
        metadata["created"] = parsed.created.isoformat()
    if parsed.updated is not None:
        metadata["updated"] = parsed.updated.isoformat()

    post = frontmatter.Post(parsed.body)
    post.metadata = metadata
    return str(frontmatter.dumps(post))
