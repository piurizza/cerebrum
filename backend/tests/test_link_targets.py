"""Markdown links whose target holds spaces or other special characters.

The shared cases in fixtures/markdown-link-targets.json also run in the
preview's tests (frontend/src/lib/noteContent.test.ts), so the backend and
the preview read and write link targets the same way.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cerebrum.notes.parser import (
    extract_links,
    format_link_target,
    rebase_links,
    resolve_link_target,
    retarget_links,
)
from cerebrum.notes.service import move_note

_CASES: dict[str, Any] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "markdown-link-targets.json").read_text(
        encoding="utf-8"
    )
)


def _ids(kind: str) -> list[str]:
    return [case["name"] for case in _CASES[kind]]


@pytest.mark.parametrize("case", _CASES["resolve"], ids=_ids("resolve"))
def test_shared_resolve_cases(case: dict[str, Any]) -> None:
    assert resolve_link_target(case["source"], case["target"]) == case["expected"]


@pytest.mark.parametrize("case", _CASES["format"], ids=_ids("format"))
def test_shared_format_cases(case: dict[str, Any]) -> None:
    assert format_link_target(case["path"]) == case["expected"]


def test_every_written_target_resolves_back_to_its_path() -> None:
    for case in _CASES["format"]:
        if case["path"].startswith(".."):
            continue
        assert (
            resolve_link_target("x.md", format_link_target(case["path"]))
            == (case["path"])
        )


def test_extracts_encoded_angle_bracket_and_titled_links() -> None:
    body = (
        "[one](My%20Note.md) [two](<Other Note.md>) "
        '[three](plain.md "A title") [four](<Spaced Note.md> "Title")'
    )
    assert [link.target_path for link in extract_links("a.md", body)] == [
        "My Note.md",
        "Other Note.md",
        "plain.md",
        "Spaced Note.md",
    ]


def test_a_bare_space_is_not_a_link() -> None:
    # Not a link in CommonMark either: the destination ends at the space.
    assert not extract_links("a.md", "[x](My Note.md)")


def test_retarget_keeps_each_links_style_title_and_heading() -> None:
    body = (
        '[a](<Old Note.md> "t") [b](Old%20Note.md#Part%20two) '
        "[c](Old%20Note.md) [d](other.md)"
    )
    assert retarget_links(body, "n.md", "Old Note.md", "New (2).md") == (
        '[a](<New (2).md> "t") [b](New%20%282%29.md#Part%20two) '
        "[c](New%20%282%29.md) [d](other.md)"
    )


def test_rebase_rewrites_encoded_and_angle_bracket_links() -> None:
    body = "[x](My%20Folder/y.md) [z](<sib note.md>)"
    assert rebase_links(body, "a.md", "deep/a.md") == (
        "[x](../My%20Folder/y.md) [z](<../sib note.md>)"
    )


def test_moving_a_note_with_spaces_rewrites_links_and_its_images(
    tmp_path: Path,
) -> None:
    vault = tmp_path
    (vault / "Old Note.md").write_text(
        "# Old\n\n![](Old%20Note.attachments/a.png)\n"
        "![](<Old Note.attachments/b.png>)\n",
        encoding="utf-8",
    )
    images = vault / "Old Note.attachments"
    images.mkdir()
    (images / "a.png").write_bytes(b"png")
    (images / "b.png").write_bytes(b"png")
    (vault / "linker.md").write_text(
        "See [old](Old%20Note.md) and [again](<Old Note.md>).\n", encoding="utf-8"
    )

    move_note(vault, "Old Note.md", "Moved/New Name.md")

    moved = (vault / "Moved" / "New Name.md").read_text(encoding="utf-8")
    assert "![](New%20Name.attachments/a.png)" in moved
    assert "![](<New Name.attachments/b.png>)" in moved
    assert (vault / "Moved" / "New Name.attachments" / "a.png").exists()
    linker = (vault / "linker.md").read_text(encoding="utf-8")
    assert "[old](Moved/New%20Name.md)" in linker
    assert "[again](<Moved/New Name.md>)" in linker


def test_moving_keeps_a_link_to_a_name_with_a_hash_working() -> None:
    # In angle brackets too, a bare `#` starts a heading, so a name with a
    # `#` is always written encoded.
    body = "[x](C%23%20tips.md) [y](<C%23 tips.md>)"
    moved = rebase_links(body, "a.md", "deep/a.md")
    assert moved == "[x](../C%23%20tips.md) [y](../C%23%20tips.md)"
    assert [link.target_path for link in extract_links("deep/a.md", moved)] == [
        "C# tips.md",
        "C# tips.md",
    ]


def test_reads_single_quoted_and_parenthesized_titles() -> None:
    body = "[a](x%20y.md 'One') [b](<z w.md> (Two))"
    assert [link.target_path for link in extract_links("n.md", body)] == [
        "x y.md",
        "z w.md",
    ]


def test_links_inside_code_are_not_links_and_are_not_rewritten() -> None:
    body = (
        "Write `[x](<Old Note.md>)` like this:\n\n"
        "```\n[y](Old%20Note.md)\n```\n\n[z](Old%20Note.md)\n"
    )
    assert [link.link_text for link in extract_links("n.md", body)] == ["z"]
    assert retarget_links(body, "n.md", "Old Note.md", "New.md") == body.replace(
        "[z](Old%20Note.md)", "[z](New.md)"
    )


def test_renaming_to_a_spaced_name_keeps_wikilink_image_embeds_raw(
    tmp_path: Path,
) -> None:
    vault = tmp_path
    (vault / "Plain.md").write_text(
        "![[Plain.attachments/a.png]]\n![](Plain.attachments/b.png)\n",
        encoding="utf-8",
    )
    (vault / "Plain.attachments").mkdir()
    (vault / "Plain.attachments" / "a.png").write_bytes(b"png")

    move_note(vault, "Plain.md", "New Name.md")

    moved = (vault / "New Name.md").read_text(encoding="utf-8")
    assert "![[New Name.attachments/a.png]]" in moved
    assert "![](New Name.attachments/b.png)" in moved
