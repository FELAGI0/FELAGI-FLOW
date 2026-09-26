"""Планировщик: тик по cron-расписаниям (DESIGN.md §3, этап 5).

Один экземпляр в кластере: advisory-lock на уровне сессии Postgres. Тик
делает ровно одно: превращает «созревшие» Schedule в Execution'ы со статусом
queued, сдвигая next_run_at. Само выполнение — за воркерами.

pg_try_advisory_lock, а не pg_advisory_lock: второй заблокировал бы процесс на
неопределённое время, а нам нужен именно «не смог взять — пропустил тик».
"""

import asyncio
import contextlib
import signal
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.cron import next_run_at
from app.engine.node_schemas import DEFAULT_TIMEZONE
from app.engine.queue import enqueue
from app.shared.db import session_factory
from app.shared.logging import setup_logging
from app.shared.models import Schedule, Workflow, WorkflowVersion

logger = structlog.get_logger()

SCHEDULER_TICK_SECONDS = 15
# произвольный, но фиксированный ключ: он один на весь кластер
SCHEDULER_LOCK_ID = 0x5EC0_1ED0
# если lock взять не удалось (тик идёт в другом инстансе) — короткая пауза,
# чтобы не долбить БД в цикле
LOCK_RETRY_SECONDS = 5

_shutdown = asyncio.Event()


def _request_shutdown() -> None:
    _shutdown.set()


async def _due_schedules(session: AsyncSession, now: datetime) -> list[Schedule]:
    """Созревшие расписания: enabled, next_run_at <= now, с блокировкой строк.

    FOR UPDATE SKIP LOCKED — тот же приём, что в очереди: строки, которые уже
    кто-то держит, пропускаются, поэтому второй планировщик не запустит то же
    расписание повторно.
    """
    rows = await session.scalars(
        select(Schedule)
        .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
        .order_by(Schedule.next_run_at)
        .with_for_update(skip_locked=True)
    )
    return list(rows)


async def _timezone_for(session: AsyncSession, schedule: Schedule) -> str:
    """Зона берётся из графа опубликованной версии, а не хранится в Schedule.

    Так смена timezone в узле применяется при следующей публикации, и нет
    второй копии параметра, которая могла бы разойтись с графом.
    """
    workflow = await session.get(Workflow, schedule.workflow_id)
    if workflow is None or workflow.published_version_id is None:
        return DEFAULT_TIMEZONE
    version = await session.get(WorkflowVersion, workflow.published_version_id)
    if version is None:
        return DEFAULT_TIMEZONE
    for node in version.graph.get("nodes", []):
        if node.get("id") == schedule.node_id:
            timezone = node.get("params", {}).get("timezone")
            if isinstance(timezone, str) and timezone:
                return timezone
    return DEFAULT_TIMEZONE


async def run_tick(session: AsyncSession, now: datetime | None = None) -> int:
    """Один тик: запускает созревшие расписания. Возвращает число запусков."""
    moment = now or datetime.now(UTC)
    created = 0

    for schedule in await _due_schedules(session, moment):
        workflow = await session.get(Workflow, schedule.workflow_id)
        if workflow is None or workflow.published_version_id is None:
            # workflow снят с публикации: запускать нечего, но расписание
            # оставляем и просто откладываем — иначе оно «застрянет» на
            # прошлом моменте и после повторной публикации зальёт очередью
            timezone = DEFAULT_TIMEZONE
            schedule.next_run_at = next_run_at(schedule.spec, timezone, moment)
            logger.warning(
                "scheduler.skipped_unpublished",
                schedule_id=str(schedule.id),
                workflow_id=str(schedule.workflow_id),
            )
            continue

        timezone = await _timezone_for(session, schedule)
        await enqueue(
            session,
            workflow.id,
            workflow.published_version_id,
            trigger_type="cron",
            # момент срабатывания кладём в payload: узел trigger_cron отдаёт его
            # как scheduled_time, и повторный запуск даёт то же значение
            trigger_payload={"scheduled_time": moment.isoformat()},
        )
        schedule.last_run_at = moment
        schedule.next_run_at = next_run_at(schedule.spec, timezone, moment)
        created += 1

    return created


async def main() -> None:
    setup_logging()
    logger.info("scheduler.started", tick_seconds=SCHEDULER_TICK_SECONDS)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows: add_signal_handler не поддерживается, полагаемся на KeyboardInterrupt
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    while not _shutdown.is_set():
        async with session_factory() as session:
            locked = await session.scalar(select(func.pg_try_advisory_lock(SCHEDULER_LOCK_ID)))
            if not locked:
                logger.debug("scheduler.lock_busy")
                await asyncio.sleep(LOCK_RETRY_SECONDS)
                continue
            try:
                created = await run_tick(session)
                await session.commit()
                if created:
                    logger.info("scheduler.enqueued", count=created)
            except Exception as exc:
                # тик упал: откатываем, но планировщик не останавливаем —
                # иначе одна кривая строка расписания убьёт все остальные
                await session.rollback()
                logger.error("scheduler.tick_failed", error=str(exc))
            finally:
                await session.execute(select(func.pg_advisory_unlock(SCHEDULER_LOCK_ID)))

        await asyncio.sleep(SCHEDULER_TICK_SECONDS)

    logger.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(main())