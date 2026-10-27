from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest

from cerebrum.notes.file_lock import file_lock
from cerebrum.notes.parser import InvalidNoteContentError
from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteNotFoundError,
    note_version,
    write_note,
)
from cerebrum.tasks.service import (
    TaskConflictError,
    add_task,
    daily_heading_line,
    daily_note_body,
    daily_note_path,
    default_daily_heading,
    set_task_done,
)

_DAY = date(2026, 10, 26)
_FRONTMATTER = (
    "---\n"
    "created: '2026-10-01T09:00:00+00:00'\n"
    "tags:\n- garden\n"
    "updated: '2026-10-02T09:00:00+00:00'\n"
    "---\n"
)


# Notes a task write must refuse to change: one that isn't UTF-8, with
# its task on line 1, and one whose frontmatter isn't YAML, on line 4.
NOT_UTF_8 = b"- [ ] Water\n\xff\n"
BAD_FRONTMATTER = b"---\ntags: [unclosed\n---\n- [ ] Water\n"
UNREADABLE_IDS = ["not-utf-8", "bad-frontmatter"]


def _write(vault: Path, path: str, content: bytes) -> Path:
    file_path = vault / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    return file_path


def _keys(frontmatter: str) -> list[str]:
    return [line.split(":")[0] for line in frontmatter.split("\n")[1:]]


def _changed_lines(before: bytes, after: bytes) -> list[int]:
    old, new = before.split(b"\n"), after.split(b"\n")
    assert len(old) == len(new)
    return [
        number
        for number, pair in enumerate(zip(old, new, strict=True), 1)
        if pair[0] != pair[1]
    ]


# -- ticking and unticking ---------------------------------------------------


def test_tick_changes_only_the_task_line(vault: Path) -> None:
    before = (
        _FRONTMATTER + "\n# Garden\n\n- [ ] Water the herbs\n- [ ] Rake\n"
    ).encode()
    file_path = _write(vault, "garden.md", before)

    note, task = set_task_done(
        vault, "garden.md", 10, "Water the herbs", done=True, day=_DAY
    )

    after = file_path.read_bytes()
    assert _changed_lines(before, after) == [10]
    assert after.split(b"\n")[9] == "- [x] Water the herbs ✅ 2026-10-26".encode()
    assert note.updated is not None and note.updated.isoformat().startswith(
        "2026-10-02"
    )
    assert note.version == note_version(after)
    assert note.content == after.decode()
    assert task.model_dump() == {
        "path": "garden.md",
        "title": "garden",
        "line": 10,
        "text": "Water the herbs",
        "tags": ["garden"],
        "done": True,
        "done_date": _DAY,
    }


def test_tick_on_a_note_without_frontmatter_adds_none(vault: Path) -> None:
    file_path = _write(vault, "plain.md", b"- [ ] Water the herbs\n")

    set_task_done(vault, "plain.md", 1, "Water the herbs", done=True, day=_DAY)

    assert file_path.read_bytes() == "- [x] Water the herbs ✅ 2026-10-26\n".encode()


def test_tick_keeps_crlf_indent_bullet_and_block_id(vault: Path) -> None:
    file_path = _write(vault, "crlf.md", b"Intro\r\n  * [ ] Rake ^abc\r\nOutro\r\n")

    note, task = set_task_done(vault, "crlf.md", 2, "Rake ^abc", done=True, day=_DAY)

    assert file_path.read_bytes() == (
        "Intro\r\n  * [x] Rake ✅ 2026-10-26 ^abc\r\nOutro\r\n".encode()
    )
    # The content the API returns is read the way `read_note` reads it.
    assert note.content == "Intro\n  * [x] Rake ✅ 2026-10-26 ^abc\nOutro\n"
    assert task.text == "Rake ^abc"


def test_untick_removes_the_done_marker(vault: Path) -> None:
    file_path = _write(vault, "a.md", "- [x] Water the herbs ✅ 2026-10-20\n".encode())

    _, task = set_task_done(vault, "a.md", 1, "Water the herbs", done=False, day=None)

    assert file_path.read_bytes() == b"- [ ] Water the herbs\n"
    assert (task.done, task.done_date, task.text) == (False, None, "Water the herbs")


