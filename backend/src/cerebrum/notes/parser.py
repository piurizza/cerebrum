from __future__ import annotations

import bisect
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

import frontmatter
import yaml

from cerebrum.notes.code_regions import code_ranges, fence_states
from cerebrum.notes.models import (
    ParsedLink,
    ParsedNote,
    ParsedTask,
    ParsedWikilink,
)
from cerebrum.notes.wikilinks import (
    NoteMove,
    extract_wikilinks,
    is_hidden_path,
    is_writable_target,
)

# A markdown link: `[text](destination "optional title")`. As in CommonMark,
# the destination is either wrapped in angle brackets, where it may hold
# spaces, or a run of non-space characters, where a space is written `%20`.
_LINK_PATTERN = re.compile(
    r"\[([^\]]*)\]\(\s*(<[^<>\n]*>|[^)\s<][^)\s]*)"
    r"(\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)"
)
_PERCENT_ESCAPES = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")
# Characters percent-encoded when Cerebrum writes a link target: the ones
# that would end or break a markdown link destination. Everything else,
# accented letters included, is written as it is. Mirrors
# `formatLinkTarget` in frontend/src/lib/noteContent.ts; both run the cases
# in fixtures/markdown-link-targets.json.
_ENCODED_IN_TARGETS = frozenset(' #%()<>[]\\"')
_TASK_LINE_PATTERN = re.compile(r"^[ \t]*[-*+] \[([ xX])\] (.*)$")
_MANAGED_METADATA_KEYS = frozenset({"title", "tags", "created", "updated"})


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


@dataclass(frozen=True)
class _Destination:
    """A link destination as written, split into the decoded path, the raw
    `#fragment` (empty when absent) and whether it was in angle brackets."""

    path: str
    fragment: str
    angle: bool


def _decode_path(path: str) -> str:
    """Decode the percent-escapes in a link target's path. A run of escapes
    that isn't valid UTF-8, or a stray `%`, is kept as written, as the
    preview's `decodeLinkPath` does."""

    def _decode(match: re.Match[str]) -> str:
        escapes = match.group(0)
        try:
            return bytes.fromhex(escapes.replace("%", "")).decode("utf-8")
        except UnicodeDecodeError:
            return escapes

    return _PERCENT_ESCAPES.sub(_decode, path)


def _parse_destination(raw: str) -> _Destination | None:
    """None for an external link or a same-note `#heading` link."""
    angle = raw.startswith("<") and raw.endswith(">")
    inner = raw[1:-1].strip() if angle else raw
    if inner.startswith(_EXTERNAL_PREFIXES):
        return None
    path, _, fragment = inner.partition("#")
    return _Destination(_decode_path(path), fragment, angle)


def _links_outside_code(body: str) -> list[re.Match[str]]:
    """The markdown links in `body`, skipping fenced code blocks and inline
    code spans, where link syntax is an example, not a link."""
    skipped = code_ranges(body)
    skipped_starts = [start for start, _ in skipped]
    matches: list[re.Match[str]] = []
    for match in _LINK_PATTERN.finditer(body):
        index = bisect.bisect_right(skipped_starts, match.start()) - 1
        if index >= 0 and match.start() < skipped[index][1]:
            continue
        matches.append(match)
    return matches


def format_link_target(path: str) -> str:
    """A path written as a markdown link target: spaces and the other
    characters that would break the link percent-encoded."""
    return "".join(
        "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
        if char in _ENCODED_IN_TARGETS or ord(char) < 0x20
        else char
        for char in path
    )


def _format_destination(path: str, fragment: str, angle: bool) -> str:
    """Write a destination back in the style it was written in: angle
    brackets stay angle brackets (with the path as it is), anything else is
    percent-encoded. A path that can't sit unencoded between angle brackets
    -- one with `#`, `%` or angle brackets of its own -- is percent-encoded
    instead."""
    if angle and not any(char in path for char in "#%<>\n"):
        return f"<{path}#{fragment}>" if fragment else f"<{path}>"
    target = format_link_target(path)
    return f"{target}#{fragment}" if fragment else target


