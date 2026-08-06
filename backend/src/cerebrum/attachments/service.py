from __future__ import annotations

import hashlib
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from cerebrum.settings import Settings

# content_type -> filename extension used when writing an attachment to
# disk. jpg (not jpeg) matches common convention for file extensions even
# though the MIME subtype itself is "jpeg".
_EXTENSION_BY_CONTENT_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class InvalidAttachmentPathError(Exception):
    pass


class AttachmentTooLargeError(Exception):
    pass


class UnsupportedAttachmentTypeError(Exception):
    pass


def _magic_bytes_match(content_type: str, data: bytes) -> bool:
    """Check `data`'s leading bytes against the signature expected for
    `content_type`. Guards against a spoofed Content-Type header (client
    declares `image/png` but sends arbitrary bytes)."""
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/gif":
        return data.startswith(b"GIF87a") or data.startswith(b"GIF89a")
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def attachment_dir_for_note(vault_root: Path, note_path: str) -> Path:
    """Return the attachment folder for a note, sibling to the note itself.

    Precondition: `note_path` must already have passed
    `notes/service.py`'s `resolve_note_path` -- this function does not
    itself re-validate traversal safety, it inherits that guarantee from
    its caller.
    """
    note_file = vault_root / note_path
    return note_file.parent / f"{note_file.stem}.attachments"


def resolve_attachment_path(vault_root: Path, attachment_path: str) -> Path:
    """Resolve a vault-relative attachment path to an absolute filesystem
    path.

    Mirrors `notes/service.py`'s `resolve_note_path` traversal-safety
    logic exactly, except the suffix check is replaced with a check that
    the path's parent directory name ends in `.attachments`. This is the
    validation boundary for untrusted input (e.g. the GET route) -- unlike
    `attachment_dir_for_note`, it makes no assumption the caller already
    validated `attachment_path`.
    """
    vault_resolved = vault_root.resolve()
    candidate = (vault_resolved / attachment_path).resolve()
    if candidate != vault_resolved and vault_resolved not in candidate.parents:
        raise InvalidAttachmentPathError(attachment_path)
    if not candidate.parent.name.endswith(".attachments"):
        raise InvalidAttachmentPathError(attachment_path)
    return candidate


async def save_attachment(
    vault_root: Path,
    note_path: str,
    content_type: str,
    chunks: AsyncIterator[bytes],
    settings: Settings,
) -> str:
    """Validate, hash, and persist an uploaded attachment for a note.

    Precondition: `note_path` must already have passed
    `notes/service.py`'s `resolve_note_path`.

    Rejects disallowed content types before consuming `chunks`, and
    rejects oversized uploads (per `settings.max_attachment_size_bytes`)
    as soon as the running total crosses the limit -- before anything is
    written to disk. Once fully read, the accumulated bytes' magic-byte
    signature is checked against `content_type` to catch a spoofed
    header. The destination filename is the SHA-256 hex digest of the
    content, so pasting byte-identical content twice is a no-op write
    (content-addressed dedup) rather than a race between two writers.

    Returns the path relative to the note's own directory (what gets
    embedded in the note's markdown), not the vault-relative path.
    """
    if content_type not in _EXTENSION_BY_CONTENT_TYPE:
        raise UnsupportedAttachmentTypeError(content_type)

    data = bytearray()
    total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > settings.max_attachment_size_bytes:
            raise AttachmentTooLargeError(total)
        data.extend(chunk)

    if not _magic_bytes_match(content_type, bytes(data)):
        raise UnsupportedAttachmentTypeError(content_type)

    digest = hashlib.sha256(data).hexdigest()
    extension = _EXTENSION_BY_CONTENT_TYPE[content_type]
    filename = f"{digest}{extension}"

    attachment_dir = attachment_dir_for_note(vault_root, note_path)
    attachment_dir.mkdir(parents=True, exist_ok=True)
    destination = attachment_dir / filename
    if not destination.exists():
        destination.write_bytes(bytes(data))

    return f"{attachment_dir.name}/{filename}"


def move_attachment_dir(
    vault_root: Path, old_note_path: str, new_note_path: str
) -> None:
    """Relocate a note's attachment folder alongside a note move.

    No-op if the note has no attachment folder.
    """
    old_dir = attachment_dir_for_note(vault_root, old_note_path)
    if not old_dir.exists():
        return
    new_dir = attachment_dir_for_note(vault_root, new_note_path)
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_dir), str(new_dir))


def delete_attachment_dir(vault_root: Path, note_path: str) -> None:
    """Remove a note's attachment folder and everything in it.

    No-op if the note has no attachment folder.
    """
    attachment_dir = attachment_dir_for_note(vault_root, note_path)
    if attachment_dir.exists():
        shutil.rmtree(attachment_dir)
