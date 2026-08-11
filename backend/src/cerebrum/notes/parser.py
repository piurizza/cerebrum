from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import PurePosixPath

import frontmatter
import yaml

from cerebrum.notes.models import ParsedLink, ParsedNote, ParsedTask

_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")
_TASK_LINE_PATTERN = re.compile(r"^[ \t]*[-*+] \[([ xX])\] (.*)$")
_FENCE_PATTERN = re.compile(r"^[ \t]*(?:```|~~~)")


class InvalidNoteContentError(Exception):
    """Raised when a note's frontmatter can't be parsed (bad YAML, or a
    non-ISO-8601 created/updated value). This is user-editable content --
    a typo made directly in the editor -- not a server bug, so it should
    surface as a 400, never an unhandled 500."""


def _normalize(path: PurePosixPath) -> str | None:
    """Collapse `.`/`..`/empty segments in a combined (possibly relative)
    path down to a normalized vault-relative path string."""
    parts: list[str] = []
    for part in path.parts:
        if part in (".", ""):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return str(PurePosixPath(*parts)) if parts else None


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
    return _normalize(source_dir / target)


def extract_links(source_path: str, body: str) -> list[ParsedLink]:
    links: list[ParsedLink] = []
    for match in _LINK_PATTERN.finditer(body):
        link_text, target = match.group(1), match.group(2)
        resolved = resolve_link_target(source_path, target)
        if resolved is not None:
            links.append(ParsedLink(target_path=resolved, link_text=link_text or None))
    return links


def extract_tasks(body: str) -> list[ParsedTask]:
    """Extract every open/closed markdown checkbox line from `body`,
    skipping any that fall inside a fenced (```/~~~) code block -- a note
    can legitimately document checkbox syntax as an example, and that
    example text is not a real task. This needs a per-line scan with
    fence-tracking state, unlike `extract_links`'s single whole-body
    `finditer`: a plain `re.MULTILINE` pattern has no way to know whether
    the current line is inside a fence.
    """
    tasks: list[ParsedTask] = []
    in_fence = False
    for line_number, line in enumerate(body.splitlines(), start=1):
        if _FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _TASK_LINE_PATTERN.match(line)
        if match:
            tasks.append(
                ParsedTask(
                    line=line_number,
                    checked=match.group(1).lower() == "x",
                    text=match.group(2).rstrip(),
                )
            )
    return tasks


def _rewrite_link_targets(body: str, resolver: Callable[[str], str | None]) -> str:
    """Replace each markdown link's target text via `resolver`.

    `resolver` receives the raw target string (e.g. `"other.md#section"`)
    and returns the replacement raw target string, or None to leave that
    link untouched.
    """

    def _replace(match: re.Match[str]) -> str:
        link_text, target = match.group(1), match.group(2)
        replacement = resolver(target)
        if replacement is None:
            return match.group(0)
        return f"[{link_text}]({replacement})"

    return _LINK_PATTERN.sub(_replace, body)


def _relative_link_text(
    base_dir: PurePosixPath, absolute_target: str, fragment: str
) -> str:
    relative = posixpath.relpath(absolute_target, start=str(base_dir))
    return f"{relative}#{fragment}" if fragment else relative


def rebase_links(body: str, old_source_path: str, new_source_path: str) -> str:
    """Rewrite this note's own outgoing relative links so they still
    resolve to the same absolute targets after the note itself moves
    from `old_source_path` to `new_source_path`.
    """
    old_dir = PurePosixPath(old_source_path).parent
    new_dir = PurePosixPath(new_source_path).parent
    if old_dir == new_dir:
        return body

    def resolver(target: str) -> str | None:
        if target.startswith(_EXTERNAL_PREFIXES):
            return None
        path_part, _, fragment = target.partition("#")
        if not path_part.endswith(".md"):
            return None
        absolute = _normalize(old_dir / path_part)
        if absolute is None:
            return None
        return _relative_link_text(new_dir, absolute, fragment)

    return _rewrite_link_targets(body, resolver)


def retarget_links(
    body: str, source_path: str, old_target: str, new_target: str
) -> str:
    """Rewrite any link in this note that currently resolves to
    `old_target` so it instead resolves to `new_target` (used when
    ANOTHER note moves from `old_target` to `new_target`).
    """
    source_dir = PurePosixPath(source_path).parent

    def resolver(target: str) -> str | None:
        if target.startswith(_EXTERNAL_PREFIXES):
            return None
        path_part, _, fragment = target.partition("#")
        if not path_part.endswith(".md"):
            return None
        if _normalize(source_dir / path_part) != old_target:
            return None
        return _relative_link_text(source_dir, new_target, fragment)

    return _rewrite_link_targets(body, resolver)


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
        tasks=extract_tasks(post.content),
    )


def render_note(parsed: ParsedNote) -> str:
    metadata: dict[str, object] = {"title": parsed.title, "tags": parsed.tags}
    if parsed.created is not None:
        metadata["created"] = parsed.created.isoformat()
    if parsed.updated is not None:
        metadata["updated"] = parsed.updated.isoformat()

    post = frontmatter.Post(parsed.body)
    post.metadata = metadata
    # frontmatter.dumps() never leaves a trailing newline (it strips the
    # body's trailing whitespace outright) -- for an empty/whitespace-only
    # body this means NO newline at all after the closing "---", so any
    # later edit appending text right at the end of the file merges into
    # the delimiter line and breaks frontmatter detection on the next
    # parse. Always end with exactly one newline instead.
    return f"{frontmatter.dumps(post)}\n"
