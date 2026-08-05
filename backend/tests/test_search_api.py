from __future__ import annotations

from fastapi.testclient import TestClient


def test_search_returns_matching_notes(authenticated_client: TestClient) -> None:
    authenticated_client.put(
        "/api/notes/a.md", content="---\ntitle: Recipe\n---\nBread and butter.\n"
    )
    authenticated_client.put(
        "/api/notes/b.md", content="---\ntitle: Travel\n---\nNotes about Japan.\n"
    )

    response = authenticated_client.get("/api/search", params={"q": "bread"})

    assert response.status_code == 200
    assert [note["path"] for note in response.json()] == ["a.md"]


def test_search_missing_query_returns_empty_list(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put("/api/notes/a.md", content="content")

    response = authenticated_client.get("/api/search")

    assert response.status_code == 200
    assert response.json() == []


def test_search_no_matches_returns_empty_list(authenticated_client: TestClient) -> None:
    authenticated_client.put("/api/notes/a.md", content="content about cats")

    response = authenticated_client.get("/api/search", params={"q": "dogs"})

    assert response.status_code == 200
    assert response.json() == []