def test_the_text_may_be_sent_with_its_done_marker(vault: Path) -> None:
    # The note preview sends the text as the line holds it, marker and all,
    # rather than parsing the marker itself.
    file_path = _write(vault, "a.md", "- [x] Water ✅ 2026-10-20 ^w\n".encode())

    _, task = set_task_done(
        vault, "a.md", 1, "Water ✅ 2026-10-20 ^w", done=False, day=None
    )

    assert file_path.read_bytes() == b"- [ ] Water ^w\n"
    assert task.text == "Water ^w"


def test_ticking_an_already_ticked_task_writes_nothing(vault: Path) -> None:
    content = "- [x] Water ✅ 2026-10-20\n".encode()
    file_path = _write(vault, "a.md", content)
    mtime = file_path.stat().st_mtime_ns

    note, task = set_task_done(vault, "a.md", 1, "Water", done=True, day=_DAY)

    assert file_path.read_bytes() == content
    assert file_path.stat().st_mtime_ns == mtime
    assert note.version == note_version(content)
    assert (task.done, task.done_date) == (True, date(2026, 10, 20))


def test_unticking_an_open_task_writes_nothing(vault: Path) -> None:
    file_path = _write(vault, "a.md", b"- [ ] Water\n")
    mtime = file_path.stat().st_mtime_ns

    set_task_done(vault, "a.md", 1, "Water", done=False, day=None)

    assert file_path.read_bytes() == b"- [ ] Water\n"
    assert file_path.stat().st_mtime_ns == mtime


def test_two_identical_lines_stay_distinct(vault: Path) -> None:
    lines = ["- [ ] Same"] + ["filler"] * 7 + ["- [ ] Same", ""]
    file_path = _write(vault, "a.md", "\n".join(lines).encode())

    set_task_done(vault, "a.md", 9, "Same", done=True, day=_DAY)

    written = file_path.read_text().split("\n")
    assert written[0] == "- [ ] Same"
    assert written[8] == "- [x] Same ✅ 2026-10-26"


@pytest.mark.parametrize(
    ("line", "text"),
    [
        (2, "Water"),  # a stale line: the task moved down
        (1, "Rake"),  # changed text
        (5, "Water"),  # past the end of the file
        (0, "Water"),
        (3, "Not a task"),  # a line that isn't a task
    ],
)
def test_a_mismatch_is_refused_and_writes_nothing(
    vault: Path, line: int, text: str
) -> None:
    content = b"- [ ] Water\nNew first line\nNot a task\n"
    file_path = _write(vault, "a.md", content)

    with pytest.raises(TaskConflictError):
        set_task_done(vault, "a.md", line, text, done=True, day=_DAY)

    assert file_path.read_bytes() == content


def test_a_task_in_a_code_block_is_refused(vault: Path) -> None:
    content = b"```\n- [ ] Example\n```\n"
    file_path = _write(vault, "a.md", content)

    with pytest.raises(TaskConflictError):
        set_task_done(vault, "a.md", 2, "Example", done=True, day=_DAY)

    assert file_path.read_bytes() == content


def test_a_lone_carriage_return_above_the_task_is_refused(vault: Path) -> None:
    # The indexer reads `\r` as a line break, so for it the second "Same"
    # is on line 3; split on `\n` alone, line 2 holds it instead. Both hold
    # the same text, so only refusing keeps the wrong one from being ticked.
    content = b"Intro\r- [ ] Same\n- [ ] Same\n"
    file_path = _write(vault, "a.md", content)

    with pytest.raises(TaskConflictError):
        set_task_done(vault, "a.md", 2, "Same", done=True, day=_DAY)

    assert file_path.read_bytes() == content


def test_a_lone_carriage_return_below_the_task_does_not_matter(vault: Path) -> None:
    file_path = _write(vault, "a.md", b"- [ ] Water\nOld\rMac\n")

    set_task_done(vault, "a.md", 1, "Water", done=True, day=_DAY)

    assert file_path.read_bytes() == "- [x] Water ✅ 2026-10-26\nOld\rMac\n".encode()


