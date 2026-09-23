import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr


class InvitationCreate(BaseModel):
    email: EmailStr
    # owner нельзя пригласить — Literal отсекает это на 422
    role: Literal["admin", "member"] = "member"


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    expires_at: datetime
    created_at: datetime
    invite_url: str


class InvitationAcceptResponse(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    role: str