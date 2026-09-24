import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.engine.graph_validator import validate_graph
from app.engine.node_schemas import NODE_SCHEMAS
from app.shared.models import (
    Workflow,
    WorkflowVersion,
    Workspace,
    WorkspaceMember,
)
from app.shared.schemas.workflow import (
    Graph,
    PublishResponse,
    SaveDraftRequest,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowUpdate,
    WorkflowVersionResponse,
)

router = APIRouter(prefix="/api", tags=["workflows"])


def _to_response(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        workspace_id=workflow.workspace_id,
        name=workflow.name,
        status=workflow.status,
        published_version_id=workflow.published_version_id,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _version_response(version: WorkflowVersion) -> WorkflowVersionResponse:
    return WorkflowVersionResponse(
        id=version.id,
        workflow_id=version.workflow_id,
        version=version.version,
        graph=Graph.model_validate(version.graph),
        change_note=version.change_note,
        created_at=version.created_at,
    )


async def _member_of_workspace(
    session: AsyncSession, ws_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember:
    """401/403/404 для workspace-scoped доступа, когда id приходит из тела запроса."""
    if await session.get(Workspace, ws_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member = await session.get(WorkspaceMember, (ws_id, user_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this workspace"
        )
    return member


async def _workflow_for_member(
    session: AsyncSession, workflow_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Workflow, WorkspaceMember]:
    """Загружает workflow и проверяет членство в его workspace."""
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    member = await session.get(WorkspaceMember, (workflow.workspace_id, user_id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this workspace"
        )
    return workflow, member


def _require_editor(member: WorkspaceMember) -> None:
    if member.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )


async def _latest_version(session: AsyncSession, workflow_id: uuid.UUID) -> WorkflowVersion | None:
    latest: WorkflowVersion | None = await session.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )
    return latest


@router.post(
    "/workspaces/{ws_id}/workflows",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowResponse,
)
async def create_workflow(
    ws_id: uuid.UUID,
    body: WorkflowCreate,
    current_user: CurrentUser,
    session: DbSession,
) -> WorkflowResponse:
    await _member_of_workspace(session, ws_id, current_user.id)
    workflow = Workflow(workspace_id=ws_id, name=body.name, created_by=current_user.id)
    session.add(workflow)
    await session.commit()
    return _to_response(workflow)


@router.get("/workspaces/{ws_id}/workflows", response_model=list[WorkflowResponse])
async def list_workflows(
    ws_id: uuid.UUID,
    current_user: CurrentUser,
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[WorkflowResponse]:
    await _member_of_workspace(session, ws_id, current_user.id)
    stmt = (
        select(Workflow)
        .where(Workflow.workspace_id == ws_id)
        .order_by(Workflow.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter is not None:
        stmt = stmt.where(Workflow.status == status_filter)
    rows = await session.scalars(stmt)
    return [_to_response(w) for w in rows]


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID, current_user: CurrentUser, session: DbSession
) -> WorkflowResponse:
    workflow, _ = await _workflow_for_member(session, workflow_id, current_user.id)
    return _to_response(workflow)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    current_user: CurrentUser,
    session: DbSession,
) -> WorkflowResponse:
    workflow, member = await _workflow_for_member(session, workflow_id, current_user.id)
    _require_editor(member)
    if body.name is not None:
        workflow.name = body.name
    if body.status is not None:
        workflow.status = body.status
    await session.commit()
    return _to_response(workflow)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: uuid.UUID, current_user: CurrentUser, session: DbSession
) -> None:
    workflow, member = await _workflow_for_member(session, workflow_id, current_user.id)
    _require_editor(member)
    # версии снесёт FK workflow_versions.workflow_id ON DELETE CASCADE
    await session.delete(workflow)
    await session.commit()


@router.get(
    "/workflows/{workflow_id}/versions",
    response_model=list[WorkflowVersionResponse],
)
async def list_versions(
    workflow_id: uuid.UUID, current_user: CurrentUser, session: DbSession
) -> list[WorkflowVersionResponse]:
    await _workflow_for_member(session, workflow_id, current_user.id)
    rows = await session.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version.desc())
    )
    return [_version_response(v) for v in rows]


@router.get(
    "/workflows/{workflow_id}/versions/{version_number}",
    response_model=WorkflowVersionResponse,
)
async def get_version(
    workflow_id: uuid.UUID,
    version_number: int,
    current_user: CurrentUser,
    session: DbSession,
) -> WorkflowVersionResponse:
    await _workflow_for_member(session, workflow_id, current_user.id)
    version = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version == version_number,
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return _version_response(version)


@router.post(
    "/workflows/{workflow_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowVersionResponse,
)
async def save_version(
    workflow_id: uuid.UUID,
    body: SaveDraftRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> WorkflowVersionResponse:
    await _workflow_for_member(session, workflow_id, current_user.id)

    errors = validate_graph(body.graph, NODE_SCHEMAS)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Graph validation failed", "errors": errors},
        )

    # ponytail: max+1 без блокировки; гонка двух сохранений ловится
    # unique(workflow_id, version) — редкий 409 вместо тихой потери версии
    max_version = await session.scalar(
        select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow_id)
    )
    version = WorkflowVersion(
        workflow_id=workflow_id,
        version=(max_version or 0) + 1,
        graph=body.graph.model_dump(mode="json"),
        change_note=body.change_note,
        created_by=current_user.id,
    )
    session.add(version)
    # сохранение версии — это изменение workflow: обновляем updated_at для сортировки
    # списка (индекс ix_workflows_workspace_id_updated_at); onupdate не сработает,
    # т.к. других полей workflow мы не трогаем
    await session.execute(
        update(Workflow).where(Workflow.id == workflow_id).values(updated_at=func.now())
    )
    await session.commit()
    return _version_response(version)


@router.post("/workflows/{workflow_id}/publish", response_model=PublishResponse)
async def publish_workflow(
    workflow_id: uuid.UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> PublishResponse:
    workflow, member = await _workflow_for_member(session, workflow_id, current_user.id)
    _require_editor(member)

    latest = await _latest_version(session, workflow_id)
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow has no versions to publish",
        )

    errors = validate_graph(Graph.model_validate(latest.graph), NODE_SCHEMAS)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "Graph validation failed", "errors": errors},
        )

    workflow.status = "active"
    workflow.published_version_id = latest.id
    await session.commit()
    return PublishResponse(
        workflow_id=workflow.id,
        published_version_id=latest.id,
        version=latest.version,
    )