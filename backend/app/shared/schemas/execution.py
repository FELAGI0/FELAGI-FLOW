import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_version_id: uuid.UUID
    status: str
    trigger_type: str
    trigger_payload: dict[str, Any] | None
    attempts: int
    max_attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ExecutionStepResponse(BaseModel):
    id: uuid.UUID
    node_id: str
    node_type: str
    # номер попытки узла: 1, 2, 3... при per-node retry (4.C)
    attempt: int
    status: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    warnings: list[str]
    duration_ms: int | None


class ExecutionDetailResponse(ExecutionResponse):
    steps: list[ExecutionStepResponse]


class ExecutionListResponse(BaseModel):
    items: list[ExecutionResponse]
    next_cursor: str | None


class RunWorkflowRequest(BaseModel):
    # доступно узлам как {{ trigger.payload.* }}
    payload: dict[str, Any] | None = Field(default=None)