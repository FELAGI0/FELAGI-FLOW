"""Порядок шагов выполнения (5.B-fix): sequence, сортировка REST/WS, live-доставка.

Причина появления: created_at = func.now() = время транзакции, у всех шагов
одного запуска совпадает, поэтому сортировка по нему произвольна. Введён
sequence (номер шага в запуске, с 1); runner коммитит каждый шаг отдельной
транзакцией и шлёт NOTIFY до коммита — live-логи видят шаги по мере выполнения.

Только Postgres: нужны pg_notify/LISTEN, SKIP LOCKED и отдельные соединения.
"""

import asyncio
import contextlib
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.engine.queue import claim_next, enqueue
from app.engine.runner import NodeExecutionError, run_execution, topological_order
from app.main import app
from app.shared.config import settings
from app.shared.db import get_session
from app.shared.models import (
    Base,
    Execution,
    ExecutionStep,
    User,
    Workflow,
    WorkflowVersion,
    Workspace,
    WorkspaceMember,
)
from app.shared.schemas.workflow import Graph
from app.shared.security import create_access_token

pytestmark = pytest.mark.postgres

PASSWORD = "password123"


def _async_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _dsn() -> str:
    """DSN без драйверного суффикса — для прямого подключения asyncpg (LISTEN)."""
    return _async_url().replace("+asyncpg", "")


def _engine() -> AsyncEngine:
    return create_async_engine(_async_url(), poolclass=NullPool)


def _linear_graph() -> dict[str, object]:
    """t → s → d: детерминированный топологический порядок."""
    return {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {
                "id": "s",
                "type": "transform_set",
                "params": {"fields": [{"name": "greeting", "value": "hi"}]},
                "position": {},
            },
            {"id": "d", "type": "debug", "params": {"message": "done"}, "position": {}},
        ],
        "edges": [
            {"id": "e1", "source": "t", "target": "s"},
            {"id": "e2", "source": "s", "target": "d"},
        ],
        "layout": {},
    }


@pytest.fixture(autouse=True)
def _schema() -> None:
    """Гарантирует наличие схемы, если эти тесты идут первыми в наборе."""

    async def _create() -> None:
        engine = _engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_create())


async def _fixture_workflow(
    session: AsyncSession, graph: dict[str, object]
) -> tuple[uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    user = User(email=f"order-{suffix}@example.com", password_hash="h")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="W", slug=f"order-{suffix}", created_by=user.id)
    session.add(workspace)
    await session.flush()
    workflow = Workflow(workspace_id=workspace.id, name="WF", created_by=user.id)
    session.add(workflow)
    await session.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id, version=1, graph=graph, created_by=user.id
    )
    session.add(version)
    await session.flush()
    return workflow.id, version.id


async def _run_once(session: AsyncSession, version_id: uuid.UUID) -> uuid.UUID:
    """claim + run_execution; возвращает id запуска. Шаги коммитятся внутри runner."""
    execution = await claim_next(session, "w1")
    assert execution is not None
    await session.commit()
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    await run_execution(session, execution, version, "w1")
    return execution.id


async def _steps_ordered(session: AsyncSession, execution_id: uuid.UUID) -> list[ExecutionStep]:
    rows = await session.scalars(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.sequence)
    )
    return list(rows)


# --- sequence + топологический порядок ----------------------------------------


async def test_steps_numbered_sequentially_in_topological_order(
    session: AsyncSession,
) -> None:
    """sequence = 1,2,3... и совпадает с порядком выполнения trigger→set→debug."""
    workflow_id, version_id = await _fixture_workflow(session, _linear_graph())
    await enqueue(session, workflow_id, version_id)
    await session.commit()

    execution_id = await _run_once(session, version_id)
    steps = await _steps_ordered(session, execution_id)

    assert [step.sequence for step in steps] == [1, 2, 3]
    assert [step.node_id for step in steps] == ["t", "s", "d"]
    # порядок из topological_order совпадает с порядком шагов
    order = topological_order(Graph.model_validate(_linear_graph()))
    assert [node.id for node in order] == [step.node_id for step in steps]


