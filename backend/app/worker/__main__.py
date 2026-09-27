"""Воркер: claim-цикл поверх Postgres-очереди.

Один процесс — один воркер; масштабирование — больше контейнеров
(docker compose --scale worker=N). Планировщик отдельно (scheduler).

Каждая итерация сначала возвращает в очередь задачи умерших воркеров
(reclaim_stale, раз в RECLAIM_INTERVAL_SECONDS), затем забирает одну задачу.
Reclaim идёт перед claim, чтобы зависшие запуски вернулись в пул, даже когда
у этого воркера своей работы нет.
"""

import asyncio
import contextlib
import signal
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.notify import notify_exec_log
from app.engine.queue import claim_next, complete, reclaim_stale
from app.engine.runner import ExecutionCancelled, NodeExecutionError, run_execution
from app.shared.config import settings
from app.shared.db import session_factory
from app.shared.logging import setup_logging
from app.shared.models import Execution, WorkflowVersion

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 1.0

# сколько «молчания» воркера считать падением (reclaim)
HEARTBEAT_TIMEOUT_SECONDS = 60

_shutdown = asyncio.Event()


def _request_shutdown() -> None:
    _shutdown.set()


async def maybe_reclaim(
    session: AsyncSession,
    last_reclaim_at: datetime | None,
    now: datetime | None = None,
    interval_seconds: int | None = None,
) -> tuple[int, datetime]:
    """Возвращает в очередь задачи умерших воркеров, если пришло время.

    Вынесена из цикла как чистая по смыслу функция: интервал сравнивается в
    памяти, к БД идём только когда срок наступил. Возвращает (reclaimed,
    новое время последнего reclaim).
    """
    moment = now or datetime.now(UTC)
    interval = settings.reclaim_interval_seconds if interval_seconds is None else interval_seconds

    if last_reclaim_at is not None and (moment - last_reclaim_at).total_seconds() < interval:
        return 0, last_reclaim_at

    reclaimed = await reclaim_stale(session, heartbeat_timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS)
    return reclaimed, moment


async def process_one(session: AsyncSession, execution: Execution, worker_id: str) -> None:
    """Выполняет один запуск и закрывает его статус. Любая ошибка → complete(fail).

    Шаги коммитятся сами (внутри run_execution, по одному). Здесь меняется только
    финальный статус execution, и он коммитится вызывающим (main). Финальный
    NOTIFY шлём в той же транзакции, что и смену статуса: иначе live-логи узнали
    бы о завершении только по таймауту heartbeat (DESIGN.md §3, «финальный NOTIFY»).
    """
    version = await session.get(WorkflowVersion, execution.workflow_version_id)
    if version is None:
        await complete(
            session,
            execution.id,
            success=False,
            error="pinned workflow version not found",
        )
        await notify_exec_log(session, execution.id)
        return

    try:
        await run_execution(session, execution, version, worker_id)
    except ExecutionCancelled:
        # отмена — терминальный статус, retry не нужен: оставляем 'canceled'
        execution.status = "canceled"
    except NodeExecutionError as exc:
        # падение узла — прикладная ошибка запуска
        await complete(session, execution.id, success=False, error=str(exc))
    except Exception as exc:
        await complete(session, execution.id, success=False, error=str(exc))
    else:
        await complete(session, execution.id, success=True)

    # статус либо терминальный, либо снова queued (retry) — в обоих случаях
    # подписчику WS полезно проснуться и перечитать состояние
    await notify_exec_log(session, execution.id)


async def main() -> None:
    setup_logging()
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    logger.info("worker.started", worker_id=worker_id)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows: add_signal_handler не поддерживается, полагаемся на KeyboardInterrupt
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    # время последнего reclaim; None — ещё ни разу (первый пройдёт сразу)
    last_reclaim_at: datetime | None = None

    while not _shutdown.is_set():
        async with session_factory() as session:
            # reclaim идёт ПЕРЕД claim: задачи умерших воркеров должны вернуться
            # в общий пул, в том числе когда своей работы у этого воркера нет.
            # Падение reclaim не должно ронять цикл — логируем и продолжаем.
            try:
                reclaimed, last_reclaim_at = await maybe_reclaim(
                    session, last_reclaim_at
                )
                if reclaimed > 0:
                    logger.info("worker.reclaimed", count=reclaimed)
                    await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error("worker.reclaim_failed", error=str(exc))

            execution = await claim_next(session, worker_id)
            if execution is None:
                await session.commit()
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue
            # фиксируем claim до долгой работы, чтобы другие воркеры видели locked_at
            await session.commit()

            logger.info("worker.claimed", worker_id=worker_id, execution_id=str(execution.id))
            await process_one(session, execution, worker_id)
            await session.commit()

    logger.info("worker.stopped", worker_id=worker_id)


if __name__ == "__main__":
    asyncio.run(main())