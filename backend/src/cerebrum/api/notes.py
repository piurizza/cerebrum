from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from cerebrum.api.deps import get_db, require_writable_vault
from cerebrum.index.db import list_notes
from cerebrum.index.indexer import remove_note as remove_note_from_index
from cerebrum.index.indexer import upsert_note as upsert_note_in_index
from cerebrum.notes.models import Note, NoteMeta
from cerebrum.notes.parser import InvalidNoteContentError
from cerebrum.notes.service import (
    InvalidNotePathError,
    NoteAlreadyExistsError,
    NoteNotFoundError,
    NoteVersionConflictError,
    delete_note,
    move_note,
    read_note,
    write_note,
)
from cerebrum.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


class MoveNoteRequest(BaseModel):
    new_path: str
    title: str | None = None


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


@router.put(
    "/notes/{path:path}",
    response_model=Note,
    dependencies=[Depends(require_writable_vault)],
)
async def put_note(
    path: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    x_base_version: str | None = Header(
        default=None,
        alias="X-Base-Version",
        description=(
            "The `version` the note had when it was loaded. The save is "
            "refused with 412 if the note changed or was deleted since."
        ),
    ),
    x_create_only: str | None = Header(
        default=None,
        alias="X-Create-Only",
        description="`1` to refuse the save with 412 if a note already exists.",
    ),
) -> Note:
    # Custom headers rather than If-Match/If-None-Match: nginx's
    # not-modified filter evaluates those itself, and on a proxied 200
    # without an ETag it can turn a save that already happened into a 412.
    if x_create_only not in (None, "1"):
        raise HTTPException(status_code=400, detail="X-Create-Only must be 1")
    settings = get_settings()
    raw_content = (await request.body()).decode("utf-8")
    try:
        note = write_note(
            settings.cerebrum_vault_path,
            path,
            raw_content,
            must_not_exist=x_create_only == "1",
            expected_version=x_base_version,
        )
    except NoteAlreadyExistsError as exc:
        raise HTTPException(
            status_code=412, detail=f"A note already exists at {exc}"
        ) from exc
    except NoteVersionConflictError as exc:
        raise HTTPException(
            status_code=412, detail="The note changed since it was loaded"
        ) from exc
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


@router.delete(
    "/notes/{path:path}",
    status_code=204,
    dependencies=[Depends(require_writable_vault)],
)
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


@router.post(
    "/notes/{path:path}/move",
    response_model=Note,
    dependencies=[Depends(require_writable_vault)],
)
def move_note_endpoint(
    path: str, body: MoveNoteRequest, db: sqlite3.Connection = Depends(get_db)
) -> Note:
    settings = get_settings()
    try:
        note, retargeted_paths = move_note(
            settings.cerebrum_vault_path, path, body.new_path, title=body.title
        )
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Note not found") from exc
    except NoteAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409, detail=f"A note already exists at {exc}"
        ) from exc
    except InvalidNotePathError as exc:
        raise HTTPException(status_code=400, detail="Invalid note path") from exc
    except InvalidNoteContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # The file(s) (source of truth) are already saved -- the moved note
    # itself, plus any other note whose links were retargeted. An
    # index-write failure here must not turn a successful move into a
    # misleading error response -- the index is a disposable cache and
    # self-heals on the next startup rescan (see SPEC.md).
    try:
        remove_note_from_index(db, path)
        upsert_note_in_index(db, settings.cerebrum_vault_path, body.new_path)
        for retargeted_path in retargeted_paths:
            upsert_note_in_index(db, settings.cerebrum_vault_path, retargeted_path)
    except Exception:  # noqa: BLE001 -- index is a rebuildable cache (see SPEC.md)
        logger.exception(
            "Failed to update index after moving %s to %s", path, body.new_path
        )
    return note
