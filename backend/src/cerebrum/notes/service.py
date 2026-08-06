from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cerebrum.attachments.service import (
    attachment_dir_for_note,
    delete_attachment_dir,
    move_attachment_dir,
)
from cerebrum.notes.models import Note
from cerebrum.notes.parser import parse_note, rebase_links, render_note, retarget_links

logger = logging.getLogger(__name__)


class NoteNotFoundError(Exception):
    pass


class InvalidNotePathError(Exception):
    pass


class NoteAlreadyExistsError(Exception):
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
    delete_attachment_dir(vault_root, path)


def _retarget_other_notes(
    vault_root: Path, old_target: str, new_target: str
) -> list[str]:
    """Repoint every OTHER note's links that targeted `old_target` so they
    resolve to `new_target` instead. Returns the vault-relative paths of
    the notes that were actually rewritten."""
    retargeted: list[str] = []
    for other_path in iter_note_paths(vault_root):
        if other_path == new_target:
            continue
        other_file = vault_root / other_path
        try:
            other_raw = other_file.read_text(encoding="utf-8")
            other_parsed = parse_note(other_path, other_raw)
        except Exception:  # noqa: BLE001 -- one bad note must not abort the move
            logger.exception(
                "Failed to check %s for links to relink; skipping", other_path
            )
            continue

        new_body = retarget_links(other_parsed.body, other_path, old_target, new_target)
        if new_body == other_parsed.body:
            continue
        other_parsed.body = new_body
        other_parsed.updated = datetime.now(UTC)
        other_file.write_text(render_note(other_parsed), encoding="utf-8")
        retargeted.append(other_path)
    return retargeted


def _rebase_attachment_references(body: str, old_path: str, new_path: str) -> str:
    """Rewrite `<old-stem>.attachments/` occurrences in `body` to
    `<new-stem>.attachments/` when the note's own filename stem changed
    (not just its directory). No-op (returns `body` unchanged) when the
    stem didn't change.

    A plain (non-anchored) substring replace would also mangle an
    unrelated reference whose own folder name merely *ends with* the old
    stem -- e.g. renaming `idea.md` would corrupt a cross-note reference
    like `![](other-idea.attachments/x.png)` into
    `![](other-better-idea.attachments/x.png)`, since `"idea.attachments/"`
    is a substring of `"other-idea.attachments/"`. Requiring a non-word
    character (or start-of-string) immediately before the match keeps this
    a plain string substitution (per KTD7 -- not a markdown-link reparse)
    while still only matching the stem as its own token, not as a suffix
    of a longer one.
    """
    old_stem = PurePosixPath(old_path).stem
    new_stem = PurePosixPath(new_path).stem
    if old_stem == new_stem:
        return body
    pattern = re.compile(rf"(?<![\w-]){re.escape(old_stem)}\.attachments/")
    return pattern.sub(f"{new_stem}.attachments/", body)


def move_note(
    vault_root: Path, path: str, new_path: str, title: str | None = None
) -> tuple[Note, list[str]]:
    """Relocate a note on disk and keep markdown links pointing at it correct.

    Rewrites the moved note's own outgoing relative links so they still
    resolve to the same absolute targets (they're relative to its own
    folder, which just changed), and repoints every OTHER note's links
    that targeted the old path so they resolve to the new one instead.
    A note with unreadable/malformed content is skipped (logged, not
    fatal) rather than aborting the whole move -- see rebuild_index for
    the same defensive pattern.

    Also relocates the note's attachment folder (`<stem>.attachments/`,
    sibling to the note file) so it travels with the note. If the move
    also changes the note's filename stem (not just its directory), the
    attachment folder is renamed to match the new stem, and any literal
    `<old-stem>.attachments/` occurrence in the note's own body (e.g. an
    embedded `![](old-stem.attachments/abc.png)` reference) is rewritten
    to `<new-stem>.attachments/` so the note's own embeds keep resolving.

    If `title` is given, the note's frontmatter `title` is also updated
    as part of the same write -- this is the only way to rename a note's
    displayed title (sidebar, graph) in step with its path. `new_path`
    may equal `path`, in which case this is a title-only update with no
    file relocation or link rewriting.

    Returns the moved note and the vault-relative paths of any OTHER
    notes whose link text was rewritten, so the caller can keep the
    index in sync for those too.
    """
    source = resolve_note_path(vault_root, path)
    destination = resolve_note_path(vault_root, new_path)
    is_relocation = source != destination

    if not source.is_file():
        raise NoteNotFoundError(path)
    if is_relocation and destination.exists():
        raise NoteAlreadyExistsError(new_path)

    had_attachment_dir = False
    if is_relocation:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        had_attachment_dir = attachment_dir_for_note(vault_root, path).exists()
        move_attachment_dir(vault_root, path, new_path)

    raw_content = destination.read_text(encoding="utf-8")
    parsed = parse_note(new_path, raw_content)

    changed = False
    if is_relocation:
        if had_attachment_dir:
            rewritten_body = _rebase_attachment_references(parsed.body, path, new_path)
            if rewritten_body != parsed.body:
                parsed.body = rewritten_body
                changed = True
        rebased_body = rebase_links(parsed.body, path, new_path)
        if rebased_body != parsed.body:
            parsed.body = rebased_body
            changed = True
    if title is not None and title != parsed.title:
        parsed.title = title
        changed = True

    if changed:
        parsed.updated = datetime.now(UTC)
        raw_content = render_note(parsed)
        destination.write_text(raw_content, encoding="utf-8")

    retargeted = (
        _retarget_other_notes(vault_root, path, new_path) if is_relocation else []
    )

    return (
        Note(
            path=new_path,
            title=parsed.title,
            tags=parsed.tags,
            created=parsed.created,
            updated=parsed.updated,
            content=raw_content,
        ),
        retargeted,
    )
