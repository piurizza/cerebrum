from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from cerebrum.attachments.service import (
    AttachmentTooLargeError,
    InvalidAttachmentPathError,
    UnsupportedAttachmentTypeError,
    attachment_dir_for_note,
    delete_attachment_dir,
    move_attachment_dir,
    resolve_attachment_path,
    save_attachment,
)
from cerebrum.settings import Settings

# Minimal valid PNG signature -- the 8-byte header is all
# `_magic_bytes_match` inspects, so it doesn't need to be a decodable image.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"rest-of-file-does-not-matter-for-this-test"


def _settings(max_attachment_size_bytes: int = 10_000_000) -> Settings:
    return Settings(
        auth_jwt_secret="x" * 32,
        auth_setup_token="y" * 32,
        max_attachment_size_bytes=max_attachment_size_bytes,
    )


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    # Split into a couple of chunks so the running-total accumulation
    # logic in save_attachment is actually exercised, not just a single
    # yield.
    midpoint = len(data) // 2
    if midpoint:
        yield data[:midpoint]
        yield data[midpoint:]
    else:
        yield data


def test_save_attachment_writes_file_under_note_attachments_dir(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")

    relative = asyncio.run(
        save_attachment(vault, note_path, "image/png", _chunks(_PNG_BYTES), _settings())
    )

    assert relative.startswith("idea.attachments/")
    assert relative.endswith(".png")

    note_dir = (vault / note_path).parent
    resolved = (note_dir / relative).resolve()
    assert resolved.is_file()
    assert resolved.read_bytes() == _PNG_BYTES
    assert resolved.parent == attachment_dir_for_note(vault, note_path)


def test_save_attachment_dedups_identical_content(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")
    settings = _settings()

    first = asyncio.run(
        save_attachment(vault, note_path, "image/png", _chunks(_PNG_BYTES), settings)
    )
    attachment_dir = attachment_dir_for_note(vault, note_path)
    destination = attachment_dir / Path(first).name
    mtime_after_first = destination.stat().st_mtime_ns

    second = asyncio.run(
        save_attachment(vault, note_path, "image/png", _chunks(_PNG_BYTES), settings)
    )

    assert second == first
    assert list(attachment_dir.iterdir()) == [destination]
    assert destination.stat().st_mtime_ns == mtime_after_first


def test_save_attachment_rejects_oversized_content(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")
    settings = _settings(max_attachment_size_bytes=10)

    with pytest.raises(AttachmentTooLargeError):
        asyncio.run(
            save_attachment(
                vault, note_path, "image/png", _chunks(_PNG_BYTES), settings
            )
        )

    assert not attachment_dir_for_note(vault, note_path).exists()


def test_save_attachment_rejects_disallowed_content_type(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")

    with pytest.raises(UnsupportedAttachmentTypeError):
        asyncio.run(
            save_attachment(
                vault, note_path, "application/pdf", _chunks(_PNG_BYTES), _settings()
            )
        )

    assert not attachment_dir_for_note(vault, note_path).exists()


def test_save_attachment_rejects_spoofed_content_type(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")
    fake_png = b"not actually a png, just plain text"

    with pytest.raises(UnsupportedAttachmentTypeError):
        asyncio.run(
            save_attachment(
                vault, note_path, "image/png", _chunks(fake_png), _settings()
            )
        )

    assert not attachment_dir_for_note(vault, note_path).exists()


def test_resolve_attachment_path_rejects_vault_escape(vault: Path) -> None:
    with pytest.raises(InvalidAttachmentPathError):
        resolve_attachment_path(vault, "../../etc/passwd")


def test_resolve_attachment_path_rejects_non_attachments_parent(vault: Path) -> None:
    with pytest.raises(InvalidAttachmentPathError):
        resolve_attachment_path(vault, "notes/some-file.png")


def test_resolve_attachment_path_accepts_valid_attachment(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")
    relative = asyncio.run(
        save_attachment(vault, note_path, "image/png", _chunks(_PNG_BYTES), _settings())
    )

    resolved = resolve_attachment_path(vault, f"{relative}")

    assert resolved.is_file()
    assert resolved == attachment_dir_for_note(vault, note_path) / Path(relative).name


def test_move_attachment_dir_is_noop_when_no_attachments(vault: Path) -> None:
    (vault / "idea.md").write_text("# Idea\n", encoding="utf-8")

    move_attachment_dir(vault, "idea.md", "renamed.md")  # must not raise

    assert not attachment_dir_for_note(vault, "renamed.md").exists()


def test_move_attachment_dir_relocates_existing_folder(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")
    relative = asyncio.run(
        save_attachment(vault, note_path, "image/png", _chunks(_PNG_BYTES), _settings())
    )
    old_dir = attachment_dir_for_note(vault, note_path)
    filename = Path(relative).name

    move_attachment_dir(vault, note_path, "renamed.md")

    new_dir = attachment_dir_for_note(vault, "renamed.md")
    assert not old_dir.exists()
    assert (new_dir / filename).is_file()
    assert (new_dir / filename).read_bytes() == _PNG_BYTES


def test_delete_attachment_dir_removes_folder_and_contents(vault: Path) -> None:
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")
    asyncio.run(
        save_attachment(vault, note_path, "image/png", _chunks(_PNG_BYTES), _settings())
    )
    attachment_dir = attachment_dir_for_note(vault, note_path)
    assert attachment_dir.exists()

    delete_attachment_dir(vault, note_path)

    assert not attachment_dir.exists()


def test_delete_attachment_dir_is_noop_when_no_attachments(vault: Path) -> None:
    (vault / "idea.md").write_text("# Idea\n", encoding="utf-8")

    delete_attachment_dir(vault, "idea.md")  # must not raise


def test_attachment_dir_for_note_resolves_internal_dotdot_without_stray_dir(
    vault: Path,
) -> None:
    """Regression: a `note_path` containing an internal `..` segment that
    still resolves safely inside the vault (e.g. because the caller
    already validated it via `resolve_note_path`) must not leave a stray
    directory behind -- `attachment_dir_for_note` has to resolve the path
    before deriving `.parent`/`.stem`, since plain `/` joins don't
    normalize `..`."""
    (vault / "bar.md").write_text("# Bar\n", encoding="utf-8")

    attachment_dir_for_note(vault, "foo/../bar.md")

    assert not (vault / "foo").exists()


def test_move_attachment_dir_merges_into_pre_existing_destination(vault: Path) -> None:
    """Regression: if the destination attachment folder already exists
    (orphaned content with no note of its own -- the target note path
    itself is guaranteed free by move_note's NoteAlreadyExistsError check),
    `shutil.move` alone would nest the source folder inside it instead of
    merging, silently orphaning the just-rewritten embed reference."""
    note_path = "idea.md"
    (vault / note_path).write_text("# Idea\n", encoding="utf-8")
    relative = asyncio.run(
        save_attachment(vault, note_path, "image/png", _chunks(_PNG_BYTES), _settings())
    )
    filename = Path(relative).name

    new_dir = attachment_dir_for_note(vault, "renamed.md")
    new_dir.mkdir(parents=True)
    (new_dir / "orphan.png").write_bytes(b"stale-orphaned-content")

    move_attachment_dir(vault, note_path, "renamed.md")

    assert not attachment_dir_for_note(vault, note_path).exists()
    assert (new_dir / filename).is_file()
    assert (new_dir / filename).read_bytes() == _PNG_BYTES
    assert (new_dir / "orphan.png").is_file()
    # Not nested one level too deep under new_dir.
    assert not (new_dir / "idea.attachments").exists()
