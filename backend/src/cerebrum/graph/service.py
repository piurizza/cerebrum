from __future__ import annotations

import sqlite3
from pathlib import PurePosixPath

from cerebrum.graph.models import GraphEdge, GraphNode, GraphResponse
from cerebrum.index.db import row_to_note_meta, write_lock
from cerebrum.notes.models import NoteMeta
from cerebrum.notes.wikilinks import NoteLookup, name_key


def _ghost_path(target: str) -> str:
    """Where an unresolved wikilink's ghost node goes: the note it would
    point at if created next to the vault root, like a broken markdown
    link's target path."""
    target = target.strip().strip("/")
    return target if target.lower().endswith(".md") else f"{target}.md"


def get_graph(conn: sqlite3.Connection) -> GraphResponse:
    # write_lock: this read races the filesystem watcher/backstop rescan's
    # sustained writes against the same shared connection -- see
    # index/db.py's write_lock docstring for the exact hazard
    # (sqlite3.InterfaceError) an unlocked read can hit here.
    with write_lock:
        note_rows = conn.execute("SELECT path, title FROM notes").fetchall()
        # DISTINCT: a note can have multiple links to the same target
        # (different link text/fragment) -- those are still one edge.
        link_rows = conn.execute(
            "SELECT DISTINCT source_path, target_path FROM links"
        ).fetchall()
        wikilink_rows = conn.execute(
            "SELECT DISTINCT source_path, target FROM wikilinks"
        ).fetchall()
    nodes = {
        row["path"]: GraphNode(path=row["path"], title=row["title"], exists=True)
        for row in note_rows
    }

    edge_keys = {(row["source_path"], row["target_path"]): None for row in link_rows}
    lookup = NoteLookup(nodes)
    for row in wikilink_rows:
        source = row["source_path"]
        resolved = lookup.resolve(source, row["target"])
        # Keyed like a markdown link and its wikilink twin, so a note
        # linking to the same target both ways is still one edge.
        edge_keys[(source, resolved or _ghost_path(row["target"]))] = None
    edges = [GraphEdge(source=source, target=target) for source, target in edge_keys]

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
    with write_lock:
        sources = {
            row["source_path"]
            for row in conn.execute(
                "SELECT source_path FROM links WHERE target_path = ?", (path,)
            )
        }
        # Only wikilinks naming this note's file can point at it; resolve
        # each from its own note to see whether it really does.
        candidates = conn.execute(
            "SELECT source_path, target FROM wikilinks WHERE name_key = ?",
            (name_key(PurePosixPath(path).stem),),
        ).fetchall()
        if candidates:
            lookup = NoteLookup(
                row["path"] for row in conn.execute("SELECT path FROM notes")
            )
            sources.update(
                row["source_path"]
                for row in candidates
                if lookup.resolve(row["source_path"], row["target"]) == path
            )
        if not sources:
            return []
        placeholders = ",".join("?" * len(sources))
        rows = conn.execute(
            f"""
            SELECT path, title, tags, created, updated
            FROM notes
            WHERE path IN ({placeholders})
            ORDER BY path
            """,
            tuple(sources),
        ).fetchall()
    return [row_to_note_meta(row) for row in rows]
