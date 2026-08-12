from __future__ import annotations

from pydantic import BaseModel


class TaskItem(BaseModel):
    path: str
    title: str
    line: int
    text: str
