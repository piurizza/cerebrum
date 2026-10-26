from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cerebrum.attachments.service import (
    attachment_dir_for_note,
    delete_attachment_dir,
    move_attachment_dir,
)
from cerebrum.notes.file_lock import file_lock
from cerebrum.notes.models import Note
from cerebrum.notes.parser import (
    format_link_target,
    parse_note,
    rebase_links,
    render_note,
    retarget_links,
    retarget_wikilinks,
)
from cerebrum.notes.wikilinks import NoteMove, is_hidden_path
from cerebrum.read_only import ensure_vault_writable

logger = logging.getLogger(__name__)


class NoteNotFoundError(Exception):
    pass


class InvalidNotePathError(Exception):
    pass


class NoteAlreadyExistsError(Exception):
    pass


class NoteVersionConflictError(Exception):
    """The note on disk is no longer the version the caller loaded:
    it was changed or deleted since."""


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


def note_version(raw_bytes: bytes) -> str:
    """A note's version: the sha256 of its file's bytes as they are on
    disk. Not the indexer's content hash, which hashes the text after
    newline translation, so a file differing only in line endings has the
    same content hash but a different version."""
    return hashlib.sha256(raw_bytes).hexdigest()


def _read_raw(file_path: Path) -> tuple[str, str]:
    """A note file's text and version. The text is decoded the way
    `read_text` does, universal newlines included, so CRLF and a lone CR
    still read as LF; the version hashes the bytes untouched."""
    raw_bytes = file_path.read_bytes()
    text = raw_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return text, note_version(raw_bytes)


def _write_raw(file_path: Path, raw_content: str) -> str:
    """Write a note file and return its version. Written as bytes so the
    version is exactly what is on disk, with no newline translation."""
    raw_bytes = raw_content.encode("utf-8")
    file_path.write_bytes(raw_bytes)
    return note_version(raw_bytes)


def iter_note_paths(vault_root: Path) -> Iterator[str]:
    """Every note in the vault, as sorted vault-relative posix paths.

    Hidden folders (`.git/`, `.obsidian/`, `.trash/`, `.cerebrum/`) are
    never entered and hidden files never listed, matching `is_hidden_path`.
    A `.md` symlink resolving outside the vault, to a non-`.md` file, or
    in a loop is left out, since `resolve_note_path` would refuse to read
    it -- one bad link must never stop the whole scan, and with it startup.
    """
    vault_resolved = vault_root.resolve()
    paths: list[str] = []
    for directory, folders, files in os.walk(vault_resolved):
        # os.walk doesn't descend into symlinked folders by default.
        folders[:] = [folder for folder in folders if not folder.startswith(".")]
        for file_name in files:
            if file_name.startswith(".") or not file_name.endswith(".md"):
                continue
            file_path = Path(directory) / file_name
            try:
                resolved = file_path.resolve()
            except (OSError, RuntimeError):  # RuntimeError: a symlink loop
                continue
            if not resolved.is_relative_to(vault_resolved) or resolved.suffix != ".md":
                continue
            paths.append(file_path.relative_to(vault_resolved).as_posix())
    yield from sorted(paths)


def read_note(vault_root: Path, path: str) -> Note:
    file_path = resolve_note_path(vault_root, path)
    try:
        raw_content, version = _read_raw(file_path)
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
        version=version,
    )


# The keyword-only conditions are what push this past pylint's argument
# limit; each is optional and named at every call site.
def write_note(  # pylint: disable=too-many-arguments
    vault_root: Path,
    path: str,
    raw_content: str,
    *,
    must_not_exist: bool = False,
    must_exist: bool = False,
    expected_version: str | None = None,
) -> Note:
    """Save a note. Each condition is checked under the same `file_lock`
    as the write, so no other write can land between check and save:
    `must_not_exist` and `must_exist` on whether the file is there, and
    `expected_version` on the file still being the version the caller
    loaded. A note deleted since it was loaded fails `expected_version`
    too, as a conflict rather than a missing note."""
    file_path = resolve_note_path(vault_root, path)

    with file_lock(file_path):
        if must_not_exist and file_path.exists():
            raise NoteAlreadyExistsError(path)
        if must_exist and not file_path.exists():
            raise NoteNotFoundError(path)
        if expected_version is not None:
            try:
                current_version = note_version(file_path.read_bytes())
            except FileNotFoundError as exc:
                raise NoteVersionConflictError(path) from exc
            if current_version != expected_version:
                raise NoteVersionConflictError(path)
        return _render_and_write(file_path, path, raw_content)


