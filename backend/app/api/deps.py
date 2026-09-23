import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db import get_session
from app.shared.models import User, Workspace, WorkspaceMember
from app.shared.security import ACCESS_TOKEN_TYPE, decode_token

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)

BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    credentials: BearerCredentials,
    session: DbSession,
) -> User:
    if credentials is None:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _UNAUTHORIZED from None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise _UNAUTHORIZED
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _UNAUTHORIZED from None
    user: User | None = await session.get(User, user_id)
    if user is None:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_workspace_member(
    ws_id: uuid.UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> WorkspaceMember:
    """404 если workspace нет, 403 если user не участник."""
    workspace: Workspace | None = await session.get(Workspace, ws_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    member: WorkspaceMember | None = await session.get(WorkspaceMember, (ws_id, current_user.id))
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this workspace"
        )
    return member


WorkspaceMemberDep = Annotated[WorkspaceMember, Depends(get_workspace_member)]


def require_role(*roles: str) -> Callable[..., Awaitable[WorkspaceMember]]:
    """Фабрика dependency: require_role("owner", "admin") → 403 при несоответствии роли."""

    async def _dependency(member: WorkspaceMemberDep) -> WorkspaceMember:
        if member.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return member

    return _dependency