from __future__ import annotations

from fastapi.testclient import TestClient


def test_graph_reflects_linked_notes(client: TestClient) -> None:
    client.put("/api/notes/a.md", content="See [B](b.md).")
    client.put("/api/notes/b.md", content="content")

    response = client.get("/api/graph")

    assert response.status_code == 200
    body = response.json()
    assert {node["path"] for node in body["nodes"]} == {"a.md", "b.md"}
    assert {(edge["source"], edge["target"]) for edge in body["edges"]} == {
        ("a.md", "b.md")
    }


def test_graph_includes_ghost_node_for_broken_link(client: TestClient) -> None:
    client.put("/api/notes/a.md", content="See [Missing](missing.md).")

    response = client.get("/api/graph")

    body = response.json()
    nodes_by_path = {node["path"]: node for node in body["nodes"]}
    assert nodes_by_path["a.md"]["exists"] is True
    assert nodes_by_path["missing.md"]["exists"] is False


def test_backlinks_endpoint_returns_linking_notes(client: TestClient) -> None:
    # Also a regression test for the router-inclusion-order guarantee in
    # router.py: if graph.router were included after notes.router, this
    # request would be swallowed by notes.py's `/notes/{path:path}` catch-all
    # (looking for a file literally named "b.md/backlinks") and 404.
    client.put("/api/notes/a.md", content="See [B](b.md).")
    client.put("/api/notes/b.md", content="content")

    response = client.get("/api/notes/b.md/backlinks")

    assert response.status_code == 200
    assert [note["path"] for note in response.json()] == ["a.md"]
