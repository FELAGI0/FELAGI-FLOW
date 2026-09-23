import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, require_role
from app.shared.config import settings
from app.shared.models import Invitation, User, Workspace, WorkspaceMember
from app.shared.schemas.invitation import (
    InvitationAcceptResponse,
    InvitationCreate,
    InvitationResponse,
)

# DESIGN.md §5: префикс /api у всего, кроме /hooks — иначе Caddy не проксирует
router = APIRouter(prefix="/api", tags=["invitations"])

AdminMember = Annotated[WorkspaceMember, Depends(require_role("owner", "admin"))]


def _as_utc(value: datetime) -> datetime:
    # SQLite (DateTime(timezone=True)) возвращает naive datetime, Postgres — aware;
    # без нормализации сравнение с now(utc) падает на SQLite
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _to_response(invitation: Invitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invite_url=f"{settings.frontend_url}/invite/{invitation.token}",
    )


async def _active_invitations(session: AsyncSession, ws_id: uuid.UUID) -> list[Invitation]:
    rows = await session.scalars(
        select(Invitation).where(Invitation.workspace_id == ws_id)
    )
    now = datetime.now(UTC)
    return [i for i in rows if _as_utc(i.expires_at) > now]


@router.post(
    "/workspaces/{ws_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationResponse,
)
async def create_invitation(
    ws_id: uuid.UUID,
    body: InvitationCreate,
    member: AdminMember,
    session: DbSession,
) -> InvitationResponse:
    existing_user = await session.scalar(select(User).where(User.email == body.email))
    if existing_user is not None:
        already_member = await session.get(WorkspaceMember, (ws_id, existing_user.id))
        if already_member is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a member of this workspace",
            )

    now = datetime.now(UTC)
    for invite in await _active_invitations(session, ws_id):
        if invite.email == body.email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active invitation for this email already exists",
            )

    invitation = Invitation(
        workspace_id=ws_id,
        email=body.email,
        role=body.role,
        token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(days=settings.invitation_expire_days),
        created_by=member.user_id,
    )
    session.add(invitation)
    await session.commit()
    return _to_response(invitation)


@router.get(
    "/workspaces/{ws_id}/invitations",
    response_model=list[InvitationResponse],
)
async def list_invitations(
    ws_id: uuid.UUID,
    member: AdminMember,
    session: DbSession,
) -> list[InvitationResponse]:
    return [_to_response(i) for i in await _active_invitations(session, ws_id)]


@router.delete(
    "/workspaces/{ws_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    ws_id: uuid.UUID,
    invitation_id: uuid.UUID,
    member: AdminMember,
    session: DbSession,
) -> None:
    invitation: Invitation | None = await session.get(Invitation, invitation_id)
    if invitation is None or invitation.workspace_id != ws_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    await session.delete(invitation)
    await session.commit()


@router.post("/invitations/{token}/accept", response_model=InvitationAcceptResponse)
async def accept_invitation(
    token: str,
    current_user: CurrentUser,
    session: DbSession,
) -> InvitationAcceptResponse:
    invitation = await session.scalar(select(Invitation).where(Invitation.token == token))
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if _as_utc(invitation.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation expired")
    if invitation.email != current_user.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invitation was issued for a different email",
        )
    existing = await session.get(WorkspaceMember, (invitation.workspace_id, current_user.id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already a member of this workspace",
        )

    # фиксируем до удаления: читать поля удалённого инстанса после commit — хрупко
    ws_id, role = invitation.workspace_id, invitation.role

    session.add(WorkspaceMember(workspace_id=ws_id, user_id=current_user.id, role=role))
    await session.delete(invitation)  # одноразовый
    await session.commit()

    workspace: Workspace | None = await session.get(Workspace, ws_id)
    return InvitationAcceptResponse(
        workspace_id=ws_id,
        workspace_name=workspace.name if workspace is not None else "",
        role=role,
    )