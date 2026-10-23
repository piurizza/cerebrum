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


def _put(client: TestClient, path: str, tags: list[str], body: str = "") -> None:
    tag_list = ", ".join(f'"{tag}"' for tag in tags)
    client.put(f"/api/notes/{path}", content=f"---\ntags: [{tag_list}]\n---\n{body}\n")


def _paths(client: TestClient, query: str) -> list[str]:
    response = client.get("/api/search", params={"q": query})
    assert response.status_code == 200
    return [note["path"] for note in response.json()]


def test_search_by_tag_alone_lists_tagged_notes_by_path(
    authenticated_client: TestClient,
) -> None:
    _put(authenticated_client, "c.md", ["work"])
    _put(authenticated_client, "a.md", ["Work/clientA"])
    _put(authenticated_client, "b.md", ["workshop"])
    _put(authenticated_client, "d.md", [])

    assert _paths(authenticated_client, "#work") == ["a.md", "c.md"]


def test_search_with_several_tags_needs_all_of_them(
    authenticated_client: TestClient,
) -> None:
    _put(authenticated_client, "both.md", ["a", "b"])
    _put(authenticated_client, "only-a.md", ["a"])

    assert _paths(authenticated_client, "#a #b") == ["both.md"]


def test_search_with_only_an_excluded_tag_lists_every_other_note(
    authenticated_client: TestClient,
) -> None:
    _put(authenticated_client, "kept.md", ["work"])
    _put(authenticated_client, "gone.md", ["archive"])
    _put(authenticated_client, "nested.md", ["archive/2024"])
    _put(authenticated_client, "untagged.md", [])

    assert _paths(authenticated_client, "-#archive") == ["kept.md", "untagged.md"]


def test_search_words_and_tags_narrows_the_ranked_results(
    authenticated_client: TestClient,
) -> None:
    _put(authenticated_client, "plain.md", [], "bread bread bread")
    _put(authenticated_client, "recipe.md", ["recipe"], "bread")
    _put(authenticated_client, "other.md", ["recipe"], "soup")

    assert _paths(authenticated_client, "bread #recipe") == ["recipe.md"]


def test_search_plain_words_ignore_tags_entirely(
    authenticated_client: TestClient,
) -> None:
    # Regression: a query without # returns what it always did, ranked.
    _put(authenticated_client, "weak.md", ["x"], "bread once, then other words")
    _put(authenticated_client, "strong.md", [], "bread bread bread")

    assert _paths(authenticated_client, "bread") == ["strong.md", "weak.md"]


def test_search_accented_words_still_match(authenticated_client: TestClient) -> None:
    _put(authenticated_client, "a.md", ["lavoro"], "La città di notte")

    assert _paths(authenticated_client, "città") == ["a.md"]
    assert _paths(authenticated_client, "città #lavoro") == ["a.md"]


def test_search_unknown_tag_returns_empty_list(
    authenticated_client: TestClient,
) -> None:
    _put(authenticated_client, "a.md", ["work"])

    assert _paths(authenticated_client, "#nope") == []
