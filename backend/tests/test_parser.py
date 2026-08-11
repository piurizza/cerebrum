from __future__ import annotations

import pytest

from cerebrum.notes.parser import (
    InvalidNoteContentError,
    extract_links,
    extract_tasks,
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


def test_extract_links_ignores_image_references() -> None:
    # Regression: an embedded image (e.g. an attachment) must never become
    # a graph link -- `resolve_link_target` only follows `.md`-suffixed
    # targets, so image markdown is inert for link-extraction purposes.
    assert not extract_links("note.md", "![alt](img.png)")


def test_extract_tasks_extracts_unchecked_task() -> None:
    tasks = extract_tasks("- [ ] Buy milk")
    assert len(tasks) == 1
    assert tasks[0].line == 1
    assert tasks[0].checked is False
    assert tasks[0].text == "Buy milk"


def test_extract_tasks_extracts_checked_task_either_case() -> None:
    tasks = extract_tasks("- [x] Done\n- [X] Also done")
    assert [t.checked for t in tasks] == [True, True]


def test_extract_tasks_accepts_dash_star_and_plus_bullets() -> None:
    tasks = extract_tasks("- [ ] a\n* [ ] b\n+ [ ] c")
    assert [t.text for t in tasks] == ["a", "b", "c"]


def test_extract_tasks_ignores_plain_list_items() -> None:
    assert not extract_tasks("- Buy milk")


def test_extract_tasks_ignores_checkbox_syntax_mid_sentence() -> None:
    assert not extract_tasks("See [ ] for details")


def test_extract_tasks_excludes_fenced_code_block_with_backticks() -> None:
    body = "- [ ] Real task\n```\n- [ ] Example in docs\n```\n- [ ] Another real task"
    tasks = extract_tasks(body)
    assert [t.text for t in tasks] == ["Real task", "Another real task"]


def test_extract_tasks_excludes_fenced_code_block_with_tildes() -> None:
    body = "~~~\n- [ ] Example\n~~~\n- [ ] Real task"
    tasks = extract_tasks(body)
    assert [t.text for t in tasks] == ["Real task"]


def test_extract_tasks_computes_line_numbers_across_headings_and_blanks() -> None:
    body = "# Heading\n\n- [ ] First\n\nSome text.\n\n- [ ] Second"
    tasks = extract_tasks(body)
    assert [(t.line, t.text) for t in tasks] == [(3, "First"), (7, "Second")]


def test_extract_tasks_extracts_indented_subtask() -> None:
    tasks = extract_tasks("- [ ] Parent\n  - [ ] Child")
    assert [t.text for t in tasks] == ["Parent", "Child"]


def test_parse_note_extracts_tasks_end_to_end() -> None:
    raw = (
        "---\ntitle: Todo\n---\n"
        "- [ ] Open task\n"
        "```\n- [ ] Example, not a task\n```\n"
        "- [x] Closed task\n"
    )
    parsed = parse_note("todo.md", raw)
    assert [(t.checked, t.text) for t in parsed.tasks] == [
        (False, "Open task"),
        (True, "Closed task"),
    ]
