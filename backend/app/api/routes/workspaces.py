import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, WorkspaceMemberDep, require_role
from app.shared.models import User, Workspace, WorkspaceMember
from app.shared.schemas.workspace import (
    MemberResponse,
    MemberRoleUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

OwnerOrAdmin = Annotated[WorkspaceMember, Depends(require_role("owner", "admin"))]
OwnerOnly = Annotated[WorkspaceMember, Depends(require_role("owner"))]


def _to_response(workspace: Workspace, role: str) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        plan=workspace.plan,
        created_at=workspace.created_at,
        current_user_role=role,
    )


async def _member_response(session: AsyncSession, member: WorkspaceMember) -> MemberResponse:
    user: User | None = await session.get(User, member.user_id)
    if user is None:  # FK гарантирует существование; ветка для полноты типа
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        joined_at=member.joined_at,
    )


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(current_user: CurrentUser, session: DbSession) -> list[WorkspaceResponse]:
    # один запрос с JOIN — без N+1 по роли каждого workspace
    rows = await session.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
    )
    return [_to_response(ws, role) for ws, role in rows]


@router.get("/{ws_id}", response_model=WorkspaceResponse)
async def get_workspace(member: WorkspaceMemberDep, session: DbSession) -> WorkspaceResponse:
    # get_workspace_member уже загрузил workspace в identity map — второй get без запроса
    workspace = await session.get(Workspace, member.workspace_id)
    assert workspace is not None
    return _to_response(workspace, member.role)


@router.patch("/{ws_id}", response_model=WorkspaceResponse)
async def rename_workspace(
    body: WorkspaceUpdate,
    member: OwnerOrAdmin,
    session: DbSession,
) -> WorkspaceResponse:
    workspace = await session.get(Workspace, member.workspace_id)
    assert workspace is not None
    workspace.name = body.name
    await session.commit()
    return _to_response(workspace, member.role)


@router.delete("/{ws_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(member: OwnerOnly, session: DbSession) -> None:
    workspace = await session.get(Workspace, member.workspace_id)
    assert workspace is not None
    await session.delete(workspace)  # members/invitations снесёт FK ondelete=CASCADE
    await session.commit()


@router.get("/{ws_id}/members", response_model=list[MemberResponse])
async def list_members(member: WorkspaceMemberDep, session: DbSession) -> list[MemberResponse]:
    rows = await session.execute(
        select(User, WorkspaceMember.role, WorkspaceMember.joined_at)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == member.workspace_id)
    )
    return [
        MemberResponse(
            user_id=user.id, email=user.email, name=user.name, role=role, joined_at=joined
        )
        for user, role, joined in rows
    ]


@router.patch("/{ws_id}/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    user_id: uuid.UUID,
    body: MemberRoleUpdate,
    member: OwnerOnly,
    session: DbSession,
) -> MemberResponse:
    if user_id == member.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot change your own role"
        )
    target: WorkspaceMember | None = await session.get(
        WorkspaceMember, (member.workspace_id, user_id)
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if target.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot change the owner's role"
        )

    target.role = body.role
    await session.commit()
    return await _member_response(session, target)


@router.delete("/{ws_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: uuid.UUID,
    member: OwnerOrAdmin,
    session: DbSession,
) -> None:
    if user_id == member.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot remove yourself"
        )
    target: WorkspaceMember | None = await session.get(
        WorkspaceMember, (member.workspace_id, user_id)
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if target.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot remove the owner"
        )
    if member.role == "admin" and target.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admins cannot remove other admins"
        )

    await session.delete(target)
    await session.commit()