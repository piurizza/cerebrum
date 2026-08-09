from __future__ import annotations

import logging

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from cerebrum.index.db import list_notes as list_notes_in_index
from cerebrum.index.db import search_notes as search_notes_in_index
from cerebrum.index.indexer import upsert_note as upsert_note_in_index
from cerebrum.mcp.context import INDEX_LAG_WARNING, get_db
from cerebrum.notes.models import Note, NoteMeta
from cerebrum.notes.parser import InvalidNoteContentError
from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteAlreadyExistsError,
    NoteNotFoundError,
    read_note,
    write_note,
)
from cerebrum.settings import get_settings

logger = logging.getLogger(__name__)

_READ_ONLY_ANNOTATIONS = {"readOnlyHint": True, "idempotentHint": True}
_CREATE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
}
_UPDATE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
}
_WHOLE_DOCUMENT_WARNING = (
    "Replaces the whole document body -- this is not a patch or append. If "
    "you don't already hold the note's full current content (including its "
    "frontmatter, e.g. tags), call get-note first or you will lose it."
)


def _invalid_path_error(path: str) -> ToolError:
    return ToolError(f"'{path}' is not a valid note path")


def register_notes_tools(mcp: FastMCP, app: FastAPI) -> None:
    """Register `list-notes`, `get-note`, and `search-notes` (R1) against
    `mcp`, closing over `app` (KTD8) to reach the shared index connection
    and vault path the same way REST routes do."""

    @mcp.tool(
        name="list-notes",
        description=(
            "Call this to see every note currently in the vault. Returns each "
            "note's path, title, tags, and timestamps -- not its content (use "
            f"get-note for that). {INDEX_LAG_WARNING}"
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def list_notes() -> list[NoteMeta]:
        return list_notes_in_index(get_db(app))

    @mcp.tool(
        name="get-note",
        description=(
            "Call this to read a specific note's full content by its "
            "vault-relative path (e.g. 'projects/cerebrum.md'). Fails with a "
            "clear error if no note exists at that path."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_note(path: str) -> Note:
        settings = get_settings()
        try:
            return read_note(settings.cerebrum_vault_path, path)
        except NoteNotFoundError as exc:
            raise ToolError(f"No note exists at '{path}'") from exc
        except InvalidNotePathError as exc:
            raise _invalid_path_error(path) from exc
        except InvalidNoteContentError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(
        name="search-notes",
        description=(
            "Call this to find notes whose title or content matches a query, "
            "before reading the full one with get-note. Returns matching "
            "notes' metadata, ranked by relevance -- not their content. An "
            "empty query or no matches returns an empty list, not an error. "
            f"{INDEX_LAG_WARNING}"
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def search_notes(query: str = "") -> list[NoteMeta]:
        return search_notes_in_index(get_db(app), query)

    @mcp.tool(
        name="create-note",
        description=(
            "Call this to create a brand-new note at a vault-relative path "
            "(e.g. 'projects/cerebrum.md'). Fails with a clear error if a "
            "note already exists there (including one that's currently "
            "malformed) -- use update-note to change an existing one "
            f"instead. {_WHOLE_DOCUMENT_WARNING}"
        ),
        annotations=_CREATE_ANNOTATIONS,
    )
    def create_note(path: str, content: str) -> Note:
        try:
            return _write_and_sync_index(app, path, content, must_not_exist=True)
        except NoteAlreadyExistsError as exc:
            raise ToolError(f"A note already exists at '{path}'") from exc

    @mcp.tool(
        name="update-note",
        description=(
            "Call this to replace an existing note's content by its "
            "vault-relative path. Fails with a clear error if no note "
            "exists there -- use create-note for a new one instead. "
            f"{_WHOLE_DOCUMENT_WARNING}"
        ),
        annotations=_UPDATE_ANNOTATIONS,
    )
    def update_note(path: str, content: str) -> Note:
        try:
            return _write_and_sync_index(app, path, content, must_exist=True)
        except NoteNotFoundError as exc:
            raise ToolError(f"No note exists at '{path}'") from exc


def _write_and_sync_index(
    app: FastAPI,
    path: str,
    content: str,
    *,
    must_not_exist: bool = False,
    must_exist: bool = False,
) -> Note:
    # create-note/update-note widen write_note()'s caller population from
    # the trusted local frontend to remote third-party LLM clients. Verified
    # safe: python-frontmatter's default YAML handler parses frontmatter
    # with yaml.SafeLoader (see frontmatter/default_handlers.py), not an
    # executing/unsafe loader -- a one-time check, not a per-call assertion.
    #
    # must_not_exist/must_exist are threaded straight through to write_note,
    # whose own file_lock critical section evaluates them atomically with
    # the write itself -- closing the race an earlier, separate unlocked
    # read_note() pre-check here could not (R5). NoteAlreadyExistsError/
    # NoteNotFoundError raised by that check are intentionally NOT caught
    # here; they propagate to create_note/update_note, which translate them
    # to the same ToolError messages the old pre-check produced.
    settings = get_settings()
    try:
        note = write_note(
            settings.cerebrum_vault_path,
            path,
            content,
            must_not_exist=must_not_exist,
            must_exist=must_exist,
        )
    except InvalidNotePathError as exc:
        raise _invalid_path_error(path) from exc
    except InvalidNoteContentError as exc:
        raise ToolError(str(exc)) from exc

    # The file (source of truth) is already saved. An index-write failure
    # here must not turn a successful save into a misleading tool error --
    # the index is a disposable cache and self-heals on the next startup
    # rescan (see SPEC.md), mirroring `api/notes.py`'s `put_note` idiom.
    try:
        upsert_note_in_index(get_db(app), settings.cerebrum_vault_path, path)
    except Exception:  # noqa: BLE001 -- index is a rebuildable cache (see SPEC.md)
        logger.exception("Failed to update index for %s after a successful write", path)
    return note
