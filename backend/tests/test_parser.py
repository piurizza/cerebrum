from __future__ import annotations

import pytest

from cerebrum.notes.parser import (
    InvalidNoteContentError,
    parse_note,
    render_note,
    resolve_link_target,
)


def test_resolve_link_target_relative_path() -> None:
    assert (
        resolve_link_target("projects/idea.md", "../notes/related.md")
        == "notes/related.md"
    )


def test_resolve_link_target_same_directory() -> None:
    assert resolve_link_target("idea.md", "related.md") == "related.md"


def test_resolve_link_target_ignores_external_links() -> None:
    assert resolve_link_target("idea.md", "https://example.com") is None
    assert resolve_link_target("idea.md", "mailto:a@example.com") is None


def test_resolve_link_target_ignores_non_markdown() -> None:
    assert resolve_link_target("idea.md", "image.png") is None


def test_parse_note_extracts_frontmatter_and_links() -> None:
    raw = (
        "---\n"
        "title: My Note\n"
        "tags: [a, b]\n"
        "---\n"
        "See [Other](other.md) and [Site](https://example.com).\n"
    )

    parsed = parse_note("folder/note.md", raw)

    assert parsed.title == "My Note"
    assert parsed.tags == ["a", "b"]
    assert len(parsed.links) == 1
    assert parsed.links[0].target_path == "folder/other.md"


def test_parse_note_falls_back_to_filename_title() -> None:
    parsed = parse_note("folder/my-note.md", "no frontmatter here")

    assert parsed.title == "my-note"
    assert parsed.tags == []


def test_render_note_roundtrips_through_parse_note() -> None:
    raw = "---\ntitle: Roundtrip\ntags: [x]\n---\nBody text.\n"
    parsed = parse_note("note.md", raw)

    rendered = render_note(parsed)
    reparsed = parse_note("note.md", rendered)

    assert reparsed.title == "Roundtrip"
    assert reparsed.tags == ["x"]
    assert reparsed.body.strip() == "Body text."


def test_parse_note_raises_on_malformed_frontmatter() -> None:
    # Regression: typing directly into the frontmatter block (e.g. right
    # after "tags: []" with no newline) used to crash write_note with an
    # unhandled 500 instead of a clean, catchable error.
    raw = (
        "---\ntags: []Hello from the create-note test.\ntitle: test-note\n---\nBody.\n"
    )

    with pytest.raises(InvalidNoteContentError):
        parse_note("test-note.md", raw)


def test_parse_note_raises_on_invalid_date() -> None:
    raw = "---\ntitle: A\ncreated: not-a-date\n---\nBody.\n"

    with pytest.raises(InvalidNoteContentError):
        parse_note("a.md", raw)
