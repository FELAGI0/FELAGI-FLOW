"""Spike 3.D: жизнеспособность очереди на Postgres.

Только Postgres: SQLite не реализует FOR UPDATE SKIP LOCKED — тесты на нём
проходили бы, ничего не проверяя. Все тесты помечены @pytest.mark.postgres.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.engine.queue import (
    backoff,
    claim_next,
    complete,
    enqueue,
    heartbeat,
    queue_depth,
    reclaim_stale,
)
from app.shared.models import Execution, User, Workflow, WorkflowVersion, Workspace

pytestmark = pytest.mark.postgres


async def _make_workflow(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Создаёт workflow с одной версией. Возвращает (workflow_id, version_id):
    enqueue требует пин версии, т.к. запуск выполняется против конкретной версии."""
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


@pytest.fixture
async def session_factory(session: AsyncSession) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Отдельный движок к той же БД — для тестов с двумя параллельными сессиями.

    Зависит от `session`, чтобы гарантировать созданную conftest'ом схему.
    """
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


# --- enqueue / claim ----------------------------------------------------------


async def test_enqueue_creates_queued_execution(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    execution = await enqueue(session, wf_id, ver_id)

    assert execution.status == "queued"
    assert execution.attempts == 0
    assert execution.max_attempts == 3
    assert execution.available_at is not None
    assert execution.locked_by is None


async def test_claim_next_marks_running_and_increments_attempts(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()

    claimed = await claim_next(session, "worker-a")

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.locked_by == "worker-a"
    assert claimed.attempts == 1
    assert claimed.locked_at is not None
    assert claimed.started_at is not None


async def test_claim_next_empty_queue_returns_none(session: AsyncSession) -> None:
    assert await claim_next(session, "worker-a") is None


async def test_claim_next_skips_future_available_at(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.execute(
        update(Execution).values(available_at=datetime.now(UTC) + timedelta(hours=1))
    )
    await session.commit()

    assert await claim_next(session, "worker-a") is None


async def test_claim_next_respects_order(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    first = await enqueue(session, wf_id, ver_id)
    second = await enqueue(session, wf_id, ver_id)
    now = datetime.now(UTC)
    await session.execute(
        update(Execution).where(Execution.id == first.id).values(
            available_at=now - timedelta(minutes=5)
        )
    )
    await session.execute(
        update(Execution).where(Execution.id == second.id).values(
            available_at=now - timedelta(minutes=1)
        )
    )
    await session.commit()

    claimed = await claim_next(session, "worker-a")
    assert claimed is not None
    assert claimed.id == first.id  # самая ранняя по available_at


# --- главный тест: параллельный claim ------------------------------------------


async def test_two_parallel_claims_do_not_take_same_execution(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """SKIP LOCKED: два воркера одновременно берут РАЗНЫЕ задачи."""
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await enqueue(session, wf_id, ver_id)
    await session.commit()

    session_a: AsyncSession = session_factory()
    session_b: AsyncSession = session_factory()
    try:
        # A берёт задачу и держит блокировку строки (транзакция не закоммичена)
        claimed_a = await claim_next(session_a, "worker-a")
        # B в это же время пытается взять — заблокированную строку Postgres пропускает
        claimed_b = await claim_next(session_b, "worker-b")

        assert claimed_a is not None
        assert claimed_b is not None
        assert claimed_a.id != claimed_b.id, "оба воркера взяли одну задачу!"

        await session_a.commit()
        await session_b.commit()

        rows = await session.execute(
            select(Execution.id).where(Execution.status == "running")
        )
        running = rows.scalars().all()
        assert len(running) == 2
        assert len(set(running)) == 2
    finally:
        await session_a.close()
        await session_b.close()


async def test_parallel_claim_single_row_second_gets_none(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Одна задача: второй воркер не ждёт и не берёт её — получает None."""
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()

    session_a: AsyncSession = session_factory()
    session_b: AsyncSession = session_factory()
    try:
        claimed_a = await claim_next(session_a, "worker-a")
        claimed_b = await claim_next(session_b, "worker-b")

        assert claimed_a is not None
        assert claimed_b is None
        await session_a.commit()
    finally:
        await session_a.close()
        await session_b.close()


# --- heartbeat ----------------------------------------------------------------


