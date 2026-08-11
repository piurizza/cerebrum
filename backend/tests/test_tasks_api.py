from __future__ import annotations

from fastapi.testclient import TestClient


def test_tasks_returns_open_tasks_with_joined_note_titles(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put(
        "/api/notes/a.md",
        content="---\ntitle: Groceries\n---\n- [ ] Buy milk\n",
    )
    authenticated_client.put(
        "/api/notes/b.md",
        content="---\ntitle: Chores\n---\n- [ ] Mow lawn\n",
    )

    response = authenticated_client.get("/api/tasks")

    assert response.status_code == 200
    body = response.json()
    assert {(item["title"], item["text"]) for item in body} == {
        ("Groceries", "Buy milk"),
        ("Chores", "Mow lawn"),
    }


def test_tasks_excludes_checked_tasks(authenticated_client: TestClient) -> None:
    authenticated_client.put("/api/notes/a.md", content="- [ ] Open\n- [x] Closed\n")

    response = authenticated_client.get("/api/tasks")

    assert [item["text"] for item in response.json()] == ["Open"]


def test_tasks_orders_by_note_path_then_line(authenticated_client: TestClient) -> None:
    authenticated_client.put("/api/notes/z.md", content="- [ ] Z task\n")
    authenticated_client.put("/api/notes/a.md", content="- [ ] First\n- [ ] Second\n")

    response = authenticated_client.get("/api/tasks")

    assert [(item["path"], item["text"]) for item in response.json()] == [
        ("a.md", "First"),
        ("a.md", "Second"),
        ("z.md", "Z task"),
    ]


def test_tasks_uses_frontmatter_title_override_not_filename(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put(
        "/api/notes/my-note.md",
        content="---\ntitle: A Custom Title\n---\n- [ ] Task\n",
    )

    response = authenticated_client.get("/api/tasks")

    assert response.json()[0]["title"] == "A Custom Title"


def test_tasks_empty_vault_returns_empty_list(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json() == []