def resolve_link_target(source_path: str, target: str) -> str | None:
    """Resolve a link destination, as written, relative to the linking
    note's directory.

    Returns the normalized vault-relative path if it points at a `.md`
    file, or None if it's external/non-markdown and should be ignored for
    graph purposes. The target need not exist yet (broken links are valid
    data — see SPEC.md).
    """
    destination = _parse_destination(target)
    if destination is None or not destination.path.endswith(".md"):
        return None
    source_dir = PurePosixPath(source_path).parent
    return _normalize(source_dir / destination.path)


def extract_links(source_path: str, body: str) -> list[ParsedLink]:
    links: list[ParsedLink] = []
    for match in _links_outside_code(body):
        link_text, target = match.group(1), match.group(2)
        resolved = resolve_link_target(source_path, target)
        if resolved is not None:
            links.append(ParsedLink(target_path=resolved, link_text=link_text or None))
    return links


def extract_note_wikilinks(body: str) -> list[ParsedWikilink]:
    """The wikilinks in `body` that point at notes: not attachments
    (`![[photo.png]]`) and not links within the note itself
    (`[[#Heading]]`)."""
    return [
        ParsedWikilink(target=link.target, link_text=link.alias or None)
        for link in extract_wikilinks(body)
        if link.target and not link.is_attachment
    ]


def _first_body_line(raw_content: str) -> int:
    """The 1-based file line the body starts on: 1 without frontmatter,
    else the line after the frontmatter's closing boundary.

    Finds the block exactly as python-frontmatter does when `parse_note`
    loads the note -- same handlers, same boundary patterns, on the same
    normalized and stripped text -- so the lines skipped here are the
    ones `parse_note` reads as metadata. Its normalizing turns `\r\n`
    into `\n` and its strip drops leading blank lines, so the count adds
    back the line breaks that strip removed.
    """
    normalized = raw_content.replace("\r\n", "\n")
    text = normalized.strip()
    handler = frontmatter.detect_format(text, frontmatter.handlers)
    if handler is None or handler.FM_BOUNDARY is None:
        return 1
    boundaries = handler.FM_BOUNDARY.finditer(text)
    next(boundaries)  # the opening boundary, which detection matched
    closing = next(boundaries, None)
    if closing is None:
        # python-frontmatter reads a lone opening boundary as body text.
        return 1
    stripped_breaks = normalized[: len(normalized) - len(normalized.lstrip())].count(
        "\n"
    )
    return stripped_breaks + text.count("\n", 0, closing.end()) + 2


def extract_tasks(raw_content: str) -> list[ParsedTask]:
    """Extract every open/closed markdown checkbox line from a note's raw
    file content, skipping the frontmatter and any line inside a fenced
    (```/~~~) code block -- a note can legitimately document checkbox
    syntax as an example, and that example text is not a real task. See
    `fence_states` for the fence-matching rules.

    A task's line is its 1-based line in the file, frontmatter included,
    which is how a tick or untick finds it again. A line is the text
    between `\n` characters, so a `\r` before the `\n` stays part of it;
    `str.splitlines` isn't used, as it also splits on characters such as
    U+2028 and form feed that the editor and the line writer don't.
    """
    lines = raw_content.split("\n")
    first_body_line = _first_body_line(raw_content)
    body_lines = lines[first_body_line - 1 :]
    tasks: list[ParsedTask] = []
    for line_number, (line, fenced) in enumerate(
        zip(body_lines, fence_states(body_lines), strict=True), start=first_body_line
    ):
        if fenced:
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
    """Replace each markdown link's target via `resolver`.

    `resolver` receives a link's decoded path (e.g. `"My Note.md"` for
    `My%20Note.md`) and returns the replacement path, or None to leave that
    link untouched. The replacement keeps the link's text, `#fragment`,
    title and style (angle brackets or percent-encoding).
    """

    def _replace(match: re.Match[str]) -> str:
        link_text, raw, title = match.group(1), match.group(2), match.group(3)
        destination = _parse_destination(raw)
        if destination is None:
            return match.group(0)
        replacement = resolver(destination.path)
        if replacement is None:
            return match.group(0)
        written = _format_destination(
            replacement, destination.fragment, destination.angle
        )
        return f"[{link_text}]({written}{title or ''})"

    pieces: list[str] = []
    position = 0
    for match in _links_outside_code(body):
        pieces.append(body[position : match.start()])
        pieces.append(_replace(match))
        position = match.end()
    pieces.append(body[position:])
    return "".join(pieces)


