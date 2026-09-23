import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db import get_session
from app.shared.models import User
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
