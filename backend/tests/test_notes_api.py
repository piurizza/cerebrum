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


def test_put_malformed_frontmatter_returns_400_not_500(client: TestClient) -> None:
    # Regression: typing directly into the frontmatter block used to crash
    # this endpoint with an unhandled 500 instead of a clean 400.
    response = client.put(
        "/api/notes/a.md",
        content="---\ntags: []Hello from the create-note test.\ntitle: a\n---\nBody.\n",
    )

    assert response.status_code == 400


def test_move_note_relocates_and_updates_index(client: TestClient) -> None:
    client.put("/api/notes/a.md", content="---\ntitle: A\n---\nBody.\n")

    move_response = client.post(
        "/api/notes/a.md/move", json={"new_path": "folder/b.md"}
    )
    assert move_response.status_code == 200
    assert move_response.json()["path"] == "folder/b.md"

    assert client.get("/api/notes/a.md").status_code == 404
    assert client.get("/api/notes/folder/b.md").status_code == 200

    list_response = client.get("/api/notes")
    assert [note["path"] for note in list_response.json()] == ["folder/b.md"]


def test_move_note_missing_source_returns_404(client: TestClient) -> None:
    response = client.post("/api/notes/missing.md/move", json={"new_path": "target.md"})

    assert response.status_code == 404


def test_move_note_existing_destination_returns_409(client: TestClient) -> None:
    client.put("/api/notes/a.md", content="content")
    client.put("/api/notes/b.md", content="content")

    response = client.post("/api/notes/a.md/move", json={"new_path": "b.md"})

    assert response.status_code == 409


def test_move_note_retargets_other_notes_incoming_links(client: TestClient) -> None:
    # Moving a note rewrites other notes' link text so it keeps pointing
    # at the moved note -- not just the file on disk, but the index too
    # (backlinks/graph must reflect the new path, not a broken old one).
    client.put("/api/notes/a.md", content="See [B](b.md).")
    client.put("/api/notes/b.md", content="content")

    client.post("/api/notes/b.md/move", json={"new_path": "folder/b.md"})

    assert "[B](folder/b.md)" in client.get("/api/notes/a.md").json()["content"]

    backlinks_old_path = client.get("/api/notes/b.md/backlinks")
    assert backlinks_old_path.json() == []

    backlinks_new_path = client.get("/api/notes/folder/b.md/backlinks")
    assert [note["path"] for note in backlinks_new_path.json()] == ["a.md"]

    graph = client.get("/api/graph").json()
    nodes_by_path = {node["path"]: node for node in graph["nodes"]}
    assert "b.md" not in nodes_by_path  # no longer a ghost node either
    assert nodes_by_path["folder/b.md"]["exists"] is True