def test_ticking_a_missing_note_raises_not_found(vault: Path) -> None:
    with pytest.raises(NoteNotFoundError):
        set_task_done(vault, "missing.md", 1, "Water", done=True, day=_DAY)


def test_ticking_outside_the_vault_is_refused(vault: Path) -> None:
    with pytest.raises(InvalidNotePathError):
        set_task_done(vault, "../outside.md", 1, "Water", done=True, day=_DAY)


def test_tick_needs_a_date(vault: Path) -> None:
    _write(vault, "a.md", b"- [ ] Water\n")

    with pytest.raises(ValueError):
        set_task_done(vault, "a.md", 1, "Water", done=True, day=None)


@pytest.mark.parametrize(
    ("content", "line"), [(NOT_UTF_8, 1), (BAD_FRONTMATTER, 4)], ids=UNREADABLE_IDS
)
def test_ticking_in_an_unreadable_note_is_refused_and_writes_nothing(
    vault: Path, content: bytes, line: int
) -> None:
    file_path = _write(vault, "a.md", content)

    with pytest.raises(InvalidNoteContentError):
        set_task_done(vault, "a.md", line, "Water", done=True, day=_DAY)

    assert file_path.read_bytes() == content


# -- adding --------------------------------------------------------------------


def test_default_heading_is_the_english_long_date() -> None:
    assert default_daily_heading(_DAY) == "Monday, 26 October 2026"
    assert default_daily_heading(date(2026, 11, 1)) == "Sunday, 1 November 2026"


def test_heading_line_and_body_match_the_today_button() -> None:
    # getDailyNoteDefaultBody in frontend/src/lib/dailyNote.ts.
    assert daily_heading_line("Monday, 26 October 2026") == "# Monday, 26 October 2026"
    assert daily_note_body("lunedì 26 ottobre 2026") == "# lunedì 26 ottobre 2026\n\n"
    assert daily_heading_line(" Two\nlines ") == "# Two lines"


def test_daily_note_path_mirrors_get_today_note_path() -> None:
    assert daily_note_path("journal/daily", _DAY) == "journal/daily/2026-10-26.md"


def test_add_creates_the_daily_note_like_the_today_button(vault: Path) -> None:
    note, task = add_task(
        vault, "daily", _DAY, "Order timber", "Monday, 26 October 2026"
    )

    # What the Today button saves for a missing note: getDailyNoteDefaultBody.
    today_button = write_note(vault, "other/today.md", "# Monday, 26 October 2026\n\n")
    written = (vault / "daily" / "2026-10-26.md").read_text()
    frontmatter, body = written.split("\n---\n", 1)
    button_frontmatter, button_body = today_button.content.split("\n---\n", 1)
    assert (
        _keys(frontmatter)
        == _keys(button_frontmatter)
        == ["created", "tags", "updated"]
    )
    assert body == button_body + "\n- [ ] Order timber\n"
    assert note.created is not None
    assert note.version == note_version(
        (vault / "daily" / "2026-10-26.md").read_bytes()
    )
    assert task.model_dump() == {
        "path": "daily/2026-10-26.md",
        "title": "2026-10-26",
        "line": written.count("\n"),
        "text": "Order timber",
        "tags": [],
        "done": False,
        "done_date": None,
    }


@pytest.mark.parametrize("heading", [None, "", " \n "])
def test_add_without_a_heading_uses_the_english_default(
    vault: Path, heading: str | None
) -> None:
    add_task(vault, "daily", _DAY, "Order timber", heading)

    assert (
        "\n# Monday, 26 October 2026\n" in (vault / "daily/2026-10-26.md").read_text()
    )


def test_add_ignores_the_heading_when_the_note_exists(vault: Path) -> None:
    file_path = _write(vault, "daily/2026-10-26.md", b"- [ ] First\n")

    add_task(vault, "daily", _DAY, "Second", "Ignored heading")

    assert file_path.read_bytes() == b"- [ ] First\n- [ ] Second\n"


