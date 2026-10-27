from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from make_demo_vault import SENTINEL_PATH, build_vault


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


_TODAY = date(2027, 3, 10)


def _text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md")))


def test_two_runs_on_the_same_day_produce_identical_vaults(tmp_path: Path) -> None:
    build_vault(tmp_path / "a", today=_TODAY)
    build_vault(tmp_path / "b", today=_TODAY)
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


def test_done_dates_follow_the_day_it_runs(tmp_path: Path) -> None:
    # The Done tab lists the last 14 days, so a screenshot taken any day
    # needs tasks ticked on that day and the few before it.
    build_vault(tmp_path, today=_TODAY)
    done_dates = {
        date.fromisoformat(day)
        for day in re.findall(
            r"^- \[x\] .* ✅ (\d{4}-\d{2}-\d{2})$", _text(tmp_path), re.M
        )
    }
    assert {_TODAY, date(2027, 3, 9)} <= done_dates
    assert len(done_dates) >= 4
    assert all(0 <= (_TODAY - day).days < 14 for day in done_dates)
    assert "<days-ago:" not in _text(tmp_path)


def test_defaults_to_the_local_date(tmp_path: Path) -> None:
    build_vault(tmp_path)
    assert f"✅ {date.today().isoformat()}" in _text(tmp_path)


def test_vault_is_large_enough_to_look_real(tmp_path: Path) -> None:
    build_vault(tmp_path)
    notes = list(tmp_path.rglob("*.md"))
    assert 55 <= len(notes) <= 70


def test_every_note_has_frontmatter_tags(tmp_path: Path) -> None:
    build_vault(tmp_path)
    for note in tmp_path.rglob("*.md"):
        text = note.read_text(encoding="utf-8")
        assert text.startswith("---\n"), note
        assert re.search(r"^tags: \[.+\]$", text, re.MULTILINE), note


def test_vault_exercises_the_features_the_docs_show(tmp_path: Path) -> None:
    build_vault(tmp_path)
    text = "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.md"))
    assert re.search(r"tags: \[[^\]]*\w/\w", text), "a nested tag"
    assert "[[" in text, "a wikilink"
    assert re.search(r"\]\([^)]+\.md\)", text), "a markdown link"
    assert "- [ ] " in text and "- [x] " in text, "open and done tasks"
    assert re.search(r"^- \[x\] [^✅\n]+$", text, re.M), "a task ticked without a date"
    assert re.search(r"!\[[^\]]*\]\([^)]+\.attachments/[^)]+\.png\)", text), "embed"
    assert (tmp_path / "templates").is_dir()
    assert len(list((tmp_path / "daily").glob("*.md"))) >= 5


def test_embedded_images_exist(tmp_path: Path) -> None:
    build_vault(tmp_path)
    for note in tmp_path.rglob("*.md"):
        for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", note.read_text("utf-8")):
            assert (note.parent / target).is_file(), (note, target)


def test_writes_the_sentinel_note(tmp_path: Path) -> None:
    build_vault(tmp_path)
    sentinel = (tmp_path / SENTINEL_PATH).read_text(encoding="utf-8")
    assert "demo_vault: cerebrum-docs" in sentinel


def test_contains_no_hidden_files(tmp_path: Path) -> None:
    build_vault(tmp_path)
    assert not list(tmp_path.rglob(".*"))


def test_refuses_a_folder_that_is_not_empty(tmp_path: Path) -> None:
    (tmp_path / "my-notes.md").write_text("mine", encoding="utf-8")
    with pytest.raises(SystemExit):
        build_vault(tmp_path)
    assert (tmp_path / "my-notes.md").read_text(encoding="utf-8") == "mine"
