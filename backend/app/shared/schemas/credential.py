import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CredentialCreate(BaseModel):
    """Создание credential. `payload` - секрет (для Telegram: {"token": "..."}).

    `service` - Literal на текущий единственный сервис (ПРАВКА 12, Telegram-only);
    расширение списка - по мере добавления сервисов.
    """

    service: Literal["telegram"]
    name: str = Field(min_length=1, max_length=100)
    payload: dict[str, str]


class CredentialResponse(BaseModel):
    """Метаданные credential. Секрет (payload) наружу НЕ возвращается."""

    id: uuid.UUID
    service: str
    auth_type: str
    name: str
    created_at: datetime


class CredentialListResponse(BaseModel):
    items: list[CredentialResponse]