def modify_note(vault_root: Path, path: str, change: Callable[[str], str]) -> Note:
    """Apply `change` to an existing note's raw content and save the result.

    The read and the write happen under the same `file_lock` critical
    section, so a concurrent writer to the same path cannot land between
    them and be silently overwritten -- the guarantee a client gets by
    calling read_note() and then write_note() itself does not hold.
    Exceptions raised by `change` propagate unchanged and leave the file
    untouched.
    """
    file_path = resolve_note_path(vault_root, path)
    with file_lock(file_path):
        try:
            raw_content = file_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise NoteNotFoundError(path) from exc
        return _render_and_write(file_path, path, change(raw_content))


def _render_and_write(file_path: Path, path: str, raw_content: str) -> Note:
    """Parse, stamp `created`/`updated` and save. Callers hold `file_path`'s lock."""
    ensure_vault_writable()
    parsed = parse_note(path, raw_content)

    now = datetime.now(UTC)
    if parsed.created is None:
        parsed.created = now
    parsed.updated = now

    rendered = render_note(parsed)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    version = _write_raw(file_path, rendered)

    return Note(
        path=path,
        title=parsed.title,
        tags=parsed.tags,
        created=parsed.created,
        updated=parsed.updated,
        content=rendered,
        version=version,
    )


def delete_note(vault_root: Path, path: str) -> None:
    ensure_vault_writable()
    file_path = resolve_note_path(vault_root, path)
    with file_lock(file_path):
        if not file_path.is_file():
            raise NoteNotFoundError(path)
        file_path.unlink()
        # Attachment-dir cleanup stays INSIDE this lock, not after it:
        # `move_note` moves a *different* note's attachments into this same
        # path while holding this same path's lock (see move_note's
        # `move_attachment_dir` call under `_locked_paths`). Deleting them
        # outside the lock let a concurrent move-into-this-path land its
        # attachments first, then have this call's unlocked cleanup
        # `shutil.rmtree` them out from under the just-moved-in note --
        # silent, unrecoverable attachment data loss with no error to
        # either caller. Sharing this path's lock with move_note's
        # attachment-dir mutation closes that race.
        delete_attachment_dir(vault_root, path)


