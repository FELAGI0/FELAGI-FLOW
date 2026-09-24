import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base


class ExecutionStep(Base):
    """Один шаг выполнения: что подали на вход узлу, что получили, сколько заняло.

    warnings отделены от error (DESIGN.md, ПРАВКА 5): error — падение шага,
    warnings — нефатальные замечания (например, несовпадение типов в If),
    которые не влияют на статус.
    """

    __tablename__ = "execution_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    node_type: Mapped[str] = mapped_column(String, nullable=False)
    # 'running'|'succeeded'|'failed'|'skipped'
    status: Mapped[str] = mapped_column(String, nullable=False)
    input: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_execution_steps_execution_id", "execution_id"),
        # дедупликация сайд-эффектов при at-least-once (DESIGN.md §2)
        Index("ix_execution_steps_idempotency_key", "idempotency_key"),
    )