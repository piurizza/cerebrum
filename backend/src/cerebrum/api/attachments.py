from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cerebrum.attachments.service import (
    AttachmentTooLargeError,
    InvalidAttachmentPathError,
    UnsupportedAttachmentTypeError,
    resolve_attachment_path,
    save_attachment,
)
from cerebrum.notes.service import InvalidNotePathError, resolve_note_path
from cerebrum.settings import get_settings

router = APIRouter(prefix="/attachments")


class AttachmentUploadResponse(BaseModel):
    """A named schema for `upload_attachment`'s response -- previously a
    bare `dict[str, str]`, which OpenAPI (and therefore the frontend's
    generated types, see `scripts/export_openapi_schema.py`) can only
    describe as a generic string-keyed object, not a `{path: string}`
    shape. Wire format is unchanged; this only gives the existing shape a
    name."""

    path: str


@router.post("", response_model=AttachmentUploadResponse)
async def upload_attachment(
    note_path: str, request: Request
) -> AttachmentUploadResponse:
    """Accept a raw image body (no multipart/`UploadFile`) for an existing
    note and persist it via `attachments/service.py`'s `save_attachment`.

    Deliberately reads the body as a raw stream rather than binding an
    `UploadFile`/`File()` parameter: FastAPI's multipart binding fully
    parses/spools the request body before any application code (and
    therefore any size check) runs, which would defeat
    `max_attachment_size_bytes` for exactly the oversized-upload case this
    endpoint exists to reject.
    """
    settings = get_settings()

    try:
        note_file = resolve_note_path(settings.cerebrum_vault_path, note_path)
    except InvalidNotePathError as exc:
        raise HTTPException(status_code=400, detail="Invalid note path") from exc
    if not note_file.is_file():
        raise HTTPException(status_code=404, detail="Note not found")

    # Cheap early-out on the client-declared Content-Length, before
    # touching request.stream() at all -- the header is untrusted (a
    # client can lie about it) so this is an optimization, not the sole
    # guard; save_attachment's own running-total check below is what
    # actually enforces the cap against the real bytes received.
    declared_size = request.headers.get("content-length")
    if declared_size is not None:
        try:
            declared_bytes = int(declared_size)
        except ValueError:
            declared_bytes = None
        if (
            declared_bytes is not None
            and declared_bytes > settings.max_attachment_size_bytes
        ):
            raise HTTPException(status_code=413, detail="Attachment too large")

    content_type = request.headers.get("content-type", "")

    try:
        relative_path = await save_attachment(
            settings.cerebrum_vault_path,
            note_path,
            content_type,
            request.stream(),
            settings,
        )
    except UnsupportedAttachmentTypeError as exc:
        raise HTTPException(
            status_code=415, detail="Unsupported attachment type"
        ) from exc
    except AttachmentTooLargeError as exc:
        raise HTTPException(status_code=413, detail="Attachment too large") from exc

    return AttachmentUploadResponse(path=relative_path)


@router.get("/{path:path}")
def get_attachment(path: str) -> FileResponse:
    settings = get_settings()
    try:
        resolved = resolve_attachment_path(settings.cerebrum_vault_path, path)
    except InvalidAttachmentPathError as exc:
        raise HTTPException(status_code=404, detail="Attachment not found") from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")

    # media_type is inferred from the server-assigned extension
    # (.png/.jpg/.gif/.webp -- see _EXTENSION_BY_CONTENT_TYPE in
    # attachments/service.py). nosniff blocks a browser from
    # second-guessing that Content-Type via content sniffing.
    return FileResponse(resolved, headers={"X-Content-Type-Options": "nosniff"})
