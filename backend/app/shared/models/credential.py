import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, TimestampMixin


class Credential(TimestampMixin, Base):
    """Секрет воркспейса (bot-токен, OAuth-токены), зашифрованный Fernet.

    DESIGN.md §"credentials" + ПРАВКА 12 (гибрид 6.A, Telegram-only):
    - payload наружу через API не возвращается - только метаданные;
    - удаление - soft-delete (`deleted_at`), все выборки фильтруют `IS NULL`;
    - `encryption_key_id` заложен под будущую ротацию (сейчас одно значение).
    """

    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # 'gmail'|'gsheets'|'notion'|'discord'|'telegram'|'anthropic'|'http'
    # строкой, не enum (как plan/role) - добавление сервиса не требует миграции типа
    service: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # 'oauth2'|'api_key'|'bot_token' - для Telegram bot_token
    auth_type: Mapped[str] = mapped_column(String, nullable=False)
    # Fernet-шифротекст (bytea): в БД секрет лежит только в зашифрованном виде
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # метка ключа Fernet; сейчас одно значение, поле - под будущую ротацию
    encryption_key_id: Mapped[str] = mapped_column(String, nullable=False, default="default")
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # soft-delete: физически строка остаётся (аудит, восстановление)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_credentials_workspace_service",
            "workspace_id",
            "service",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
