from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # eager_defaults: server-side значения (created_at/updated_at с now() и onupdate)
    # возвращаются в том же стейтменте, а не остаются expired. Без этого чтение
    # updated_at после UPDATE в async-сессии падает с MissingGreenlet.
    # Директива ниже — потому что __mapper_args__ потребляется SQLAlchemy,
    # а не читается как обычный мутабельный атрибут класса.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