def test_add_to_a_missing_note_takes_the_lock_once_and_releases_it(
    vault: Path,
) -> None:
    # `file_lock` isn't re-entrant: taking it twice would hang forever.
    thread = threading.Thread(
        target=add_task, args=(vault, "daily", _DAY, "Order timber", "Heading")
    )
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()
    lock_path = (vault / "daily" / "2026-10-26.md").resolve()
    acquired = threading.Event()

    def take_lock() -> None:
        with file_lock(lock_path):
            acquired.set()

    threading.Thread(target=take_lock).start()
    assert acquired.wait(timeout=5)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (b"- [ ] First\n", b"- [ ] First\n- [ ] New\n"),
        (b"- [ ] First", b"- [ ] First\n- [ ] New\n"),
        (b"A paragraph.\n", b"A paragraph.\n\n- [ ] New\n"),
        (b"A paragraph.", b"A paragraph.\n\n- [ ] New\n"),
        (b"A paragraph.\n\n", b"A paragraph.\n\n- [ ] New\n"),
        (b"# Heading\n", b"# Heading\n\n- [ ] New\n"),
        (
            b"- [x] Done \xe2\x9c\x85 2026-10-20\n\n",
            b"- [x] Done \xe2\x9c\x85 2026-10-20\n\n- [ ] New\n",
        ),
        (b"", b"- [ ] New\n"),
        (b"\n", b"\n- [ ] New\n"),
        (b"Intro\r\n- [ ] First\r\n", b"Intro\r\n- [ ] First\r\n- [ ] New\r\n"),
        (b"Intro\r\n", b"Intro\r\n\r\n- [ ] New\r\n"),
        (b"Intro\r\nOutro", b"Intro\r\nOutro\r\n\r\n- [ ] New\r\n"),
    ],
)
def test_add_appends_one_line_after_what_is_there(
    vault: Path, before: bytes, after: bytes
) -> None:
    file_path = _write(vault, "daily/2026-10-26.md", before)

    _, task = add_task(vault, "daily", _DAY, "New", "Heading")

    assert file_path.read_bytes() == after
    assert task.line == after.count(b"\n")


def test_add_keeps_frontmatter_byte_for_byte(vault: Path) -> None:
    before = (_FRONTMATTER + "\nNotes.\n").encode()
    file_path = _write(vault, "daily/2026-10-26.md", before)

    note, _ = add_task(vault, "daily", _DAY, "New", "Heading")

    assert file_path.read_bytes() == before + b"\n- [ ] New\n"
    assert note.updated is not None and note.updated.isoformat().startswith(
        "2026-10-02"
    )


@pytest.mark.parametrize(
    ("text", "stored"),
    [
        ("Buy\nmilk", "Buy milk"),
        ("  Buy\r\nmilk\t ", "Buy  milk"),
        ("- [ ] Buy", "Buy"),
        ("[ ] Buy", "Buy"),
        ("Buy milk\x00", "Buy milk"),
    ],
)
def test_add_cleans_the_text(vault: Path, text: str, stored: str) -> None:
    file_path = _write(vault, "daily/2026-10-26.md", b"")

    _, task = add_task(vault, "daily", _DAY, text, "Heading")

    assert file_path.read_text() == f"- [ ] {stored}\n"
    assert task.text == stored


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "- [ ]", "[ ]  "])
def test_add_refuses_empty_text_and_writes_nothing(vault: Path, text: str) -> None:
    with pytest.raises(ValueError):
        add_task(vault, "daily", _DAY, text, "Heading")

    assert not (vault / "daily").exists()


def test_add_after_an_unclosed_code_block_is_refused(vault: Path) -> None:
    content = b"```\ncode\n"
    file_path = _write(vault, "daily/2026-10-26.md", content)

    with pytest.raises(TaskConflictError):
        add_task(vault, "daily", _DAY, "New", "Heading")

    assert file_path.read_bytes() == content


@pytest.mark.parametrize("content", [NOT_UTF_8, BAD_FRONTMATTER], ids=UNREADABLE_IDS)
def test_add_to_an_unreadable_note_is_refused_and_writes_nothing(
    vault: Path, content: bytes
) -> None:
    file_path = _write(vault, "daily/2026-10-26.md", content)

    with pytest.raises(InvalidNoteContentError):
        add_task(vault, "daily", _DAY, "New", "Heading")

    assert file_path.read_bytes() == content