def _retarget_other_notes(
    vault_root: Path,
    old_target: str,
    new_target: str,
    pending_moves: Mapping[str, str] | None = None,
) -> list[str]:
    """Repoint every OTHER note's links that targeted `old_target` so they
    resolve to `new_target` instead, and rewrite any of their wikilinks
    the move would otherwise send to a different note (see
    `retarget_wikilinks`). `pending_moves` is as in `NoteMove`. Returns
    the vault-relative paths of the notes that were actually rewritten."""
    retargeted: list[str] = []
    note_paths = list(iter_note_paths(vault_root))
    move = NoteMove.from_paths_after(old_target, new_target, note_paths, pending_moves)
    # Resolved once -- `vault_root` is invariant across the loop below, so
    # resolving it fresh on every iteration (as passing the raw `vault_root`
    # into `resolve_note_path` per-note would do) is redundant work
    # repeated once per note in the vault.
    vault_root_resolved = vault_root.resolve()
    for other_path in note_paths:
        if other_path == new_target:
            continue
        other_file = vault_root / other_path
        try:
            # The lock key MUST be the resolved path, not a bare join --
            # every other call site (write_note/delete_note/move_note)
            # locks on `resolve_note_path`'s output, and `file_lock` locks
            # on `Path` identity/hash with no normalization of its own
            # (see file_lock.py's module docstring). A relative or
            # symlinked `vault_root` would otherwise make this lock key
            # never collide with the SAME physical file's lock taken
            # elsewhere, silently defeating locking for exactly the race
            # this exists to close. This resolve call must stay INSIDE
            # this try/except: `resolve_note_path` raises for any other
            # note whose canonical path escapes the vault (e.g. a
            # symlink), and that failure is exactly one bad note's
            # problem -- it must not abort retargeting for every
            # remaining note in the vault.
            lock_path = resolve_note_path(vault_root_resolved, other_path)
            with file_lock(lock_path):
                other_raw = other_file.read_text(encoding="utf-8")
                other_parsed = parse_note(other_path, other_raw)

                # A note moved into a hidden folder (`.trash/`) is no longer
                # indexed, so markdown links pointing there would only be
                # dead. Leave them on the old path, as `retarget_wikilinks`
                # does, so they work again once the note is restored.
                new_body = (
                    other_parsed.body
                    if is_hidden_path(new_target)
                    else retarget_links(
                        other_parsed.body, other_path, old_target, new_target
                    )
                )
                source = move.logical_path(other_path)
                new_body = retarget_wikilinks(new_body, source, source, move)
                if new_body == other_parsed.body:
                    continue
                other_parsed.body = new_body
                other_parsed.updated = datetime.now(UTC)
                other_file.write_text(render_note(other_parsed), encoding="utf-8")
        except Exception:  # noqa: BLE001 -- one bad note must not abort the move
            # Covers both the read/parse step and the compute-and-write step:
            # a write failure partway through this loop (permission error,
            # disk full, a concurrent external edit) must not silently
            # strand an already-rewritten note out of `retargeted` -- the
            # caller (retarget_note_links's watcher-driven pairing path)
            # relies on this list to re-sync the index for exactly the
            # notes whose files actually changed on disk.
            logger.exception(
                "Failed to relink %s to %s; skipping", other_path, new_target
            )
            continue
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
    # A stem with spaces or similar is written percent-encoded in a plain
    # link and as it is in an angle-bracket one; each form is replaced by
    # the new stem in the same form.
    forms = [(old_stem, new_stem)]
    if format_link_target(old_stem) != old_stem:
        forms.append((format_link_target(old_stem), format_link_target(new_stem)))
    for old_form, new_form in forms:
        pattern = re.compile(rf"(?<![\w-]){re.escape(old_form)}\.attachments/")
        # Backslashes doubled: `sub` reads them in the replacement as escapes.
        body = pattern.sub(new_form.replace("\\", "\\\\") + ".attachments/", body)
    return body


def _rebase_own_links(
    vault_root: Path,
    body: str,
    moved: tuple[str, str],
    pending_moves: Mapping[str, str] | None = None,
) -> str:
    """A moved note's own links, rewritten so they still reach the notes
    they reached before the move: relative markdown links always (they're
    relative to the note's folder), wikilinks only where the new folder
    changes which same-named note they resolve to."""
    old_path, new_path = moved
    body = rebase_links(body, old_path, new_path)
    if "[[" not in body:
        return body
    move = NoteMove.from_paths_after(
        old_path, new_path, list(iter_note_paths(vault_root)), pending_moves
    )
    return retarget_wikilinks(body, old_path, new_path, move)


@contextmanager
def _locked_paths(*paths: Path) -> Iterator[None]:
    """Acquire `file_lock` for every distinct path in `paths`, in a
    fixed (sorted-by-string) order -- so two callers wanting the same
    set of paths always request them in the same order regardless of
    call-site argument order, and can't AB-BA deadlock on each other."""
    with ExitStack() as stack:
        for lock_path in sorted(set(paths), key=str):
            stack.enter_context(file_lock(lock_path))
        yield


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
    ensure_vault_writable()
    source = resolve_note_path(vault_root, path)
    destination = resolve_note_path(vault_root, new_path)
    is_relocation = source != destination

    # `source == destination` for a title-only update, so `_locked_paths`
    # collapses to a single lock there. This block (and only this block)
    # must be exited BEFORE `_retarget_other_notes` is called below --
    # see the module-level note in file_lock.py and this function's own
    # docstring for why holding these locks across that call would risk
    # a cross-move deadlock.
    with _locked_paths(source, destination):
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

        raw_content, version = _read_raw(destination)
        parsed = parse_note(new_path, raw_content)

        changed = False
        if is_relocation:
            if had_attachment_dir:
                rewritten_body = _rebase_attachment_references(
                    parsed.body, path, new_path
                )
                if rewritten_body != parsed.body:
                    parsed.body = rewritten_body
                    changed = True
            rebased_body = _rebase_own_links(vault_root, parsed.body, (path, new_path))
            if rebased_body != parsed.body:
                parsed.body = rebased_body
                changed = True
        if title is not None and title != parsed.title:
            parsed.title = title
            parsed.title_in_frontmatter = True
            changed = True

        if changed:
            parsed.updated = datetime.now(UTC)
            raw_content = render_note(parsed)
            version = _write_raw(destination, raw_content)

    # Locks released above -- `_retarget_other_notes` discovers and locks
    # its OWN set of paths (one at a time, per note), which must never
    # overlap in time with this move still holding source/destination, or
    # two concurrent cross-linked moves can form an AB-BA deadlock.
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
            version=version,
        ),
        retargeted,
    )


