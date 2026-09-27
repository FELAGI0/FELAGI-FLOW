"""Reclaim в воркер-цикле: `maybe_reclaim` возвращает задачи умерших воркеров.

Только Postgres: SQLite не реализует нужные блокировки/типы. Проверяем и
чистую функцию (гейтинг по интервалу), и её эффект на очередь.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.queue import claim_next, enqueue
from app.shared.models import Execution, User, Workflow, WorkflowVersion, Workspace
from app.worker.__main__ import maybe_reclaim

pytestmark = pytest.mark.postgres


async def _make_workflow(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="h")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="W", slug=uuid.uuid4().hex[:12], created_by=user.id)
    session.add(workspace)
    await session.flush()
    workflow = Workflow(workspace_id=workspace.id, name="WF", created_by=user.id)
    session.add(workflow)
    await session.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id, version=1, graph={"nodes": [], "edges": []}, created_by=user.id
    )
    session.add(version)
    await session.flush()
    return workflow.id, version.id


async def _stale_running(session: AsyncSession, *, minutes_ago: int = 5) -> uuid.UUID:
    """Запуск в running с состаренным locked_at (как будто воркер «замолчал»)."""
    workflow_id, version_id = await _make_workflow(session)
    await enqueue(session, workflow_id, version_id)
    await session.commit()

    execution = await claim_next(session, "dead-worker")
    assert execution is not None
    await session.commit()

    await session.execute(
        update(Execution)
        .where(Execution.id == execution.id)
        .values(locked_at=datetime.now(UTC) - timedelta(minutes=minutes_ago))
    )
    await session.commit()
    return execution.id


async def _status(session: AsyncSession, execution_id: uuid.UUID) -> str:
    value = await session.scalar(select(Execution.status).where(Execution.id == execution_id))
    assert value is not None
    return value


async def test_maybe_reclaim_returns_stale_to_queue(session: AsyncSession) -> None:
    """Задача подвисшего воркера возвращается в queued — и её снова можно взять."""
    execution_id = await _stale_running(session)
    assert await _status(session, execution_id) == "running"

    reclaimed, _ = await maybe_reclaim(session, last_reclaim_at=None)
    await session.commit()

    assert reclaimed == 1
    assert await _status(session, execution_id) == "queued"
    # задача снова доступна забору (attempts не «сгорел»)
    claimed = await claim_next(session, "fresh-worker")
    assert claimed is not None
    assert claimed.id == execution_id


async def test_maybe_reclaim_skips_within_interval(session: AsyncSession) -> None:
    """Внутри интервала к БД не идём: ничего не возвращается, время не сдвигается."""
    await _stale_running(session)
    now = datetime.now(UTC)

    # последний reclaim был только что → пропуск
    reclaimed, new_last = await maybe_reclaim(
        session, last_reclaim_at=now, now=now, interval_seconds=30
    )
    assert reclaimed == 0
    assert new_last == now


async def test_maybe_reclaim_runs_after_interval(session: AsyncSession) -> None:
    """Спустя интервал reclaim выполняется и обновляет метку времени."""
    execution_id = await _stale_running(session)
    now = datetime.now(UTC)
    stale_mark = now - timedelta(seconds=31)

    reclaimed, new_last = await maybe_reclaim(
        session, last_reclaim_at=stale_mark, now=now, interval_seconds=30
    )
    await session.commit()

    assert reclaimed == 1
    assert new_last == now
    assert await _status(session, execution_id) == "queued"


async def test_maybe_reclaim_leaves_fresh_locks_alone(session: AsyncSession) -> None:
    """Свежий locked_at (воркер жив) не трогаем."""
    workflow_id, version_id = await _make_workflow(session)
    await enqueue(session, workflow_id, version_id)
    await session.commit()
    execution = await claim_next(session, "alive-worker")
    assert execution is not None
    await session.commit()

    reclaimed, _ = await maybe_reclaim(session, last_reclaim_at=None)
    await session.commit()

    assert reclaimed == 0
    assert await _status(session, execution.id) == "running"