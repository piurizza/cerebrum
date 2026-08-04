from __future__ import annotations

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from cerebrum.index.db import list_notes as list_notes_in_index
from cerebrum.index.db import search_notes as search_notes_in_index
from cerebrum.mcp.context import get_db
from cerebrum.notes.models import Note, NoteMeta
from cerebrum.notes.parser import InvalidNoteContentError
from cerebrum.notes.service import InvalidNotePathError, NoteNotFoundError, read_note
from cerebrum.settings import get_settings

_READ_ONLY_ANNOTATIONS = {"readOnlyHint": True, "idempotentHint": True}


def register_notes_tools(mcp: FastMCP, app: FastAPI) -> None:
    """Register `list-notes`, `get-note`, and `search-notes` (R1) against
    `mcp`, closing over `app` (KTD8) to reach the shared index connection
    and vault path the same way REST routes do."""

    @mcp.tool(
        name="list-notes",
        description=(
            "Call this to see every note currently in the vault. Returns each "
            "note's path, title, tags, and timestamps -- not its content (use "
            "get-note for that). Reads from the search index, which can lag "
            "slightly behind a just-completed write."
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
            raise ToolError(f"'{path}' is not a valid note path") from exc
        except InvalidNoteContentError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(
        name="search-notes",
        description=(
            "Call this to find notes whose title or content matches a query, "
            "before reading the full one with get-note. Returns matching "
            "notes' metadata, ranked by relevance -- not their content. An "
            "empty query or no matches returns an empty list, not an error."
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def search_notes(query: str) -> list[NoteMeta]:
        return search_notes_in_index(get_db(app), query)