async def test_retry_attempts_get_distinct_sequences(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Попытки одного узла нумеруются последовательно: sequence уникален."""
    import app.engine.runner as runner_module
    from app.engine.nodes import handle as real_handle

    calls = {"count": 0}

    async def failing_debug(
        node_type: str, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        # узел debug падает всегда → три попытки при max_retries=2
        if node_type == "debug":
            calls["count"] += 1
            return {"error": f"boom {calls['count']}"}
        return await real_handle(node_type, params, context)

    monkeypatch.setattr(runner_module, "handle", failing_debug)

    graph = {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {
                "id": "d",
                "type": "debug",
                "params": {
                    "message": "x",
                    "retry": {"max_retries": 2, "backoff": "fixed", "base_s": 0.01},
                },
                "position": {},
            },
        ],
        "edges": [{"id": "e1", "source": "t", "target": "d"}],
        "layout": {},
    }
    workflow_id, version_id = await _fixture_workflow(session, graph)
    await enqueue(session, workflow_id, version_id)
    await session.commit()
    # узел падает всегда → run_execution бросает; шаги при этом уже закоммичены
    # (коммит на шаг), поэтому ловим ошибку и проверяем sequence
    workflows_execution = await claim_next(session, "w1")
    assert workflows_execution is not None
    await session.commit()
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    with contextlib.suppress(NodeExecutionError):
        await run_execution(session, workflows_execution, version, "w1")
    execution_id = workflows_execution.id
    steps = await _steps_ordered(session, execution_id)

    # t (succeeded) + d × 3 попытки = 4 шага, sequence 1..4 без повторов
    assert [step.sequence for step in steps] == [1, 2, 3, 4]
    assert len({step.sequence for step in steps}) == len(steps)


async def test_rerun_after_reclaim_does_not_duplicate_sequence(
    session: AsyncSession,
) -> None:
    """Повторный запуск (после reclaim) продолжает нумерацию, а не начинает с 1."""
    workflow_id, version_id = await _fixture_workflow(session, _linear_graph())
    await enqueue(session, workflow_id, version_id)
    await session.commit()

    execution = await claim_next(session, "w1")
    assert execution is not None
    await session.commit()
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None

    # первый прогон «падает» вручную: пишем один шаг и как будто воркер умер.
    # _record_step коммитит сам, поэтому шаг останется в БД.
    from app.engine.runner import StepCounter, _record_step

    first_node = Graph.model_validate(version.graph).nodes[0]
    await _record_step(
        session, execution.id, StepCounter().take(), first_node, "succeeded", None, None
    )

    # повторный прогон: счётчик должен продолжить с 2, а не с 1
    await run_execution(session, execution, version, "w1")
    steps = await _steps_ordered(session, execution.id)

    sequences = [step.sequence for step in steps]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences), f"дубли sequence: {sequences}"


# --- REST ---------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_rest_returns_steps_in_sequence_order(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    suffix = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/auth/register",
        json={"email": f"rest-{suffix}@example.com", "password": PASSWORD, "name": "R"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    workspaces = (await client.get("/api/workspaces", headers=_auth(token))).json()
    ws_id = workspaces[0]["id"]
    created = await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": "WF"}, headers=_auth(token)
    )
    wf_id = created.json()["id"]
    saved = await client.post(
        f"/api/workflows/{wf_id}/versions",
        json={"graph": _linear_graph(), "change_note": None},
        headers=_auth(token),
    )
    assert saved.status_code == 201, saved.text
    published = await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(token))
    assert published.status_code == 200, published.text

    run = await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    assert run.status_code == 201, run.text
    execution_id = run.json()["id"]

    claimed = await claim_next(session, "w1")
    assert claimed is not None
    await session.commit()
    version = await session.get(WorkflowVersion, claimed.workflow_version_id)
    assert version is not None
    await run_execution(session, claimed, version, "w1")

    detail = await client.get(f"/api/executions/{execution_id}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    steps = detail.json()["steps"]
    assert [step["node_id"] for step in steps] == ["t", "s", "d"]


# --- WS -----------------------------------------------------------------------


@pytest.fixture
def ws_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient с NullPool-сессией на тестовой БД (как в test_ws.py)."""
    url = _async_url()
    monkeypatch.setattr(settings, "database_url", url)
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _seed_execution(*, status: str = "running") -> dict[str, str]:
    """user → ws → workflow → version + execution. Возвращает ids/token."""

    async def _run() -> dict[str, str]:
        engine = _engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            suffix = uuid.uuid4().hex[:8]
            user = User(email=f"wsord-{suffix}@example.com", password_hash="h")
            session.add(user)
            await session.flush()
            workspace = Workspace(name="W", slug=f"wsord-{suffix}", created_by=user.id)
            session.add(workspace)
            await session.flush()
            session.add(
                WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
            )
            await session.flush()
            workflow = Workflow(workspace_id=workspace.id, name="WF", created_by=user.id)
            session.add(workflow)
            await session.flush()
            version = WorkflowVersion(
                workflow_id=workflow.id,
                version=1,
                graph=_linear_graph(),
                created_by=user.id,
            )
            session.add(version)
            await session.flush()
            execution = Execution(
                workflow_id=workflow.id,
                workflow_version_id=version.id,
                status=status,
                trigger_type="manual",
                attempts=1,
                max_attempts=3,
            )
            session.add(execution)
            await session.flush()
            await session.commit()
            return {
                "execution_id": str(execution.id),
                "version_id": str(version.id),
                "token": create_access_token(user.id),
            }
        await engine.dispose()

    return asyncio.run(_run())


def _insert_steps(execution_id: str, rows: list[tuple[str, int]]) -> None:
    """Прямой INSERT шагов с заданными (node_id, sequence) — для проверки сортировки."""

    async def _run() -> None:
        engine = _engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            for node_id, sequence in rows:
                session.add(
                    ExecutionStep(
                        execution_id=uuid.UUID(execution_id),
                        node_id=node_id,
                        node_type="debug",
                        sequence=sequence,
                        attempt=1,
                        status="succeeded",
                        input={},
                        output={},
                        warnings=[],
                        duration_ms=1,
                    )
                )
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


def test_ws_snapshot_returns_steps_in_sequence_order(ws_client: TestClient) -> None:
    """Snapshot отдаёт шаги по sequence, а не по node_id/created_at."""
    data = _seed_execution()
    # sequence намеренно расходится с node_id: z=1, a=2 → ожидаем [z, a]
    _insert_steps(data["execution_id"], [("z", 1), ("a", 2)])

    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        snapshot = ws.receive_json()

    assert snapshot["type"] == "snapshot"
    assert [step["node_id"] for step in snapshot["steps"]] == ["z", "a"]


def test_ws_and_rest_agree_on_step_order(ws_client: TestClient) -> None:
    """Один и тот же запуск: WS-snapshot и REST отдают одинаковый порядок.

    node_id подобраны так, чтобы порядок по sequence отличался от порядка по
    node_id — иначе тест не поймал бы рассинхрон двух сортировок.
    """
    data = _seed_execution()
    # по sequence: [z(1), a(2), m(3)]; по node_id: [a, m, z] — порядки разные
    _insert_steps(data["execution_id"], [("z", 1), ("a", 2), ("m", 3)])

    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        snapshot = ws.receive_json()
    ws_order = [step["node_id"] for step in snapshot["steps"]]

    rest = ws_client.get(
        f"/api/executions/{data['execution_id']}",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    rest_order = [step["node_id"] for step in rest.json()["steps"]]

    assert ws_order == ["z", "a", "m"]
    assert rest_order == ws_order


async def test_each_step_commit_delivers_separate_notification(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Коммит на шаг → отдельные NOTIFY, а не один схлопнутый батч.

    Доказательство коммита на шаг: три узла дают три отдельные доставки
    `exec_log`. Если бы шаги коммитились одной транзакцией в конце (как было до
    5.B-fix), Postgres схлопнул бы одинаковые payload'ы в одну доставку.

    Замедляем узлы, чтобы коммиты шли с разрывом во времени, — тогда доставки
    гарантированно раздельные.
    """
    import asyncpg

    import app.engine.runner as runner_module
    from app.engine.nodes import handle as real_handle

    async def slow_handle(
        node_type: str, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        await asyncio.sleep(0.15)
        return await real_handle(node_type, params, context)

    monkeypatch.setattr(runner_module, "handle", slow_handle)

    workflow_id, version_id = await _fixture_workflow(session, _linear_graph())
    await enqueue(session, workflow_id, version_id)
    await session.commit()

    execution = await claim_next(session, "w1")
    assert execution is not None
    await session.commit()
    execution_id = execution.id
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None

    listener = await asyncpg.connect(_dsn())
    received: list[str] = []

    def _record(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        received.append(payload)

    await listener.add_listener("exec_log", _record)
    try:
        await run_execution(session, execution, version, "w1")
        # дожидаемся доставки всех уведомлений
        for _ in range(60):
            if len(received) >= 3:
                break
            await asyncio.sleep(0.05)
    finally:
        await listener.remove_listener("exec_log", _record)
        await listener.close()

    # три шага → три отдельных уведомления (не один батч)
    assert received == [str(execution_id)] * 3, received