async def test_heartbeat_updates_locked_at(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()
    claimed = await claim_next(session, "worker-a")
    assert claimed is not None

    stale = datetime.now(UTC) - timedelta(minutes=5)
    await session.execute(
        update(Execution).where(Execution.id == claimed.id).values(locked_at=stale)
    )
    await session.commit()
    await heartbeat(session, claimed.id, "worker-a")
    await session.commit()

    refreshed = await session.get(Execution, claimed.id)
    assert refreshed is not None
    assert refreshed.locked_at is not None
    assert refreshed.locked_at > stale


async def test_heartbeat_from_other_worker_is_ignored(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()
    claimed = await claim_next(session, "worker-a")
    assert claimed is not None
    locked_at = claimed.locked_at

    await session.commit()
    await heartbeat(session, claimed.id, "worker-b")  # чужой воркер
    await session.commit()

    refreshed = await session.get(Execution, claimed.id)
    assert refreshed is not None
    assert refreshed.locked_at == locked_at  # не изменилось


# --- reclaim ------------------------------------------------------------------


async def test_reclaim_returns_stale_to_queue_without_changing_attempts(
    session: AsyncSession,
) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()
    claimed = await claim_next(session, "worker-a")
    assert claimed is not None
    assert claimed.attempts == 1
    await session.commit()

    await session.execute(
        update(Execution)
        .where(Execution.id == claimed.id)
        .values(locked_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    await session.commit()

    returned = await reclaim_stale(session, heartbeat_timeout_seconds=60)
    await session.commit()

    assert returned == 1
    refreshed = await session.get(Execution, claimed.id)
    assert refreshed is not None
    assert refreshed.status == "queued"
    assert refreshed.locked_by is None
    assert refreshed.locked_at is None
    assert refreshed.attempts == 1  # попытка не «сгорела» при reclaim


async def test_reclaim_leaves_fresh_locks_alone(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()
    claimed = await claim_next(session, "worker-a")
    assert claimed is not None
    await session.commit()

    returned = await reclaim_stale(session, heartbeat_timeout_seconds=60)
    await session.commit()

    assert returned == 0
    refreshed = await session.get(Execution, claimed.id)
    assert refreshed is not None
    assert refreshed.status == "running"


# --- complete -----------------------------------------------------------------


async def test_complete_success(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()
    claimed = await claim_next(session, "worker-a")
    assert claimed is not None

    result = await complete(session, claimed.id, success=True)
    await session.commit()

    assert result is not None
    assert result.status == "succeeded"
    assert result.finished_at is not None


async def test_complete_failure_reschedules_with_backoff(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id, max_attempts=3)
    await session.commit()
    claimed = await claim_next(session, "worker-a")
    assert claimed is not None
    assert claimed.attempts == 1

    before = datetime.now(UTC)
    result = await complete(session, claimed.id, success=False, error="boom")
    await session.commit()

    assert result is not None
    assert result.status == "queued"
    assert result.error == "boom"
    assert result.available_at > before  # отложена на backoff
    # backoff(1) = 2s
    assert result.available_at >= before + timedelta(seconds=2)


async def test_complete_failure_exhausted_retries_goes_dead(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    execution = await enqueue(session, wf_id, ver_id, max_attempts=3)
    # имитируем третью попытку
    await session.execute(
        update(Execution)
        .where(Execution.id == execution.id)
        .values(status="running", attempts=3, locked_by="worker-a", locked_at=datetime.now(UTC))
    )
    await session.commit()

    result = await complete(session, execution.id, success=False, error="final")
    await session.commit()

    assert result is not None
    assert result.status == "dead"
    assert result.finished_at is not None


# --- backoff ------------------------------------------------------------------


@pytest.mark.parametrize(("attempts", "expected"), [(1, 2), (2, 4), (3, 8)])
def test_backoff_exponential(attempts: int, expected: int) -> None:
    assert backoff(attempts) == expected


# --- spike: kill -9 -----------------------------------------------------------


async def test_worker_killed_during_execution(session: AsyncSession) -> None:
    """Воркер падает посреди работы: задача подхватывается, но не выполняется дважды."""
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    await session.commit()

    # 1-2. воркер A берёт задачу и «умирает»: ни complete, ни heartbeat
    claimed_a = await claim_next(session, "worker-a")
    assert claimed_a is not None
    assert claimed_a.attempts == 1
    await session.commit()  # его claim зафиксирован; процесс убит

    # проверяем, что задачу сейчас никто не может взять как новую
    assert await claim_next(session, "worker-b") is None

    # 3. время прошло (симулируем: locked_at в прошлое)
    await session.execute(
        update(Execution)
        .where(Execution.id == claimed_a.id)
        .values(locked_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    await session.commit()

    # 4. воркер B возвращает зависшую задачу в очередь
    returned = await reclaim_stale(session, heartbeat_timeout_seconds=60)
    await session.commit()
    assert returned == 1

    # 5. воркер B берёт ту же задачу
    claimed_b = await claim_next(session, "worker-b")
    assert claimed_b is not None
    assert claimed_b.id == claimed_a.id

    # 6. attempts=2 — попытка A не потерялась и не удвоилась
    assert claimed_b.attempts == 2
    await session.commit()


async def test_queue_depth_counts_only_ready(session: AsyncSession) -> None:
    wf_id, ver_id = await _make_workflow(session)
    await enqueue(session, wf_id, ver_id)
    delayed = await enqueue(session, wf_id, ver_id)
    await session.execute(
        update(Execution)
        .where(Execution.id == delayed.id)
        .values(available_at=datetime.now(UTC) + timedelta(hours=1))
    )
    await session.commit()

    assert await queue_depth(session) == 1