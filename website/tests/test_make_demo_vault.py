from __future__ import annotations

import re
from pathlib import Path

import pytest

from make_demo_vault import SENTINEL_PATH, build_vault


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_two_runs_produce_identical_vaults(tmp_path: Path) -> None:
    build_vault(tmp_path / "a")
    build_vault(tmp_path / "b")
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


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
