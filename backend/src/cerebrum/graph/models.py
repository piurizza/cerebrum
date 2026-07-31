from __future__ import annotations

from pydantic import BaseModel


class GraphNode(BaseModel):
    path: str
    title: str
    exists: bool


class GraphEdge(BaseModel):
    source: str
    target: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