def retarget_note_links(
    vault_root: Path,
    old_path: str,
    new_path: str,
    pending_moves: Mapping[str, str] | None = None,
) -> tuple[Note, list[str]]:
    """Repoint links for a note that has already been relocated on disk
    from `old_path` to `new_path` (e.g. an external `mv` detected by the
    filesystem watcher as a rename), producing the same link-repointing
    outcome as `move_note`'s post-relocation steps -- without performing
    the physical file move itself.

    Rewrites the note's own outgoing relative links so they still resolve
    to the same absolute targets (they're relative to its own folder,
    which already changed on disk), and repoints every OTHER note's
    links that targeted `old_path` so they resolve to `new_path` instead.
    `pending_moves` maps notes the same batch also moved on disk, but
    whose moves are applied after this one, back to their old paths (see
    `NoteMove`), so a renamed folder doesn't confuse wikilink resolution.

    Also relocates the note's attachment folder (`<stem>.attachments/`,
    sibling to the note file), if any, so it travels with the note --
    mirroring `move_note`'s own attachment handling. If the rename also
    changed the note's filename stem, any literal
    `<old-stem>.attachments/` occurrence in the note's own body (e.g. an
    embedded `![](old-stem.attachments/abc.png)` reference) is rewritten
    to `<new-stem>.attachments/`. A failure relocating the attachment
    folder is logged and does not abort link-repointing -- but in that
    case the body is left referencing the *old* stem, since the folder
    never actually moved; rewriting the reference to a location nothing
    was relocated to would break a previously-working embed.

    Returns the (possibly rewritten) note now at `new_path`, and the
    vault-relative paths of any OTHER notes whose link text was
    rewritten, so the caller can keep the index in sync for those too.
    """
    ensure_vault_writable()
    destination = resolve_note_path(vault_root, new_path)

    with file_lock(destination):
        if not destination.is_file():
            raise NoteNotFoundError(new_path)

        had_attachment_dir = attachment_dir_for_note(vault_root, old_path).exists()
        attachment_moved = False
        if had_attachment_dir:
            try:
                move_attachment_dir(vault_root, old_path, new_path)
                attachment_moved = True
            except Exception:  # noqa: BLE001 -- link-repointing must still proceed
                logger.exception(
                    "Failed to relocate attachment dir for %s -> %s",
                    old_path,
                    new_path,
                )

        raw_content, version = _read_raw(destination)
        parsed = parse_note(new_path, raw_content)

        changed = False
        if attachment_moved:
            rewritten_body = _rebase_attachment_references(
                parsed.body, old_path, new_path
            )
            if rewritten_body != parsed.body:
                parsed.body = rewritten_body
                changed = True
        rebased_body = _rebase_own_links(
            vault_root, parsed.body, (old_path, new_path), pending_moves
        )
        if rebased_body != parsed.body:
            parsed.body = rebased_body
            changed = True
        if changed:
            parsed.updated = datetime.now(UTC)
            raw_content = render_note(parsed)
            version = _write_raw(destination, raw_content)

    # Lock released above -- must not be held across `_retarget_other_notes`,
    # which acquires its own per-note locks, for the same cross-move AB-BA
    # deadlock reason `move_note` releases source/destination before its
    # own call to `_retarget_other_notes` (see that function's comment).
    retargeted = _retarget_other_notes(vault_root, old_path, new_path, pending_moves)

    return (
        Note(
            path=new_path,
            title=parsed.title,
            tags=parsed.tags,
            created=parsed.created,
            updated=parsed.updated,
            content=raw_content,
            version=version,
        ),
        retargeted,
    )
