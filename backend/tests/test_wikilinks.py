from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from cerebrum.notes.parser import parse_note
from cerebrum.notes.wikilinks import NoteLookup, Wikilink, extract_wikilinks

_CASES: dict[str, Any] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "wikilink-resolution.json").read_text(
        encoding="utf-8"
    )
)


def _only(links: list[Wikilink]) -> Wikilink:
    assert len(links) == 1
    return links[0]


def _case_ids(kind: str) -> list[str]:
    return [case["name"] for case in _CASES[kind]]


@pytest.mark.parametrize("case", _CASES["parse"], ids=_case_ids("parse"))
def test_shared_parse_cases(case: dict[str, Any]) -> None:
    found = [
        {
            "embed": link.embed,
            "target": link.target,
            "heading": link.heading,
            "alias": link.alias,
        }
        for link in extract_wikilinks(case["text"])
    ]

    assert found == case["expected"]


@pytest.mark.parametrize("case", _CASES["resolve"], ids=_case_ids("resolve"))
def test_shared_resolve_cases(case: dict[str, Any]) -> None:
    lookup = NoteLookup(case["notes"])

    assert lookup.resolve(case["source"], case["target"]) == case["expected"]


@pytest.mark.parametrize("case", _CASES["shortest"], ids=_case_ids("shortest"))
def test_shared_shortest_target_cases(case: dict[str, Any]) -> None:
    lookup = NoteLookup(case["notes"])

    target = lookup.shortest_unambiguous_target(case["path"])

    assert target == case["expected"]
    # Whatever it returns must reach the note from anywhere in the vault,
    # including from a folder holding a same-named note.
    for source in [*case["notes"], "elsewhere/Source.md"]:
        assert lookup.resolve(source, target) == case["path"]


def test_skips_fenced_code_and_inline_code() -> None:
    body = (
        "Real [[A]].\n"
        "```\n[[In fence]]\n```\n"
        "~~~~\n```\n[[Still fenced]]\n```\n~~~~\n"
        "Inline `[[Code]]` and ``[[Double `tick`]]`` here, then [[B]].\n"
    )

    assert [link.target for link in extract_wikilinks(body)] == ["A", "B"]


def test_keeps_spans_for_rewriting() -> None:
    body = "x ![[Note#H|alias]] y"

    link = _only(extract_wikilinks(body))

    assert body[link.start : link.end] == "![[Note#H|alias]]"
    assert link.render("Folder/New") == "![[Folder/New#H|alias]]"


def test_render_keeps_escaped_alias_separator() -> None:
    link = _only(extract_wikilinks("| [[a\\|b]] |"))

    assert link.render("c") == "[[c\\|b]]"


def test_parse_note_keeps_only_note_wikilinks() -> None:
    parsed = parse_note(
        "a.md",
        "[[B|Bee]] ![[C]] ![[Pasted image 2024.png]] [[doc.pdf]] [[#Heading]]",
    )

    assert [(link.target, link.link_text) for link in parsed.wikilinks] == [
        ("B", "Bee"),
        ("C", None),
    ]


def test_unmatched_backtick_runs_do_not_slow_parsing_down() -> None:
    # Many unmatched runs of different lengths in one paragraph made the
    # old backtracking pattern take seconds on a ~180 KB note.
    body = " ".join("`" * length for length in range(1, 600)) + " [[A]]"

    started = time.perf_counter()
    links = extract_wikilinks(body)

    assert time.perf_counter() - started < 1
    assert [link.target for link in links] == ["A"]


def test_code_span_rules() -> None:
    body = "``a ` b`` [[In]] `x` [[Out]]\n\n`open\n\n[[After blank]]` `"

    assert [link.target for link in extract_wikilinks(body)] == [
        "In",
        "Out",
        "After blank",
    ]
