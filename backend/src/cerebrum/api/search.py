from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from cerebrum.api.deps import get_db
from cerebrum.index.db import search_notes
from cerebrum.notes.models import NoteMeta

router = APIRouter()


@router.get("/search", response_model=list[NoteMeta])
def search(q: str = "", db: sqlite3.Connection = Depends(get_db)) -> list[NoteMeta]:
    return search_notes(db, q)
