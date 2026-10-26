from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cerebrum.attachments.service import (
    delete_attachment_dir,
    move_attachment_dir,
    save_attachment,
)
from cerebrum.notes.service import (
    delete_note,
    modify_note,
    move_note,
    retarget_note_links,
    write_note,
)
from cerebrum.read_only import VaultReadOnlyError
from cerebrum.settings import get_settings

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"rest-of-file-does-not-matter-for-this-test"
_READ_ONLY = {"detail": "This vault is read-only"}


def _snapshot(vault: Path) -> dict[str, str]:
    """Every file and folder under `vault`, files mapped to their SHA-256 --
    any write, new folder or deletion changes it."""
    return {
        entry.relative_to(vault).as_posix(): (
            hashlib.sha256(entry.read_bytes()).hexdigest() if entry.is_file() else "/"
        )
        for entry in vault.rglob("*")
    }


@pytest.fixture
def seeded_vault(vault: Path) -> dict[str, str]:
    """Notes written before the app starts, so the startup scan indexes
    them. Returns the vault's snapshot from before startup."""
    (vault / "a.md").write_text(
        "---\ntitle: A\n---\nSee [B](b.md).\n\n- [ ] buy milk\n", encoding="utf-8"
    )
    (vault / "b.md").write_text("---\ntitle: B\n---\nBravo body\n", encoding="utf-8")
    (vault / "a.attachments").mkdir()
    (vault / "a.attachments" / "x.png").write_bytes(_PNG_BYTES)
    return _snapshot(vault)


@pytest.fixture
def ro_client(
    seeded_vault: dict[str, str], authenticated_read_only_client: TestClient
) -> TestClient:
    """`seeded_vault` is listed first so the notes exist before the app
    starts."""
    del seeded_vault
    return authenticated_read_only_client


def test_note_and_attachment_writes_are_refused(ro_client: TestClient) -> None:
    responses = [
        ro_client.put("/api/notes/a.md", content="overwritten"),
        ro_client.put("/api/notes/new.md", content="new"),
        ro_client.delete("/api/notes/a.md"),
        ro_client.post("/api/notes/a.md/move", json={"new_path": "c.md"}),
        ro_client.post(
            "/api/attachments",
            params={"note_path": "a.md"},
            content=_PNG_BYTES,
            headers={"Content-Type": "image/png"},
        ),
    ]

    for response in responses:
        assert response.status_code == 403
        assert response.json() == _READ_ONLY


def test_conditional_note_saves_are_refused_before_the_precondition(
    ro_client: TestClient,
) -> None:
    # A stale version or an existing note would be a 412 from the handler;
    # a 403 proves the read-only refusal runs first.
    responses = [
        ro_client.put(
            "/api/notes/a.md", content="mine", headers={"X-Base-Version": "stale"}
        ),
        ro_client.put(
            "/api/notes/a.md", content="mine", headers={"X-Create-Only": "1"}
        ),
    ]

    for response in responses:
        assert response.status_code == 403
        assert response.json() == _READ_ONLY


def test_upload_is_refused_before_its_size_is_checked(ro_client: TestClient) -> None:
    # A declared size over the cap would be a 413 from the handler; a 403
    # proves the refusal runs first, so the body is never read.
    response = ro_client.post(
        "/api/attachments",
        params={"note_path": "a.md"},
        content=_PNG_BYTES,
        headers={"Content-Type": "image/png", "content-length": str(10_000_001)},
    )

    assert response.status_code == 403


def test_reads_still_work(ro_client: TestClient) -> None:
    notes = ro_client.get("/api/notes")
    assert notes.status_code == 200
    assert {note["path"] for note in notes.json()} == {"a.md", "b.md"}

    note = ro_client.get("/api/notes/b.md")
    assert note.status_code == 200
    assert "Bravo body" in note.json()["content"]

    search = ro_client.get("/api/search", params={"q": "bravo"})
    assert search.status_code == 200
    assert [hit["path"] for hit in search.json()] == ["b.md"]

    graph = ro_client.get("/api/graph")
    assert graph.status_code == 200

    tasks = ro_client.get("/api/tasks")
    assert tasks.status_code == 200
    assert [task["text"] for task in tasks.json()] == ["buy milk"]

    backlinks = ro_client.get("/api/notes/b.md/backlinks")
    assert backlinks.status_code == 200
    assert [hit["path"] for hit in backlinks.json()] == ["a.md"]

    attachment = ro_client.get("/api/attachments/a.attachments/x.png")
    assert attachment.status_code == 200


def test_account_writes_still_work(ro_client: TestClient) -> None:
    # Tokens live in the accounts database, outside the vault.
    response = ro_client.post("/api/tokens", json={"name": "reader"})

    assert response.status_code == 201


def test_the_vault_is_byte_for_byte_unchanged(
    seeded_vault: dict[str, str], ro_client: TestClient, vault: Path
) -> None:
    # Startup (index, accounts database) and every refused write leave no
    # trace in the vault -- not even a `.cerebrum/` folder.
    ro_client.put("/api/notes/a.md", content="overwritten")
    ro_client.delete("/api/notes/b.md")
    ro_client.post("/api/notes/a.md/move", json={"new_path": "c.md"})
    ro_client.post(
        "/api/attachments",
        params={"note_path": "a.md"},
        content=_PNG_BYTES,
        headers={"Content-Type": "image/png"},
    )
    ro_client.post("/api/tokens", json={"name": "reader"})
    ro_client.get("/api/notes")

    assert _snapshot(vault) == seeded_vault


async def _chunks() -> AsyncIterator[bytes]:
    yield _PNG_BYTES


_SERVICE_WRITES: dict[str, Callable[[Path], object]] = {
    "write_note": lambda vault: write_note(vault, "a.md", "overwritten"),
    "modify_note": lambda vault: modify_note(vault, "a.md", str.upper),
    "delete_note": lambda vault: delete_note(vault, "a.md"),
    "move_note": lambda vault: move_note(vault, "a.md", "c.md"),
    "retarget_note_links": lambda vault: retarget_note_links(vault, "a.md", "b.md"),
    "save_attachment": lambda vault: asyncio.run(
        save_attachment(vault, "b.md", "image/png", _chunks(), get_settings())
    ),
    "move_attachment_dir": lambda vault: move_attachment_dir(vault, "a.md", "c.md"),
    "delete_attachment_dir": lambda vault: delete_attachment_dir(vault, "a.md"),
}


@pytest.mark.parametrize("write", _SERVICE_WRITES.values(), ids=_SERVICE_WRITES)
def test_service_layer_refuses_vault_writes(
    seeded_vault: dict[str, str],
    read_only_env: Path,
    vault: Path,
    write: Callable[[Path], object],
) -> None:
    # The net under the 403s and the missing MCP tools: a write path that
    # forgets both still can't touch the vault.
    del read_only_env
    with pytest.raises(VaultReadOnlyError):
        write(vault)

    assert _snapshot(vault) == seeded_vault
