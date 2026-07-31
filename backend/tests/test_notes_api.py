from __future__ import annotations

from fastapi.testclient import TestClient


def test_put_then_get_note(client: TestClient) -> None:
    put_response = client.put("/api/notes/a.md", content="---\ntitle: A\n---\nBody.\n")
    assert put_response.status_code == 200
    assert put_response.json()["title"] == "A"

    get_response = client.get("/api/notes/a.md")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "A"


def test_list_notes_includes_written_note(client: TestClient) -> None:
    client.put("/api/notes/a.md", content="content")

    response = client.get("/api/notes")

    assert response.status_code == 200
    assert [note["path"] for note in response.json()] == ["a.md"]


def test_delete_note_then_get_returns_404(client: TestClient) -> None:
    client.put("/api/notes/a.md", content="content")

    delete_response = client.delete("/api/notes/a.md")
    assert delete_response.status_code == 204

    get_response = client.get("/api/notes/a.md")
    assert get_response.status_code == 404


def test_get_missing_note_returns_404(client: TestClient) -> None:
    response = client.get("/api/notes/missing.md")

    assert response.status_code == 404


def test_put_invalid_suffix_returns_400(client: TestClient) -> None:
    response = client.put("/api/notes/note.txt", content="content")

    assert response.status_code == 400
