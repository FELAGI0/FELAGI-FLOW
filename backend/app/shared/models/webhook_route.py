import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base

# длина token_urlsafe(32) — 43 символа; колонка с запасом
TOKEN_BYTES = 32


def generate_token() -> str:
    """Токен вебхука = секрет (URL неугадываем), а не идентификатор."""
    return secrets.token_urlsafe(TOKEN_BYTES)


class WebhookRoute(Base):
    """Публичный вебхук: token → (workflow, узел-триггер).

    Синхронизируется из графа при публикации. Приём вебхука — один lookup по
    первичному ключу, без разбора JSONB (DESIGN.md §2).
    """

    __tablename__ = "webhook_routes"

    token: Mapped[str] = mapped_column(String, primary_key=True, default=generate_token)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    # id узла trigger_webhook в графе: из его params берём разрешённые methods
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # sync при публикации ищет маршруты конкретного workflow
        Index("ix_webhook_routes_workflow_id", "workflow_id"),
    )