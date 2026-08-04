from __future__ import annotations

from fastapi import FastAPI
from fastmcp import FastMCP

from cerebrum.graph.models import GraphResponse
from cerebrum.graph.service import get_backlinks as get_backlinks_from_graph
from cerebrum.graph.service import get_graph as get_graph_from_service
from cerebrum.mcp.context import INDEX_LAG_WARNING, get_db
from cerebrum.notes.models import NoteMeta

_READ_ONLY_ANNOTATIONS = {"readOnlyHint": True, "idempotentHint": True}


def register_graph_tools(mcp: FastMCP, app: FastAPI) -> None:
    """Register `get-graph` and `get-backlinks` (R2) against `mcp`, closing
    over `app` (KTD8) to reach the shared index connection the same way
    REST routes do. Split from `notes_tools.py` to mirror the existing
    `api/notes.py` vs. `api/graph.py` split."""

    @mcp.tool(
        name="get-graph",
        description=(
            "Call this to see the whole-vault link graph: every note as a "
            "node, every markdown link between notes as an edge. Includes "
            "'ghost' nodes for links that target a note that doesn't exist "
            "yet. Returns the whole vault unscoped, not centered on any one "
            f"note. {INDEX_LAG_WARNING}"
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_graph() -> GraphResponse:
        return get_graph_from_service(get_db(app))

    @mcp.tool(
        name="get-backlinks",
        description=(
            "Call this to find every note that links to a given note, by its "
            "vault-relative path. Returns their metadata, not their content. "
            f"{INDEX_LAG_WARNING}"
        ),
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    def get_backlinks(path: str) -> list[NoteMeta]:
        return get_backlinks_from_graph(get_db(app), path)
