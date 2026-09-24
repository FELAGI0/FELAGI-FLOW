import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    created_at: datetime
    # роль текущего пользователя в этом workspace — чтобы UI знал, что показывать
    current_user_role: str


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1)


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    name: str | None
    role: str
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    # owner через этот эндпоинт не назначается — Literal отсекает на 422
    role: Literal["admin", "member"]