def _relative_link_path(base_dir: PurePosixPath, absolute_target: str) -> str:
    return posixpath.relpath(absolute_target, start=str(base_dir))


def rebase_links(body: str, old_source_path: str, new_source_path: str) -> str:
    """Rewrite this note's own outgoing relative links so they still
    resolve to the same absolute targets after the note itself moves
    from `old_source_path` to `new_source_path`.
    """
    old_dir = PurePosixPath(old_source_path).parent
    new_dir = PurePosixPath(new_source_path).parent
    if old_dir == new_dir:
        return body

    def resolver(path: str) -> str | None:
        if not path.endswith(".md"):
            return None
        absolute = _normalize(old_dir / path)
        if absolute is None:
            return None
        return _relative_link_path(new_dir, absolute)

    return _rewrite_link_targets(body, resolver)


def retarget_links(
    body: str, source_path: str, old_target: str, new_target: str
) -> str:
    """Rewrite any link in this note that currently resolves to
    `old_target` so it instead resolves to `new_target` (used when
    ANOTHER note moves from `old_target` to `new_target`).
    """
    source_dir = PurePosixPath(source_path).parent

    def resolver(path: str) -> str | None:
        if not path.endswith(".md"):
            return None
        if _normalize(source_dir / path) != old_target:
            return None
        return _relative_link_path(source_dir, new_target)

    return _rewrite_link_targets(body, resolver)


def retarget_wikilinks(
    body: str, source_before: str, source_after: str, move: NoteMove
) -> str:
    """Rewrite the wikilinks in `body` that `move` would otherwise break.

    `source_before`/`source_after` are where this body's own note sits
    either side of the move (they differ only for the moved note itself).
    Every wikilink keeps pointing at the note it pointed at before the
    move -- the moved note at its new path, any other note where it was.
    A link that still does is left exactly as written; one that doesn't
    gets the shortest target that reaches it, keeping its embed marker,
    heading and alias. Unresolved links stay unresolved.

    A link is left as written when no wikilink can reach its note: one now
    in a hidden folder (it resolves again when the note comes back, and a
    note leaving a hidden folder takes back the links naming it), or one
    whose path holds a character a wikilink can't carry (`#`, `|`, `[`,
    `]`).
    """
    pieces: list[str] = []
    last = 0
    for link in extract_wikilinks(body):
        if not link.target or link.is_attachment:
            continue
        was = move.before.resolve(source_before, link.target)
        if was is None:
            continue
        if was == move.old_path:
            expected = move.new_path
        elif is_hidden_path(move.old_path):
            # A note coming back from a hidden folder (e.g. restored from
            # .trash) takes back the links that name it: while it was
            # hidden they could only fall through to a same-named note.
            continue
        else:
            expected = was
        if move.after.resolve(source_after, link.target) == expected:
            continue
        if is_hidden_path(expected):
            continue
        target = move.after.shortest_unambiguous_target(expected)
        if not is_writable_target(target):
            continue
        if link.target.lower().endswith(".md"):
            target += ".md"
        pieces.extend((body[last : link.start], link.render(target)))
        last = link.end
    if not pieces:
        return body
    pieces.append(body[last:])
    return "".join(pieces)


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
        tasks=extract_tasks(raw_content),
        wikilinks=extract_note_wikilinks(post.content),
        extra_metadata={
            key: value
            for key, value in metadata.items()
            if key not in _MANAGED_METADATA_KEYS
        },
        title_in_frontmatter="title" in metadata,
    )


def render_note(parsed: ParsedNote) -> str:
    metadata: dict[str, object] = dict(parsed.extra_metadata)
    if parsed.title_in_frontmatter:
        metadata["title"] = parsed.title
    metadata["tags"] = parsed.tags
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
