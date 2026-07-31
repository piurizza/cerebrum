from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from cerebrum.notes.models import Note
from cerebrum.notes.parser import parse_note, render_note


class NoteNotFoundError(Exception):
    pass


class InvalidNotePathError(Exception):
    pass


def resolve_note_path(vault_root: Path, path: str) -> Path:
    """Resolve a vault-relative note path to an absolute filesystem path.

    Rejects any path that escapes the vault root (e.g. via `..`) or that
    doesn't end in `.md`.
    """
    vault_resolved = vault_root.resolve()
    candidate = (vault_resolved / path).resolve()
    if candidate != vault_resolved and vault_resolved not in candidate.parents:
        raise InvalidNotePathError(path)
    if candidate.suffix != ".md":
        raise InvalidNotePathError(path)
    return candidate


def iter_note_paths(vault_root: Path) -> Iterator[str]:
    if not vault_root.exists():
        return
    for file_path in sorted(vault_root.rglob("*.md")):
        if ".cerebrum" in file_path.relative_to(vault_root).parts:
            continue
        yield file_path.relative_to(vault_root).as_posix()


def read_note(vault_root: Path, path: str) -> Note:
    file_path = resolve_note_path(vault_root, path)
    try:
        raw_content = file_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise NoteNotFoundError(path) from exc
    parsed = parse_note(path, raw_content)
    return Note(
        path=path,
        title=parsed.title,
        tags=parsed.tags,
        created=parsed.created,
        updated=parsed.updated,
        content=raw_content,
    )


def write_note(vault_root: Path, path: str, raw_content: str) -> Note:
    file_path = resolve_note_path(vault_root, path)
    parsed = parse_note(path, raw_content)

    now = datetime.now(UTC)
    if parsed.created is None:
        parsed.created = now
    parsed.updated = now

    rendered = render_note(parsed)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(rendered, encoding="utf-8")

    return Note(
        path=path,
        title=parsed.title,
        tags=parsed.tags,
        created=parsed.created,
        updated=parsed.updated,
        content=rendered,
    )


def delete_note(vault_root: Path, path: str) -> None:
    file_path = resolve_note_path(vault_root, path)
    if not file_path.is_file():
        raise NoteNotFoundError(path)
    file_path.unlink()
