"""The search query language shared by `GET /api/search`, the MCP
`search-notes` tool and the sidebar search box
(frontend/src/lib/tagQuery.ts): `#tag` keeps notes carrying that tag (or a
tag nested under it, `#work` -> `work/clientA`), `-#tag` drops them, and
`#"two words"` quotes a tag with a space. Everything else is left as text
for the full-text search. Both sides run the cases in
fixtures/tag-query.json, so they can't drift apart."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# A tag starts the query or follows whitespace, so `pre#fix` stays a word,
# and needs something besides digits, so `issue #42` stays words (as in
# Obsidian). An unterminated quote runs to the end of the query.
_TAG_TOKEN = re.compile(r'(?<!\S)(-?)#(?:"([^"]*)"?|([^\s"]*[^\s"\d][^\s"]*))')


def normalize_tag(tag: str) -> str:
    """One leading `#` and any outer `/` dropped, trimmed, lower-cased --
    the form two tags are compared in, so `#Work` in a note's frontmatter
    matches `#work`. `lower`, not `casefold`, to agree with the search
    box's `toLowerCase` (`casefold` turns `Straße` into `strasse`)."""
    tag = tag.strip()
    if tag.startswith("#"):
        tag = tag[1:].strip()
    return tag.strip("/").lower()


def tags_match(note_tag: str, query_tag: str) -> bool:
    """Whether a note's tag satisfies a tag from the query: the same tag,
    or one nested under it. Both sides are normalised here."""
    note_tag = normalize_tag(note_tag)
    query_tag = normalize_tag(query_tag)
    return note_tag == query_tag or note_tag.startswith(query_tag + "/")


@dataclass(frozen=True)
class ParsedQuery:
    text: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]

    @property
    def has_tags(self) -> bool:
        return bool(self.include or self.exclude)

    def matches(self, note_tags: Iterable[str]) -> bool:
        tags = list(note_tags)
        return all(
            any(tags_match(tag, wanted) for tag in tags) for wanted in self.include
        ) and not any(
            tags_match(tag, unwanted) for tag in tags for unwanted in self.exclude
        )


def parse_query(query: str) -> ParsedQuery:
    include: list[str] = []
    exclude: list[str] = []

    def take(match: re.Match[str]) -> str:
        tag = normalize_tag(
            match.group(2) if match.group(2) is not None else match.group(3)
        )
        if tag:
            (exclude if match.group(1) else include).append(tag)
        return " "

    text = " ".join(_TAG_TOKEN.sub(take, query).split())
    return ParsedQuery(text=text, include=tuple(include), exclude=tuple(exclude))
