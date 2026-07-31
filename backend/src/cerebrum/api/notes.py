from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from cerebrum.api.deps import get_db
from cerebrum.index.db import list_notes
from cerebrum.index.indexer import remove_note as remove_note_from_index
from cerebrum.index.indexer import upsert_note as upsert_note_in_index
from cerebrum.notes.models import Note, NoteMeta
from cerebrum.notes.parser import InvalidNoteContentError
from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteNotFoundError,
    delete_note,
    read_note,
    write_note,
)
from cerebrum.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/notes", response_model=list[NoteMeta])
def list_all_notes(db: sqlite3.Connection = Depends(get_db)) -> list[NoteMeta]:
    return list_notes(db)


@router.get("/notes/{path:path}", response_model=Note)
def get_note(path: str) -> Note:
    settings = get_settings()
    try:
        return read_note(settings.cerebrum_vault_path, path)
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Note not found") from exc
    except InvalidNotePathError as exc:
        raise HTTPException(status_code=400, detail="Invalid note path") from exc
    except InvalidNoteContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/notes/{path:path}", response_model=Note)
async def put_note(
    path: str, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> Note:
    settings = get_settings()
    raw_content = (await request.body()).decode("utf-8")
    try:
        note = write_note(settings.cerebrum_vault_path, path, raw_content)
    except InvalidNotePathError as exc:
        raise HTTPException(status_code=400, detail="Invalid note path") from exc
    except InvalidNoteContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # The file (source of truth) is already saved. An index-write failure
    # here must not turn a successful save into a misleading error
    # response -- the index is a disposable cache and self-heals on the
    # next startup rescan (see SPEC.md).
    try:
        upsert_note_in_index(db, settings.cerebrum_vault_path, path)
    except Exception:  # noqa: BLE001 -- index is a rebuildable cache (see SPEC.md)
        logger.exception("Failed to update index for %s after a successful write", path)
    return note


@router.delete("/notes/{path:path}", status_code=204)
def delete_note_endpoint(
    path: str, db: sqlite3.Connection = Depends(get_db)
) -> Response:
    settings = get_settings()
    try:
        delete_note(settings.cerebrum_vault_path, path)
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Note not found") from exc
    except InvalidNotePathError as exc:
        raise HTTPException(status_code=400, detail="Invalid note path") from exc

    try:
        remove_note_from_index(db, path)
    except Exception:  # noqa: BLE001 -- index is a rebuildable cache (see SPEC.md)
        logger.exception(
            "Failed to update index for %s after a successful delete", path
        )
    return Response(status_code=204)
