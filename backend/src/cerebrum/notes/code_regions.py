"""Find the parts of a note body that are code, so link and task extraction
can skip them: a note can legitimately document `- [ ] task` or
`[[wikilink]]` syntax as an example, and that example text is not real."""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator

_FENCE_PATTERN = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_BACKTICK_RUN = re.compile(r"`+")
# CommonMark lets a code span continue onto the next line of the same
# paragraph, but never across a blank line.
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def iter_lines_with_fence_state(body: str) -> Iterator[tuple[int, str, bool]]:
    """Yield `(offset, line, fenced)` for every line of `body`, where
    `fenced` is True for fence marker lines and the lines between them.
    `line` keeps its line ending, so offsets add up to positions in `body`.

    Tracks the opening fence's character (backtick or tilde) *and* run
    length, not just whether one is open, mirroring CommonMark's own
    fence-matching rule (a fence only closes on a marker of the same
    character with length >= the opener's). A bare on/off toggle, or one
    that ignores length, gets this wrong two ways: (1) a body that opens
    with ``` and later contains a literal ~~~ line as content inside that
    same block (e.g. documenting fence syntax) would close early and then
    reopen on the real closing ```, wrongly fencing everything after; (2)
    a longer fence (e.g. ````` `````) nesting a shorter same-character
    example fence (```` ``` ````) -- precisely the idiom for documenting
    "how to write a fenced code block" -- would have its inner markers
    mistaken for the outer close/reopen, inverting which lines are really
    fenced.
    """
    fence_char: str | None = None
    fence_length = 0
    offset = 0
    for line in body.splitlines(keepends=True):
        fence_match = _FENCE_PATTERN.match(line)
        if fence_match:
            marker = fence_match.group(1)
            char, length = marker[0], len(marker)
            if fence_char is None:
                fence_char, fence_length = char, length
            elif char == fence_char and length >= fence_length:
                fence_char, fence_length = None, 0
            # Any other fence-looking line (different character, or the
            # same character but a shorter run) doesn't close the open
            # fence -- it's just content, per CommonMark.
            yield offset, line, True
        else:
            yield offset, line, fence_char is not None
        offset += len(line)


def code_ranges(body: str) -> list[tuple[int, int]]:
    """Return the `[start, end)` ranges of `body` that are fenced code
    blocks or inline code spans, in order."""
    ranges: list[tuple[int, int]] = []
    prose_start: int | None = None
    for offset, line, fenced in iter_lines_with_fence_state(body):
        if fenced:
            if prose_start is not None:
                ranges.extend(_inline_code_ranges(body, prose_start, offset))
                prose_start = None
            ranges.append((offset, offset + len(line)))
        elif prose_start is None:
            prose_start = offset
    if prose_start is not None:
        ranges.extend(_inline_code_ranges(body, prose_start, len(body)))
    return ranges


def _inline_code_ranges(body: str, start: int, end: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    paragraph_start = start
    for blank in _BLANK_LINE.finditer(body, start, end):
        ranges.extend(_code_spans(body, paragraph_start, blank.start()))
        paragraph_start = blank.end()
    ranges.extend(_code_spans(body, paragraph_start, end))
    return ranges


def _code_spans(body: str, start: int, end: int) -> list[tuple[int, int]]:
    """Code spans in one paragraph: a run of backticks up to the next run
    of exactly the same length. Pairs runs by length with a binary search
    rather than a backtracking regex, so a paragraph full of unmatched
    runs of different lengths stays linear-ish instead of taking seconds."""
    runs = [match.span() for match in _BACKTICK_RUN.finditer(body, start, end)]
    runs_by_length: dict[int, list[int]] = {}
    for index, (run_start, run_end) in enumerate(runs):
        runs_by_length.setdefault(run_end - run_start, []).append(index)
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        run_start, run_end = runs[index]
        same_length = runs_by_length[run_end - run_start]
        position = bisect.bisect_right(same_length, index)
        if position == len(same_length):
            index += 1
            continue
        closer = same_length[position]
        spans.append((run_start, runs[closer][1]))
        index = closer + 1
    return spans
