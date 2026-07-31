from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from cerebrum.api.deps import get_db
from cerebrum.graph.models import GraphResponse
from cerebrum.graph.service import get_backlinks, get_graph
from cerebrum.notes.models import NoteMeta

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
def graph_endpoint(db: sqlite3.Connection = Depends(get_db)) -> GraphResponse:
    return get_graph(db)


@router.get("/notes/{path:path}/backlinks", response_model=list[NoteMeta])
def backlinks_endpoint(
    path: str, db: sqlite3.Connection = Depends(get_db)
) -> list[NoteMeta]:
    return get_backlinks(db, path)
