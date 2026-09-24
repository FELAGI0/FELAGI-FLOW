import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Node(BaseModel):
    id: str
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = None
    targetHandle: str | None = None


class Graph(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    layout: dict[str, Any] | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    # 'active' недоступен: активация только через POST /publish, иначе Literal → 422
    status: Literal["draft", "paused"] | None = None


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    status: str
    published_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class WorkflowVersionResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    version: int
    graph: Graph
    change_note: str | None
    created_at: datetime


class SaveDraftRequest(BaseModel):
    graph: Graph
    change_note: str | None = None


class PublishResponse(BaseModel):
    workflow_id: uuid.UUID
    published_version_id: uuid.UUID
    version: int