import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base


class Execution(Base):
    """Очередь выполнения: одновременно журнал запусков и рабочая очередь.

    Схема — предмет spike 3.D: проверяем, что claim через SKIP LOCKED,
    heartbeat-reclaim и retry с backoff держатся на Postgres без брокера.
    """

    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    # 'queued'|'running'|'succeeded'|'failed'|'dead'
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # очередь: берём только готовые к запуску, по порядку available_at
        Index(
            "ix_executions_queue",
            "status",
            "available_at",
            postgresql_where=text("status = 'queued'"),
        ),
        # поиск зависших: reclaim сканирует только running
        Index(
            "ix_executions_running_locked_at",
            "locked_at",
            postgresql_where=text("status = 'running'"),
        ),
        # история запусков по workflow
        Index("ix_executions_workflow_created_at", "workflow_id", text("created_at DESC")),
    )