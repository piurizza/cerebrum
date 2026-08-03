from __future__ import annotations

import pytest

from cerebrum.notes.parser import (
    InvalidNoteContentError,
    parse_note,
    rebase_links,
    render_note,
    resolve_link_target,
    retarget_links,
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


def test_render_note_separates_frontmatter_from_empty_body() -> None:
    # Regression: an empty/whitespace-only body used to render with NO
    # newline at all after the closing "---" (frontmatter.dumps() strips
    # trailing content whitespace outright), so appending text right at
    # the end of the file merged into the delimiter line and made the
    # frontmatter unparseable on the next save.
    parsed = parse_note("note.md", "---\ntitle: Empty\n---\n\n")

    rendered = render_note(parsed)

    assert rendered.endswith("---\n")
    appended = f"{rendered}New content."
    reparsed = parse_note("note.md", appended)
    assert reparsed.title == "Empty"
    assert reparsed.body == "New content."


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


def test_rebase_links_updates_relative_target_after_move_up() -> None:
    # A note at "folder/a.md" linking to "target.md" means "folder/target.md".
    # Moved to the root, the same absolute target needs the full path.
    body = "See [T](target.md)."

    rebased = rebase_links(body, "folder/a.md", "a.md")

    assert rebased == "See [T](folder/target.md)."


def test_rebase_links_no_op_when_directory_unchanged() -> None:
    body = "See [T](target.md)."

    rebased = rebase_links(body, "folder/a.md", "folder/renamed.md")

    assert rebased == body


def test_rebase_links_ignores_external_and_non_markdown_targets() -> None:
    body = "See [Site](https://example.com) and ![img](pic.png)."

    rebased = rebase_links(body, "folder/a.md", "a.md")

    assert rebased == body


def test_retarget_links_repoints_matching_links_only() -> None:
    body = "See [B](b.md) and [C](c.md)."

    retargeted = retarget_links(body, "linker.md", "b.md", "folder/b.md")

    assert retargeted == "See [B](folder/b.md) and [C](c.md)."


def test_retarget_links_preserves_fragment() -> None:
    body = "See [B](b.md#section)."

    retargeted = retarget_links(body, "linker.md", "b.md", "folder/b.md")

    assert retargeted == "See [B](folder/b.md#section)."
