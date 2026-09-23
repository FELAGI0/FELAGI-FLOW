import re
import secrets
import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, get_current_user
from app.shared.config import settings
from app.shared.models import User, Workspace, WorkspaceMember
from app.shared.schemas.auth import LoginRequest, MeResponse, RegisterRequest, TokenResponse
from app.shared.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# DESIGN.md §5: префикс /api у всего, кроме /hooks. Cookie path обязан совпадать
# с префиксом роутов, иначе браузер не пришлёт refresh на /api/auth/refresh.
AUTH_PREFIX = "/api/auth"

router = APIRouter(prefix=AUTH_PREFIX, tags=["auth"])

REFRESH_COOKIE = "refresh_token"

CurrentUser = Annotated[User, Depends(get_current_user)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]
# `= None` обязателен: в Annotated-стиле опциональность даёт default, а не `| None`,
# иначе отсутствующая cookie → 422 вместо нашего 401

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired refresh token",
)


def _set_refresh_cookie(response: Response, user_id: uuid.UUID) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=create_refresh_token(user_id),
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=AUTH_PREFIX,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE, path=AUTH_PREFIX)


def _slug_from_email(email: str) -> str:
    local = email.split("@")[0]
    slug = re.sub(r"[^a-z0-9]+", "-", local.lower()).strip("-")
    return slug or "workspace"


async def _unique_slug(session: AsyncSession, base: str) -> str:
    # ponytail: одна проверка на коллизию; при частых совпадениях local-part нужен счётчик
    exists: uuid.UUID | None = await session.scalar(
        select(Workspace.id).where(Workspace.slug == base)
    )
    return base if exists is None else f"{base}-{secrets.token_hex(3)}"


async def _find_user(session: AsyncSession, email: str) -> User | None:
    user: User | None = await session.scalar(select(User).where(User.email == email))
    return user


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
async def register(body: RegisterRequest, response: Response, session: DbSession) -> TokenResponse:
    if await _find_user(session, body.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(email=body.email, password_hash=hash_password(body.password), name=body.name)
    session.add(user)
    await session.flush()  # user.id присваивается на flush (default=uuid4)

    display = body.name or body.email.split("@")[0]
    workspace = Workspace(
        name=f"{display}'s workspace",
        slug=await _unique_slug(session, _slug_from_email(body.email)),
        created_by=user.id,
    )
    session.add(workspace)
    await session.flush()

    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await session.commit()

    _set_refresh_cookie(response, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, session: DbSession) -> TokenResponse:
    user = await _find_user(session, body.email)
    # одинаковая ошибка и для «нет такого», и для «не тот пароль» — не раскрываем существование
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _set_refresh_cookie(response, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/refresh")
async def refresh(response: Response, refresh_token: RefreshCookie = None) -> TokenResponse:
    if refresh_token is None:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(refresh_token)
    except jwt.InvalidTokenError:
        raise _UNAUTHORIZED from None
    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise _UNAUTHORIZED
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _UNAUTHORIZED from None

    _set_refresh_cookie(response, user_id)  # ротация: старый refresh заменяется новым
    return TokenResponse(access_token=create_access_token(user_id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    # возвращаем None: новый Response отбросил бы cookie, поставленный на инжектированный
    _clear_refresh_cookie(response)


@router.get("/me")
async def me(current_user: CurrentUser) -> MeResponse:
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        created_at=current_user.created_at,
    )
