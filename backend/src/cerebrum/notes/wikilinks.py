"""Obsidian-style `[[wikilinks]]`: finding them in a note body and resolving
a written target to a note path.

A wikilink names a note by file name, not by path, so what it points at
depends on every other note in the vault. That is why the index stores
wikilinks as written and resolves them when reading (see
`graph/service.py`), unlike markdown links, which resolve on their own.

The frontend's preview mirrors these rules in `frontend/src/lib/wikilinks.ts`;
both test suites run the shared cases in `fixtures/wikilink-resolution.json`.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from cerebrum.notes.code_regions import code_ranges

# `!` (embed), then `[[`, then anything up to the first `]]` on the same
# line that doesn't itself contain a bracket.
_WIKILINK_PATTERN = re.compile(r"(!?)\[\[([^\[\]\n]*)\]\]")
# `\|` is Obsidian's alias separator inside a table cell, where a bare `|`
# would end the cell.
_ALIAS_SEPARATOR_PATTERN = re.compile(r"\\?\|")

# A target ending in one of these is a file, not a note. Anything else --
# including a dotted note name such as `Release 1.2` -- is a note.
ATTACHMENT_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".bmp",
        ".avif",
        ".pdf",
        ".mp3",
        ".wav",
        ".m4a",
        ".ogg",
        ".flac",
        ".mp4",
        ".webm",
        ".mov",
        ".mkv",
        ".ogv",
    }
)


@dataclass(frozen=True)
class Wikilink:
    """One wikilink as written. `heading` and `alias` are None when absent
    (an empty alias, `[[Note|]]`, is kept as `""` so rewriting preserves it)."""

    embed: bool
    target: str
    heading: str | None
    alias: str | None
    alias_separator: str
    start: int
    end: int

    @property
    def is_attachment(self) -> bool:
        return is_attachment_target(self.target)

    def render(self, target: str) -> str:
        """This link's text with its target replaced, everything else kept."""
        text = f"{'!' if self.embed else ''}[[{target}"
        if self.heading is not None:
            text += f"#{self.heading}"
        if self.alias is not None:
            text += f"{self.alias_separator}{self.alias}"
        return f"{text}]]"


def extract_wikilinks(body: str) -> list[Wikilink]:
    """Every wikilink in `body`, in order, skipping fenced code blocks and
    inline code spans. `[[]]` and `[[ ]]` are not links."""
    skipped = code_ranges(body)
    skipped_starts = [start for start, _ in skipped]
    links: list[Wikilink] = []
    for match in _WIKILINK_PATTERN.finditer(body):
        index = bisect.bisect_right(skipped_starts, match.start()) - 1
        if index >= 0 and match.start() < skipped[index][1]:
            continue
        link = _parse_inner(match.group(2), match.group(1) == "!", match.span())
        if link is not None:
            links.append(link)
    return links


def _parse_inner(inner: str, embed: bool, span: tuple[int, int]) -> Wikilink | None:
    alias: str | None = None
    alias_separator = "|"
    separator = _ALIAS_SEPARATOR_PATTERN.search(inner)
    if separator is not None:
        alias = inner[separator.end() :]
        alias_separator = separator.group(0)
        inner = inner[: separator.start()]
    target, hash_sign, heading = inner.partition("#")
    target = target.strip()
    if not target and not (hash_sign and heading.strip()):
        return None
    return Wikilink(
        embed=embed,
        target=target,
        heading=heading if hash_sign else None,
        alias=alias,
        alias_separator=alias_separator,
        start=span[0],
        end=span[1],
    )


# Characters a wikilink target can't carry: brackets end the link, `|`
# starts the alias, `#` the heading.
_UNSAFE_TARGET_CHARACTERS = frozenset("[]|#")


def is_writable_target(target: str) -> bool:
    """Whether `target` can be written inside `[[...]]` and read back."""
    return not _UNSAFE_TARGET_CHARACTERS.intersection(target)


def is_attachment_target(target: str) -> bool:
    return PurePosixPath(target).suffix.lower() in ATTACHMENT_EXTENSIONS


def name_key(text: str) -> str:
    """The comparison form of a name: Unicode NFC (macOS writes accented
    file names decomposed) and lowercase."""
    return unicodedata.normalize("NFC", text).lower()


def _strip_md(target: str) -> str:
    return target[:-3] if target.lower().endswith(".md") else target


def target_name_key(target: str) -> str:
    """The key of the note name a written target points at -- its last
    path segment, without `.md`. Indexed so backlinks can find candidate
    links without resolving every wikilink in the vault."""
    return name_key(PurePosixPath(_strip_md(target.strip())).name)


