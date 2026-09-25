"""Воркер: claim-цикл поверх Postgres-очереди.

Один процесс — один воркер; масштабирование — больше контейнеров
(docker compose --scale worker=N). Планировщик отдельно (scheduler).
"""

import asyncio
import contextlib
import signal
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.queue import claim_next, complete
from app.engine.runner import ExecutionCancelled, NodeExecutionError, run_execution
from app.shared.db import session_factory
from app.shared.logging import setup_logging
from app.shared.models import Execution, WorkflowVersion

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 1.0

_shutdown = asyncio.Event()


def _request_shutdown() -> None:
    _shutdown.set()


async def process_one(session: AsyncSession, execution: Execution, worker_id: str) -> None:
    """Выполняет один запуск и закрывает его статус. Любая ошибка → complete(fail)."""
    version = await session.get(WorkflowVersion, execution.workflow_version_id)
    if version is None:
        await complete(
            session,
            execution.id,
            success=False,
            error="pinned workflow version not found",
        )
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


async def main() -> None:
    setup_logging()
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    logger.info("worker.started", worker_id=worker_id)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows: add_signal_handler не поддерживается, полагаемся на KeyboardInterrupt
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    while not _shutdown.is_set():
        async with session_factory() as session:
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