import base64
import binascii
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, require_role
from app.engine.queue import enqueue
from app.shared.models import Execution, ExecutionStep, Workflow, Workspace, WorkspaceMember
from app.shared.schemas.execution import (
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionResponse,
    ExecutionStepResponse,
    RunWorkflowRequest,
)

router = APIRouter(prefix="/api", tags=["executions"])

Viewer = Annotated[WorkspaceMember, Depends(require_role("owner", "admin", "member"))]

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _to_response(execution: Execution) -> ExecutionResponse:
    return ExecutionResponse(
        id=execution.id,
        workflow_id=execution.workflow_id,
        workflow_version_id=execution.workflow_version_id,
        status=execution.status,
        trigger_type=execution.trigger_type,
        trigger_payload=execution.trigger_payload,
        attempts=execution.attempts,
        max_attempts=execution.max_attempts,
        error=execution.error,
        created_at=execution.created_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
    )


def _step_response(step: ExecutionStep) -> ExecutionStepResponse:
    return ExecutionStepResponse(
        id=step.id,
        node_id=step.node_id,
        node_type=step.node_type,
        attempt=step.attempt,
        status=step.status,
        input=step.input,
        output=step.output,
        error=step.error,
        warnings=step.warnings,
        duration_ms=step.duration_ms,
    )


def _encode_cursor(created_at: datetime, execution_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{execution_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_str, execution_id_str = raw.split("|", 1)
        return datetime.fromisoformat(created_at_str), uuid.UUID(execution_id_str)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


async def _execution_for_member(
    session: AsyncSession, execution_id: uuid.UUID, user_id: uuid.UUID
) -> Execution:
    """Загружает execution и проверяет членство в workspace его workflow."""
    execution = await session.get(Execution, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    workflow: Workflow | None = await session.get(Workflow, execution.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    member = await session.get(WorkspaceMember, (workflow.workspace_id, user_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this workspace"
        )
    return execution


async def _member_of_workspace(
    session: AsyncSession, ws_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember:
    if await session.get(Workspace, ws_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member = await session.get(WorkspaceMember, (ws_id, user_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this workspace"
        )
    return member


@router.post(
    "/workflows/{workflow_id}/run",
    status_code=status.HTTP_201_CREATED,
    response_model=ExecutionResponse,
)
async def run_workflow(
    workflow_id: uuid.UUID,
    body: RunWorkflowRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ExecutionResponse:
    workflow: Workflow | None = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await _member_of_workspace(session, workflow.workspace_id, current_user.id)

    if workflow.published_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Workflow is not published: publish first"
        )

    # лимиты плана — заглушка до этапа 8 (биллинг)
    execution = await enqueue(
        session,
        workflow.id,
        workflow.published_version_id,
        trigger_type="manual",
        trigger_payload=body.payload or {},
    )
    await session.commit()
    return _to_response(execution)


@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> ExecutionDetailResponse:
    execution = await _execution_for_member(session, execution_id, current_user.id)
    steps = await session.scalars(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution.id)
        .order_by(ExecutionStep.created_at, ExecutionStep.node_id)
    )
    base = _to_response(execution)
    return ExecutionDetailResponse(**base.model_dump(), steps=[_step_response(s) for s in steps])


@router.get("/workspaces/{ws_id}/executions", response_model=ExecutionListResponse)
async def list_executions(
    ws_id: uuid.UUID,
    current_user: CurrentUser,
    session: DbSession,
    workflow_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> ExecutionListResponse:
    await _member_of_workspace(session, ws_id, current_user.id)

    stmt = (
        select(Execution)
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .where(Workflow.workspace_id == ws_id)
        .order_by(Execution.created_at.desc(), Execution.id.desc())
        .limit(limit + 1)  # +1 строка, чтобы понять, есть ли следующая страница
    )
    if workflow_id is not None:
        stmt = stmt.where(Execution.workflow_id == workflow_id)
    if status_filter is not None:
        stmt = stmt.where(Execution.status == status_filter)
    if cursor is not None:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor"
            )
        cursor_created, cursor_id = decoded
        # keyset-пагинация: строго «старше» последней строки предыдущей страницы.
        # literal() нужен, чтобы значения курсора стали bind-параметрами
        # (в tuple_ ожидаются SQL-выражения, а не «сырые» Python-значения)
        stmt = stmt.where(
            tuple_(Execution.created_at, Execution.id)
            < tuple_(literal(cursor_created), literal(cursor_id))
        )

    rows = list(await session.scalars(stmt))
    has_more = len(rows) > limit
    page = rows[:limit]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return ExecutionListResponse(
        items=[_to_response(execution) for execution in page],
        next_cursor=next_cursor,
    )


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionResponse)
async def cancel_execution(
    execution_id: uuid.UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> ExecutionResponse:
    execution = await _execution_for_member(session, execution_id, current_user.id)

    # отмена — best effort: ставим флаг, runner проверяет его между узлами.
    # Если узел уже в работе (HTTP-запрос и т.п.), он завершится.
    if execution.status not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel execution in status '{execution.status}'",
        )

    execution.status = "canceled"
    await session.commit()
    return _to_response(execution)