from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from cerebrum.main import create_app
from cerebrum.settings import get_settings
from tests.mcp_test_support import issue_test_access_token

# Minimal valid PNG signature -- matches test_attachments_service.py's
# convention: the 8-byte header is all `_magic_bytes_match` inspects, so
# it doesn't need to be a decodable image.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"rest-of-file-does-not-matter-for-this-test"


def _create_note(client: TestClient, path: str = "idea.md") -> None:
    response = client.put(f"/api/notes/{path}", content="# Idea\n")
    assert response.status_code == 200


def _upload(
    client: TestClient, note_path: str, content: bytes = _PNG_BYTES
) -> httpx.Response:
    return client.post(
        "/api/attachments",
        params={"note_path": note_path},
        content=content,
        headers={"Content-Type": "image/png"},
    )


@pytest.fixture
def small_cap_client(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Same construction as conftest's `client` + `authenticated_client`
    fixtures, but with `max_attachment_size_bytes` overridden to a small
    value via `MAX_ATTACHMENT_SIZE_BYTES` -- there's no `app.dependency_
    overrides` hook for `get_settings` in this codebase (it's called
    directly as a module-level function, not injected via `Depends`), so
    an env-var override plus `get_settings.cache_clear()` is the same
    mechanism the base `client` fixture already uses for the other
    required settings.
    """
    monkeypatch.setenv("CEREBRUM_VAULT_PATH", str(vault))
    monkeypatch.setenv("AUTH_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AUTH_SETUP_TOKEN", "y" * 32)
    monkeypatch.setenv("MAX_ATTACHMENT_SIZE_BYTES", "10")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        token = issue_test_access_token(test_client)
        test_client.headers.update({"Authorization": f"Bearer {token}"})
        yield test_client
    get_settings.cache_clear()


def test_upload_then_get_roundtrip(authenticated_client: TestClient) -> None:
    _create_note(authenticated_client)

    upload_response = _upload(authenticated_client, "idea.md")

    assert upload_response.status_code == 200
    body = upload_response.json()
    assert "path" in body

    get_response = authenticated_client.get(f"/api/attachments/{body['path']}")
    assert get_response.status_code == 200
    assert get_response.content == _PNG_BYTES
    assert get_response.headers["content-type"] == "image/png"


def test_upload_for_missing_note_returns_404_and_writes_nothing(
    authenticated_client: TestClient, vault: Path
) -> None:
    upload_response = _upload(authenticated_client, "missing.md")

    assert upload_response.status_code == 404
    assert not (vault / "missing.attachments").exists()
    # `.cerebrum` (the index/auth DB dir) is created by app startup, not by
    # this route -- confirming no *other* entry (note file, attachments
    # dir) was written is the actual assertion here.
    assert [entry.name for entry in vault.iterdir()] == [".cerebrum"]


def test_upload_exceeding_size_cap_returns_413(small_cap_client: TestClient) -> None:
    _create_note(small_cap_client)

    upload_response = _upload(small_cap_client, "idea.md")

    assert upload_response.status_code == 413


def test_upload_with_spoofed_content_length_returns_413_without_consuming_body(
    authenticated_client: TestClient, vault: Path
) -> None:
    # httpx (unlike some HTTP client libraries) does NOT recompute
    # Content-Length when the caller sets it explicitly -- verified
    # separately with an httpx.MockTransport handler that observed the
    # spoofed value arriving unchanged server-side. That means this *can*
    # isolate the early Content-Length guard from the general
    # over-the-cap path: the default (10MB) cap is used here, the real
    # body is tiny and well under it, and only the declared header lies
    # about the size -- so a 413 here can only come from the early-out
    # branch (`request.stream()` is never reached to run save_attachment's
    # own running-total check, which would need actual oversized bytes to
    # ever fire).
    _create_note(authenticated_client)

    upload_response = authenticated_client.post(
        "/api/attachments",
        params={"note_path": "idea.md"},
        content=_PNG_BYTES,
        headers={
            "Content-Type": "image/png",
            "content-length": str(10_000_000 + 1),
        },
    )

    assert upload_response.status_code == 413
    assert not (vault / "idea.attachments").exists()


def test_upload_with_disallowed_content_type_returns_415(
    authenticated_client: TestClient,
) -> None:
    _create_note(authenticated_client)

    upload_response = authenticated_client.post(
        "/api/attachments",
        params={"note_path": "idea.md"},
        content=b"%PDF-1.4 not a real pdf",
        headers={"Content-Type": "application/pdf"},
    )

    assert upload_response.status_code == 415


def test_get_missing_attachment_returns_404(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/attachments/idea.attachments/missing.png")

    assert response.status_code == 404


def test_get_attachment_includes_nosniff_header(
    authenticated_client: TestClient,
) -> None:
    _create_note(authenticated_client)
    upload_response = _upload(authenticated_client, "idea.md")
    path = upload_response.json()["path"]

    get_response = authenticated_client.get(f"/api/attachments/{path}")

    assert get_response.headers["x-content-type-options"] == "nosniff"


def test_upload_requires_authentication(client: TestClient) -> None:
    response = _upload(client, "idea.md")

    assert response.status_code == 401


def test_get_attachment_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/attachments/idea.attachments/whatever.png")

    assert response.status_code == 401


def test_upload_does_not_modify_note_content(authenticated_client: TestClient) -> None:
    _create_note(authenticated_client)
    before = authenticated_client.get("/api/notes/idea.md").json()["content"]

    _upload(authenticated_client, "idea.md")

    after = authenticated_client.get("/api/notes/idea.md").json()["content"]
    assert after == before
