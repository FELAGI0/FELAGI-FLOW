import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base


class Schedule(Base):
    """Cron-расписание, синхронизируемое из графа при публикации (DESIGN.md §2).

    Одна строка на узел trigger_cron опубликованной версии. kind пока всегда
    'cron': poll-триггеры (Gmail/Sheets/Discord) появятся на этапе 6 вместе с
    курсором, который в MVP не нужен.
    """

    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    # 'cron' ('poll' — этап 6)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="cron")
    # cron-выражение, например "0 9 * * *"
    spec: Mapped[str] = mapped_column(String, nullable=False)
    # id узла-триггера в графе: по нему берём timezone и узнаём, что узел ещё жив
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # тик планировщика: выбрать всё, что пора запускать
        Index("ix_schedules_enabled_next_run_at", "enabled", "next_run_at"),
    )