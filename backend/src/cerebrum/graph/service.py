from __future__ import annotations

import sqlite3

from cerebrum.graph.models import GraphEdge, GraphNode, GraphResponse
from cerebrum.index.db import row_to_note_meta
from cerebrum.notes.models import NoteMeta


def get_graph(conn: sqlite3.Connection) -> GraphResponse:
    note_rows = conn.execute("SELECT path, title FROM notes").fetchall()
    nodes = {
        row["path"]: GraphNode(path=row["path"], title=row["title"], exists=True)
        for row in note_rows
    }

    # DISTINCT: a note can have multiple markdown links to the same
    # target (different link text/fragment) -- those are still one edge.
    link_rows = conn.execute(
        "SELECT DISTINCT source_path, target_path FROM links"
    ).fetchall()
    edges = [
        GraphEdge(source=row["source_path"], target=row["target_path"])
        for row in link_rows
    ]

    # A link may point at a note that doesn't exist yet — a valid "broken
    # link" (see SPEC.md). Surface it as a ghost node (exists=False) so the
    # frontend can render it distinctly instead of dropping the edge.
    for edge in edges:
        if edge.target not in nodes:
            nodes[edge.target] = GraphNode(
                path=edge.target, title=edge.target, exists=False
            )

    return GraphResponse(nodes=list(nodes.values()), edges=edges)


def get_backlinks(conn: sqlite3.Connection, path: str) -> list[NoteMeta]:
    # DISTINCT: a note can have multiple markdown links to the same
    # target (different link text/fragment) -- it should still appear
    # as one backlink, not once per link.
    rows = conn.execute(
        """
        SELECT DISTINCT n.path, n.title, n.tags, n.created, n.updated
        FROM links l
        JOIN notes n ON n.path = l.source_path
        WHERE l.target_path = ?
        ORDER BY n.path
        """,
        (path,),
    ).fetchall()
    return [row_to_note_meta(row) for row in rows]
