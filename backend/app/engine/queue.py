"""Очередь на Postgres — spike 3.D.

Только логика работы с очередью: без HTTP, без воркер-цикла, без runner.
Все функции работают на переданной AsyncSession и НЕ коммитят — коммит
остаётся за вызывающим. Это позволяет тестам управлять моментом фиксации
транзакции и проверять блокировки (SKIP LOCKED) детерминированно.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models.execution import Execution


def backoff(attempts: int) -> int:
    """Экспоненциальная задержка перед повтором, в секундах: 2, 4, 8, ..."""
    delay: int = 2**attempts
    return delay


async def enqueue(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    workflow_version_id: uuid.UUID,
    max_attempts: int = 3,
    trigger_payload: dict[str, Any] | None = None,
    trigger_type: str = "manual",
) -> Execution:
    """Ставит запуск в очередь, пиня версию графа.

    workflow_version_id обязателен: запуск должен выполняться ровно против той
    версии, что была актуальна в момент постановки, иначе правки черновика
    поменяют поведение уже идущего запуска.
    """
    execution = Execution(
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        status="queued",
        attempts=0,
        max_attempts=max_attempts,
        available_at=datetime.now(UTC),
        trigger_payload=trigger_payload or {},
        trigger_type=trigger_type,
    )
    session.add(execution)
    await session.flush()
    return execution


async def claim_next(session: AsyncSession, worker_id: str) -> Execution | None:
    """Берёт одну готовую задачу, помечает running.

    FOR UPDATE SKIP LOCKED — ключевой механизм: если строку уже держит другая
    транзакция, Postgres пропускает её вместо блокировки, поэтому N воркеров
    берут разные задачи без ожидания и без двойного выполнения.
    """
    now = datetime.now(UTC)
    execution_id = await session.scalar(
        select(Execution.id)
        .where(Execution.status == "queued", Execution.available_at <= now)
        .order_by(Execution.available_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if execution_id is None:
        return None

    await session.execute(
        update(Execution)
        .where(Execution.id == execution_id)
        .values(
            status="running",
            locked_by=worker_id,
            locked_at=now,
            started_at=now,
            attempts=Execution.attempts + 1,
        )
    )
    await session.flush()
    execution = await session.get(Execution, execution_id)
    if execution is not None:
        await session.refresh(execution)
    return execution


async def heartbeat(session: AsyncSession, execution_id: uuid.UUID, worker_id: str) -> None:
    """Продлевает владение задачей. Обновляется только своим воркером."""
    await session.execute(
        update(Execution)
        .where(Execution.id == execution_id, Execution.locked_by == worker_id)
        .values(locked_at=datetime.now(UTC))
    )
    await session.flush()


async def reclaim_stale(
    session: AsyncSession,
    heartbeat_timeout_seconds: int = 60,
) -> int:
    """Возвращает в очередь задачи, чей воркер замолчал (упал).

    attempts НЕ меняется: попытка уже была посчитана при claim, и после
    падения она не должна «сгорать» — иначе краш-цикл воркера исчерпает
    max_attempts, не выполнив задачу ни разу.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=heartbeat_timeout_seconds)
    # RETURNING вместо rowcount: rowcount у Result не типизирован в stubs,
    # а список возвращённых id и точнее (не зависит от драйвера), и нормально типизируется
    result = await session.execute(
        update(Execution)
        .where(Execution.status == "running", Execution.locked_at < cutoff)
        .values(status="queued", locked_by=None, locked_at=None)
        .returning(Execution.id)
    )
    reclaimed = len(result.scalars().all())
    await session.flush()
    return reclaimed


async def complete(
    session: AsyncSession,
    execution_id: uuid.UUID,
    success: bool,
    error: str | None = None,
) -> Execution | None:
    execution = await session.get(Execution, execution_id)
    if execution is None:
        return None

    now = datetime.now(UTC)
    if success:
        execution.status = "succeeded"
        execution.finished_at = now
        execution.locked_by = None
        execution.locked_at = None
    else:
        execution.error = error
        if execution.attempts < execution.max_attempts:
            execution.status = "queued"
            execution.available_at = now + timedelta(seconds=backoff(execution.attempts))
            execution.locked_by = None
            execution.locked_at = None
        else:
            execution.status = "dead"
            execution.finished_at = now

    await session.flush()
    return execution


async def queue_depth(session: AsyncSession) -> int:
    """Сколько задач готово к запуску прямо сейчас (для тестов и метрик)."""
    count: int | None = await session.scalar(
        select(func.count())
        .select_from(Execution)
        .where(Execution.status == "queued", Execution.available_at <= datetime.now(UTC))
    )
    return count or 0