def is_hidden_path(path: str) -> bool:
    """True for anything under a dot-prefixed folder (`.trash/`,
    `.obsidian/`, `.cerebrum/`) or itself dot-prefixed."""
    return any(part.startswith(".") for part in PurePosixPath(path).parts)


def closest_path(candidates: Iterable[str], source_path: str) -> str:
    """The candidate a link written in `source_path` means when several
    files match: the one in the same folder, then the shortest path
    (fewest folders, then fewest characters), then alphabetical order."""
    source_dir = PurePosixPath(source_path).parent

    def rank(path: str) -> tuple[bool, int, int, str]:
        pure = PurePosixPath(path)
        return (pure.parent != source_dir, len(pure.parts), len(path), path)

    return min(candidates, key=rank)


class NoteLookup:
    """The vault's note paths, indexed by name, for resolving wikilinks.
    Build one per request and resolve every link against it."""

    def __init__(self, note_paths: Iterable[str]) -> None:
        self._by_name: dict[str, list[str]] = {}
        for path in note_paths:
            if is_hidden_path(path):
                continue
            key = name_key(PurePosixPath(path).stem)
            self._by_name.setdefault(key, []).append(path)

    def resolve(self, source_path: str, target: str) -> str | None:
        """The note `target` points at when written in `source_path`, or
        None. An empty target (`[[#Heading]]`) is the linking note itself.

        Matches the file name, never the title, ignoring case and a
        trailing `.md`. A target containing `/` must match the whole
        vault-relative path or its end. When several notes match, the one
        in the linking note's folder wins, then the shortest path (fewest
        folders, then fewest characters), then alphabetical order.
        A leading `/` anchors the target at the vault root: only that exact
        path matches. Relative targets (`./`, `../`) are not supported.
        """
        target = _strip_md(target.strip())
        anchored = target.startswith("/")
        target = target.strip("/")
        if not target:
            return None if anchored else source_path
        parts = target.split("/")
        if any(part in (".", "..", "") for part in parts):
            return None
        same_name = self._by_name.get(name_key(parts[-1]), [])
        candidates = same_name
        if anchored or len(parts) > 1:
            wanted = name_key(target)
            candidates = [p for p in same_name if name_key(_strip_md(p)) == wanted]
            if not anchored and not candidates:
                candidates = [
                    p
                    for p in same_name
                    if name_key(_strip_md(p)).endswith(f"/{wanted}")
                ]
        if not candidates:
            return None
        return closest_path(candidates, source_path)

    def shortest_unambiguous_target(self, path: str) -> str:
        """The shortest target that points at `path` from any note: the
        file name when no other note shares it, otherwise the shortest
        trailing part of the path that only `path` ends with. A root-level
        note whose name is shared gets the root-anchored `/Name`."""
        no_ext = _strip_md(path)
        parts = no_ext.split("/")
        others = [
            name_key(_strip_md(p))
            for p in self._by_name.get(name_key(parts[-1]), [])
            if p != path
        ]
        for count in range(1, len(parts)):
            suffix = "/".join(parts[-count:])
            key = name_key(suffix)
            if not any(other == key or other.endswith(f"/{key}") for other in others):
                return suffix
        if not others:
            return no_ext
        return no_ext if len(parts) > 1 else f"/{no_ext}"


@dataclass(frozen=True)
class NoteMove:
    """One note moving from `old_path` to `new_path`, with the vault's
    notes on either side of the move.

    `pending` maps the current path of every note that has already moved
    on disk but whose move hasn't been applied to links yet (later pairs
    of the same watcher batch, e.g. the other notes of a renamed folder)
    back to where it was. Those notes are treated as not moved yet, so a
    folder rename replays as a sequence of single moves, each seeing a
    consistent vault."""

    old_path: str
    new_path: str
    before: NoteLookup
    after: NoteLookup
    pending: Mapping[str, str]

    @classmethod
    def from_paths_after(
        cls,
        old_path: str,
        new_path: str,
        paths_after: Sequence[str],
        pending: Mapping[str, str] | None = None,
    ) -> NoteMove:
        """Build from the vault's note paths as they are on disk now."""
        pending = dict(pending or {})
        after = [pending.get(path, path) for path in paths_after]
        before = [old_path if path == new_path else path for path in after]
        return cls(old_path, new_path, NoteLookup(before), NoteLookup(after), pending)

    def logical_path(self, disk_path: str) -> str:
        """Where the note at `disk_path` is as far as this move knows."""
        return self.pending.get(disk_path, disk_path)
