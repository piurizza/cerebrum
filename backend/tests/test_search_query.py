from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cerebrum.index.search_query import parse_query, tags_match

# Shared with frontend/src/lib/tagQuery.test.ts, so the search box and the
# server parse the same query the same way.
_CASES: dict[str, Any] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "tag-query.json").read_text(
        encoding="utf-8"
    )
)


def _case_ids(kind: str) -> list[str]:
    return [case["name"] for case in _CASES[kind]]


@pytest.mark.parametrize("case", _CASES["parse"], ids=_case_ids("parse"))
def test_shared_parse_cases(case: dict[str, Any]) -> None:
    parsed = parse_query(case["query"])

    assert parsed.text == case["text"]
    assert list(parsed.include) == case["include"]
    assert list(parsed.exclude) == case["exclude"]


@pytest.mark.parametrize("case", _CASES["match"], ids=_case_ids("match"))
def test_shared_match_cases(case: dict[str, Any]) -> None:
    assert tags_match(case["note"], case["query"]) is case["expected"]


def test_every_included_tag_must_match_and_no_excluded_one() -> None:
    parsed = parse_query("#a #b -#c")

    assert parsed.matches(["a", "b/x"])
    assert not parsed.matches(["a"])
    assert not parsed.matches(["a", "b", "c/old"])


def test_no_tags_matches_every_note() -> None:
    assert parse_query("bread").matches([])
