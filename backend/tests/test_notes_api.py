from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient


def test_put_then_get_note(authenticated_client: TestClient) -> None:
    put_response = authenticated_client.put(
        "/api/notes/a.md", content="---\ntitle: A\n---\nBody.\n"
    )
    assert put_response.status_code == 200
    assert put_response.json()["title"] == "A"

    get_response = authenticated_client.get("/api/notes/a.md")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "A"


def test_list_notes_includes_written_note(authenticated_client: TestClient) -> None:
    authenticated_client.put("/api/notes/a.md", content="content")

    response = authenticated_client.get("/api/notes")

    assert response.status_code == 200
    assert [note["path"] for note in response.json()] == ["a.md"]


def test_delete_note_then_get_returns_404(authenticated_client: TestClient) -> None:
    authenticated_client.put("/api/notes/a.md", content="content")

    delete_response = authenticated_client.delete("/api/notes/a.md")
    assert delete_response.status_code == 204

    get_response = authenticated_client.get("/api/notes/a.md")
    assert get_response.status_code == 404


def test_get_missing_note_returns_404(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/notes/missing.md")

    assert response.status_code == 404


def test_put_invalid_suffix_returns_400(authenticated_client: TestClient) -> None:
    response = authenticated_client.put("/api/notes/note.txt", content="content")

    assert response.status_code == 400


def test_put_malformed_frontmatter_returns_400_not_500(
    authenticated_client: TestClient,
) -> None:
    # Regression: typing directly into the frontmatter block used to crash
    # this endpoint with an unhandled 500 instead of a clean 400.
    response = authenticated_client.put(
        "/api/notes/a.md",
        content="---\ntags: []Hello from the create-note test.\ntitle: a\n---\nBody.\n",
    )

    assert response.status_code == 400


def test_move_note_relocates_and_updates_index(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put("/api/notes/a.md", content="---\ntitle: A\n---\nBody.\n")

    move_response = authenticated_client.post(
        "/api/notes/a.md/move", json={"new_path": "folder/b.md"}
    )
    assert move_response.status_code == 200
    assert move_response.json()["path"] == "folder/b.md"

    assert authenticated_client.get("/api/notes/a.md").status_code == 404
    assert authenticated_client.get("/api/notes/folder/b.md").status_code == 200

    list_response = authenticated_client.get("/api/notes")
    assert [note["path"] for note in list_response.json()] == ["folder/b.md"]


def test_move_note_missing_source_returns_404(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/notes/missing.md/move", json={"new_path": "target.md"}
    )

    assert response.status_code == 404


def test_move_note_existing_destination_returns_409(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put("/api/notes/a.md", content="content")
    authenticated_client.put("/api/notes/b.md", content="content")

    response = authenticated_client.post(
        "/api/notes/a.md/move", json={"new_path": "b.md"}
    )

    assert response.status_code == 409


def test_move_note_retargets_other_notes_incoming_links(
    authenticated_client: TestClient,
) -> None:
    # Moving a note rewrites other notes' link text so it keeps pointing
    # at the moved note -- not just the file on disk, but the index too
    # (backlinks/graph must reflect the new path, not a broken old one).
    authenticated_client.put("/api/notes/a.md", content="See [B](b.md).")
    authenticated_client.put("/api/notes/b.md", content="content")

    authenticated_client.post("/api/notes/b.md/move", json={"new_path": "folder/b.md"})

    assert (
        "[B](folder/b.md)"
        in authenticated_client.get("/api/notes/a.md").json()["content"]
    )

    backlinks_old_path = authenticated_client.get("/api/notes/b.md/backlinks")
    assert backlinks_old_path.json() == []

    backlinks_new_path = authenticated_client.get("/api/notes/folder/b.md/backlinks")
    assert [note["path"] for note in backlinks_new_path.json()] == ["a.md"]

    graph = authenticated_client.get("/api/graph").json()
    nodes_by_path = {node["path"]: node for node in graph["nodes"]}
    assert "b.md" not in nodes_by_path  # no longer a ghost node either
    assert nodes_by_path["folder/b.md"]["exists"] is True


def test_move_note_into_trash_drops_it_from_the_list_immediately(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put("/api/notes/a.md", content="content")
    authenticated_client.put("/api/notes/x.md", content="content")

    move_response = authenticated_client.post(
        "/api/notes/x.md/move", json={"new_path": ".trash/x.md"}
    )
    assert move_response.status_code == 200

    list_response = authenticated_client.get("/api/notes")
    assert [note["path"] for note in list_response.json()] == ["a.md"]
    # Still readable by its explicit path, so it can be restored.
    assert authenticated_client.get("/api/notes/.trash/x.md").status_code == 200


def test_put_note_in_a_hidden_folder_is_not_listed(
    authenticated_client: TestClient,
) -> None:
    put_response = authenticated_client.put(
        "/api/notes/.obsidian/x.md", content="content"
    )
    assert put_response.status_code == 200

    list_response = authenticated_client.get("/api/notes")
    assert list_response.json() == []


def test_get_note_version_changes_when_the_file_changes(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put("/api/notes/a.md", content="first")
    before = authenticated_client.get("/api/notes/a.md").json()["version"]
    assert before == hashlib.sha256((vault / "a.md").read_bytes()).hexdigest()

    (vault / "a.md").write_text("changed on disk", encoding="utf-8")

    after = authenticated_client.get("/api/notes/a.md").json()["version"]
    assert after != before
    assert after == hashlib.sha256((vault / "a.md").read_bytes()).hexdigest()


def test_put_with_the_current_base_version_saves_and_returns_a_new_version(
    authenticated_client: TestClient, vault: Path
) -> None:
    loaded = authenticated_client.put("/api/notes/a.md", content="first").json()

    response = authenticated_client.put(
        "/api/notes/a.md",
        content="second",
        headers={"X-Base-Version": loaded["version"]},
    )

    assert response.status_code == 200
    assert "second" in response.json()["content"]
    assert response.json()["version"] != loaded["version"]
    assert (
        response.json()["version"]
        == hashlib.sha256((vault / "a.md").read_bytes()).hexdigest()
    )


def test_put_with_a_stale_base_version_returns_412_and_leaves_the_file(
    authenticated_client: TestClient, vault: Path
) -> None:
    loaded = authenticated_client.put("/api/notes/a.md", content="first").json()
    authenticated_client.put("/api/notes/a.md", content="changed elsewhere")
    on_disk = (vault / "a.md").read_bytes()

    response = authenticated_client.put(
        "/api/notes/a.md",
        content="mine",
        headers={"X-Base-Version": loaded["version"]},
    )

    assert response.status_code == 412
    assert response.json() == {"detail": "The note changed since it was loaded"}
    assert (vault / "a.md").read_bytes() == on_disk


def test_put_with_a_base_version_for_a_deleted_note_returns_412_not_404(
    authenticated_client: TestClient, vault: Path
) -> None:
    loaded = authenticated_client.put("/api/notes/a.md", content="first").json()
    authenticated_client.delete("/api/notes/a.md")

    response = authenticated_client.put(
        "/api/notes/a.md",
        content="mine",
        headers={"X-Base-Version": loaded["version"]},
    )

    assert response.status_code == 412
    assert not (vault / "a.md").exists()


def test_put_create_only_on_an_existing_note_returns_412(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put("/api/notes/a.md", content="first")
    on_disk = (vault / "a.md").read_bytes()

    response = authenticated_client.put(
        "/api/notes/a.md", content="mine", headers={"X-Create-Only": "1"}
    )

    assert response.status_code == 412
    assert response.json() == {"detail": "A note already exists at a.md"}
    assert (vault / "a.md").read_bytes() == on_disk


def test_put_create_only_on_a_new_path_creates_the_note(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.put(
        "/api/notes/new.md", content="fresh", headers={"X-Create-Only": "1"}
    )

    assert response.status_code == 200
    assert "fresh" in authenticated_client.get("/api/notes/new.md").json()["content"]
    assert [note["path"] for note in authenticated_client.get("/api/notes").json()] == [
        "new.md"
    ]


def test_put_create_only_with_another_value_is_refused(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put("/api/notes/a.md", content="first")

    response = authenticated_client.put(
        "/api/notes/a.md", content="mine", headers={"X-Create-Only": "true"}
    )

    assert response.status_code == 400
    assert "first" in (vault / "a.md").read_text(encoding="utf-8")


def test_put_without_precondition_headers_overwrites(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put("/api/notes/a.md", content="first")

    response = authenticated_client.put("/api/notes/a.md", content="second")

    assert response.status_code == 200
    assert "second" in authenticated_client.get("/api/notes/a.md").json()["content"]


def test_move_note_returns_the_moved_files_version(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put("/api/notes/a.md", content="---\ntitle: A\n---\nBody.\n")

    response = authenticated_client.post(
        "/api/notes/a.md/move", json={"new_path": "b.md", "title": "B"}
    )

    assert (
        response.json()["version"]
        == hashlib.sha256((vault / "b.md").read_bytes()).hexdigest()
    )
