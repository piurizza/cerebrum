from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from cerebrum.api.deps import get_db
from cerebrum.tasks.models import TaskItem
from cerebrum.tasks.service import list_open_tasks

router = APIRouter()


@router.get("/tasks", response_model=list[TaskItem])
def tasks_endpoint(db: sqlite3.Connection = Depends(get_db)) -> list[TaskItem]:
    return list_open_tasks(db)
