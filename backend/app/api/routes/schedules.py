"""Список cron-расписаний workspace (DESIGN.md §5, этап 5).

Пока только чтение: расписания создаются и удаляются синхронизацией при
публикации графа, отдельного CRUD нет — редактирование расписания и есть
редактирование узла trigger_cron.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_role
from app.shared.models import Schedule, WorkspaceMember

router = APIRouter(prefix="/api", tags=["schedules"])

# членство в workspace проверяет dependency: ws_id берётся из пути
Viewer = Annotated[WorkspaceMember, Depends(require_role("owner", "admin", "member"))]


class ScheduleResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    spec: str
    next_run_at: datetime
    last_run_at: datetime | None
    enabled: bool


@router.get("/workspaces/{ws_id}/schedules", response_model=list[ScheduleResponse])
async def list_schedules(
    ws_id: uuid.UUID,
    current_user: CurrentUser,
    session: DbSession,
    _member: Viewer,
) -> list[ScheduleResponse]:
    rows = await session.scalars(
        select(Schedule)
        .where(Schedule.workspace_id == ws_id)
        .order_by(Schedule.next_run_at)
    )
    return [
        ScheduleResponse(
            id=row.id,
            workflow_id=row.workflow_id,
            spec=row.spec,
            next_run_at=row.next_run_at,
            last_run_at=row.last_run_at,
            enabled=row.enabled,
        )
        for row in rows
    ]