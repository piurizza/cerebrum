from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from cerebrum.tasks.markers import (
    parse_task_line,
    split_done_marker,
    tick_line,
    untick_line,
)

_DAY = date(2026, 10, 26)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Water ✅ 2026-10-26", ("Water", _DAY)),
        ("Water ✅️  2026-10-26 ^abc", ("Water ^abc", _DAY)),
        ("Water ✅ 2026-10-26   ", ("Water", _DAY)),
        ("✅ 2026-10-26", ("", _DAY)),
        ("Water✅ 2026-10-26", ("Water", _DAY)),
        # Only the last marker on the line counts.
        ("Water ✅ 2026-10-01 ✅ 2026-10-26", ("Water ✅ 2026-10-01", _DAY)),
    ],
)
def test_split_done_marker_finds_the_marker(
    text: str, expected: tuple[str, date]
) -> None:
    assert split_done_marker(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Water",
        "Water ✅ 2026-13-40",
        "Water ✅ 2026-02-30",
        "Water ✅ 2026-10-26 later",
        "Water ✅ 2026-10-26 📅 2026-10-30",
        "Water ✅2026-10-26",
        "Water ✅ 26-10-26",
        "Water ✅ ２０２６-10-26",
    ],
)
def test_split_done_marker_leaves_text_without_a_valid_marker(text: str) -> None:
    assert split_done_marker(text) == (text, None)


def test_parse_task_line_splits_the_parts_a_rewrite_keeps() -> None:
    task = parse_task_line("\t* [X] Water ✅ 2026-10-26 ^id  \r\n")
    assert task is not None
    assert (task.indent, task.bullet, task.checked, task.text, task.ending) == (
        "\t",
        "*",
        True,
        "Water ✅ 2026-10-26 ^id",
        "\r\n",
    )


@pytest.mark.parametrize("line", ["- Water", "See [ ] here", "-[ ] Water", ""])
def test_parse_task_line_is_none_for_other_lines(line: str) -> None:
    assert parse_task_line(line) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("  * [ ] Water ^id", "  * [x] Water ✅ 2026-10-26 ^id"),
        ("- [ ] Water", "- [x] Water ✅ 2026-10-26"),
        ("+ [ ] Water\n", "+ [x] Water ✅ 2026-10-26\n"),
        ("- [ ] Water\r\n", "- [x] Water ✅ 2026-10-26\r\n"),
        ("- [ ] Water\r", "- [x] Water ✅ 2026-10-26\r"),
        ("- [X] Water", "- [x] Water ✅ 2026-10-26"),
        ("- [x] Water ✅ 2026-10-01 ^id", "- [x] Water ✅ 2026-10-26 ^id"),
        ("- [x] Water ✅️ 2026-10-01", "- [x] Water ✅ 2026-10-26"),
        ("- [ ] ", "- [x] ✅ 2026-10-26"),
        # A date that isn't the done marker stays part of the text.
        ("- [ ] Water ✅ 2026-13-40", "- [x] Water ✅ 2026-13-40 ✅ 2026-10-26"),
    ],
)
def test_tick_line(line: str, expected: str) -> None:
    assert tick_line(line, _DAY) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("  * [x] Water ✅ 2026-10-26 ^id", "  * [ ] Water ^id"),
        ("- [X] Water ✅ 2026-10-26", "- [ ] Water"),
        ("- [x] Water ✅ 2026-10-26\r\n", "- [ ] Water\r\n"),
        ("- [x] Water\n", "- [ ] Water\n"),
        ("- [x] ✅ 2026-10-26", "- [ ] "),
        ("- [ ] Water", "- [ ] Water"),
    ],
)
def test_untick_line(line: str, expected: str) -> None:
    assert untick_line(line) == expected


def test_a_ticked_then_unticked_line_is_back_where_it_started() -> None:
    line = "    - [ ] Water the plants ^plants\r\n"
    assert untick_line(tick_line(line, _DAY)) == line


@pytest.mark.parametrize("builder", [lambda line: tick_line(line, _DAY), untick_line])
def test_builders_refuse_a_line_that_is_not_a_task(
    builder: Callable[[str], str],
) -> None:
    with pytest.raises(ValueError, match="not a task line"):
        builder("Just prose\n")
