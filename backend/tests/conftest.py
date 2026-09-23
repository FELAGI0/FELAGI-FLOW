import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.shared.models import Base


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Тесты с маркером postgres скипаются, если TEST_DATABASE_URL не указывает на Postgres."""
    url = os.environ.get("TEST_DATABASE_URL", "")
    if url.startswith("postgresql"):
        return
    skip = pytest.mark.skip(reason="requires Postgres (TEST_DATABASE_URL)")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # TEST_DATABASE_URL задаёт целевой диалект (Postgres в CI), иначе SQLite in-memory
    url = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    engine = create_async_engine(url)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_connection: Any, _record: Any) -> None:
            # в SQLite проверка FK по умолчанию выключена — без неё ondelete=CASCADE не работает
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()
