"""Тесты live-логов execution через WebSocket (этап 5.B).

Синхронные (starlette TestClient): он сам держит portal-loop и поднимает
lifespan, в котором менеджер открывает LISTEN. Данные готовим отдельными
`asyncio.run` поверх NullPool-движка — так у каждого вызова свой loop и нет
пересечения пулов между portal-loop и pytest-asyncio.

Только Postgres: нужны pg_notify/LISTEN и отдельные соединения.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.ws_manager import ListenManager
from app.engine.queue import enqueue
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
from app.shared.security import create_access_token

pytestmark = pytest.mark.postgres

CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_TOO_MANY = 4429
CLOSE_NORMAL = 1000


def _async_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _dsn() -> str:
    return _async_url().replace("+asyncpg", "")


def _engine() -> AsyncEngine:
    return create_async_engine(_async_url(), poolclass=NullPool)


@pytest.fixture(autouse=True)
def _schema() -> None:
    """Гарантирует, что схема есть, даже если WS-тесты идут первыми в наборе."""

    async def _create() -> None:
        engine = _engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_create())


@pytest.fixture
def ws_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient с get_session, переопределённым на NullPool-фабрику тестовой БД.

    settings.database_url тоже указываем на тестовую БД: менеджер LISTEN читает
    её при старте lifespan (в проде это боевая БД, в тестах — felagi_test).
    """
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


def _seed(*, status: str = "running", steps: int = 0) -> dict[str, str]:
    """Создаёт user/workspace/workflow/version/execution (+шаги). Возвращает ids/token."""

    async def _run() -> dict[str, str]:
        engine = _engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            suffix = uuid.uuid4().hex[:8]
            user = User(email=f"ws-{suffix}@example.com", password_hash="h")
            session.add(user)
            await session.flush()
            workspace = Workspace(name="W", slug=f"ws-{suffix}", created_by=user.id)
            session.add(workspace)
            await session.flush()
            # членство обязательно: WS-авторизация проверяет WorkspaceMember,
            # а не created_by (как это делает реальная регистрация)
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
                graph={"nodes": [], "edges": [], "layout": {}},
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
            for index in range(steps):
                session.add(
                    ExecutionStep(
                        execution_id=execution.id,
                        node_id=f"n{index}",
                        node_type="debug",
                        sequence=index + 1,
                        attempt=1,
                        status="succeeded",
                        input={"i": index},
                        output={"o": index},
                        warnings=[],
                        duration_ms=1,
                    )
                )
            await session.commit()
            token = create_access_token(user.id)
            return {
                "user_id": str(user.id),
                "execution_id": str(execution.id),
                "token": token,
                "workspace_id": str(workspace.id),
            }
        await engine.dispose()

    return asyncio.run(_run())


def _add_step_and_notify(execution_id: str, node_id: str = "new") -> None:
    """Прямой INSERT шага + pg_notify, закоммиченные вместе (как делает runner)."""

    async def _run() -> None:
        engine = _engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            execution_uuid = uuid.UUID(execution_id)
            last = await session.scalar(
                select(func.max(ExecutionStep.sequence)).where(
                    ExecutionStep.execution_id == execution_uuid
                )
            )
            session.add(
                ExecutionStep(
                    execution_id=execution_uuid,
                    node_id=node_id,
                    node_type="debug",
                    sequence=(last or 0) + 1,
                    attempt=1,
                    status="succeeded",
                    input={},
                    output={"added": True},
                    warnings=[],
                    duration_ms=2,
                )
            )
            await session.flush()
            await session.execute(
                text("SELECT pg_notify('exec_log', :payload)"),
                {"payload": execution_id},
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


def _finish_and_notify(execution_id: str, status: str, error: str | None = None) -> None:
    async def _run() -> None:
        engine = _engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                update(Execution)
                .where(Execution.id == uuid.UUID(execution_id))
                .values(status=status, error=error)
            )
            await session.execute(
                text("SELECT pg_notify('exec_log', :payload)"),
                {"payload": execution_id},
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


def _notify_raw(execution_id: str) -> None:
    """NOTIFY с отдельного соединения, без изменения данных."""

    async def _run() -> None:
        connection = await asyncpg.connect(_dsn())
        await connection.execute("SELECT pg_notify('exec_log', $1)", execution_id)
        await connection.close()

    asyncio.run(_run())


# --- auth ---------------------------------------------------------------------


def test_ws_without_token_closes_4401(ws_client: TestClient) -> None:
    data = _seed()
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        ws_client.websocket_connect(f"/ws/executions/{data['execution_id']}") as ws,
    ):
        ws.receive_json()
    assert exc.value.code == CLOSE_UNAUTHORIZED


def test_ws_with_invalid_token_closes_4401(ws_client: TestClient) -> None:
    data = _seed()
    with pytest.raises(WebSocketDisconnect) as exc, ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token=not-a-jwt"
    ) as ws:
        ws.receive_json()
    assert exc.value.code == CLOSE_UNAUTHORIZED


def test_ws_with_foreign_token_closes_4404(ws_client: TestClient) -> None:
    """Токен валиден, но пользователь не member чужого workspace → 4404."""
    owner = _seed()
    stranger = _seed()
    with pytest.raises(WebSocketDisconnect) as exc, ws_client.websocket_connect(
        f"/ws/executions/{owner['execution_id']}?token={stranger['token']}"
    ) as ws:
        ws.receive_json()
    assert exc.value.code == CLOSE_NOT_FOUND


def test_ws_unknown_execution_closes_4404(ws_client: TestClient) -> None:
    data = _seed()
    with pytest.raises(WebSocketDisconnect) as exc, ws_client.websocket_connect(
        f"/ws/executions/{uuid.uuid4()}?token={data['token']}"
    ) as ws:
        ws.receive_json()
    assert exc.value.code == CLOSE_NOT_FOUND


# --- snapshot -----------------------------------------------------------------


def test_ws_snapshot_contains_execution_and_steps(ws_client: TestClient) -> None:
    data = _seed(status="running", steps=2)
    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        message = ws.receive_json()
    assert message["type"] == "snapshot"
    assert message["execution"]["id"] == data["execution_id"]
    assert len(message["steps"]) == 2
    assert {step["node_id"] for step in message["steps"]} == {"n0", "n1"}


def test_ws_snapshot_on_already_finished_execution(ws_client: TestClient) -> None:
    """Уже завершённый запуск: snapshot, затем сразу finished и close(1000)."""
    data = _seed(status="succeeded", steps=1)
    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        snapshot = ws.receive_json()
        finished = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert finished["type"] == "finished"
        assert finished["status"] == "succeeded"
        assert finished["error"] is None
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == CLOSE_NORMAL


# --- live-обновления ----------------------------------------------------------


def test_ws_receives_new_step_on_notify(ws_client: TestClient) -> None:
    data = _seed(status="running", steps=0)
    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["steps"] == []

        _add_step_and_notify(data["execution_id"], node_id="live1")
        message = ws.receive_json()

    assert message["type"] == "steps"
    assert [step["node_id"] for step in message["steps"]] == ["live1"]


def test_ws_ignores_notify_for_other_execution(ws_client: TestClient) -> None:
    """Свой notify доходит до соединения, даже если ему предшествовал чужой.

    Прямую маршрутизацию (чужой id НЕ будит соединение) проверяет
    test_listen_manager_routes_only_matching_execution: через WS это ненаблюдаемо,
    т.к. эндпоинт всегда перечитывает свой execution и дедуплицирует шаги —
    лишнее пробуждение при отсутствии новых шагов не даёт сообщения.
    """
    data = _seed(status="running", steps=0)
    other = _seed(status="running", steps=0)
    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        assert ws.receive_json()["type"] == "snapshot"

        # уведомление о другом запуске не должно дать сообщение этому соединению
        _notify_raw(other["execution_id"])

        _add_step_and_notify(data["execution_id"], node_id="mine")
        message = ws.receive_json()

    assert [step["node_id"] for step in message["steps"]] == ["mine"]


def test_ws_receives_finished_then_closes_1000(ws_client: TestClient) -> None:
    data = _seed(status="running", steps=1)
    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        assert ws.receive_json()["type"] == "snapshot"

        _finish_and_notify(data["execution_id"], "failed", error="boom")
        finished = ws.receive_json()
        assert finished["type"] == "finished"
        assert finished["status"] == "failed"
        assert finished["error"] == "boom"

        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == CLOSE_NORMAL


def test_ws_reconnect_snapshot_has_all_steps(ws_client: TestClient) -> None:
    """Разрыв и повторное подключение: snapshot отдаёт всё накопленное."""
    data = _seed(status="running", steps=0)
    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        assert ws.receive_json()["steps"] == []
        _add_step_and_notify(data["execution_id"], node_id="first")
        assert ws.receive_json()["type"] == "steps"

    # соединение закрыто; добавляем ещё шаг, пока никто не слушает
    _add_step_and_notify(data["execution_id"], node_id="second")

    with ws_client.websocket_connect(
        f"/ws/executions/{data['execution_id']}?token={data['token']}"
    ) as ws:
        snapshot = ws.receive_json()
    assert snapshot["type"] == "snapshot"
    assert {step["node_id"] for step in snapshot["steps"]} == {"first", "second"}


# --- лимит соединений ---------------------------------------------------------


def test_ws_connection_limit_per_user(ws_client: TestClient) -> None:
    """Сверх лимита одновременных соединений → close(4429)."""
    data = _seed(status="running")
    url = f"/ws/executions/{data['execution_id']}?token={data['token']}"

    sessions = []
    try:
        for _ in range(settings.ws_max_connections_per_user):
            ws = ws_client.websocket_connect(url)
            ws.__enter__()
            assert ws.receive_json()["type"] == "snapshot"
            sessions.append(ws)

        with (
            pytest.raises(WebSocketDisconnect) as exc,
            ws_client.websocket_connect(url) as extra,
        ):
            extra.receive_json()
        assert exc.value.code == CLOSE_TOO_MANY
    finally:
        for ws in sessions:
            ws.__exit__(None, None, None)


# --- менеджер LISTEN: прямая маршрутизация ------------------------------------


def test_listen_manager_routes_only_matching_execution() -> None:
    """Уведомление доходит только до подписчиков того же execution_id.

    Юнит-тест менеджера (без WS): через соединение это ненаблюдаемо — эндпоинт
    перечитывает свой execution и дедуплицирует шаги, поэтому лишнее пробуждение
    при отсутствии новых шагов не приводит к отправке сообщения.
    """
    manager = ListenManager()
    target = uuid.uuid4()
    other = uuid.uuid4()

    target_queue = manager.subscribe(target)
    other_queue = manager.subscribe(other)

    manager._on_notify(None, 0, "exec_log", str(target))

    assert target_queue.qsize() == 1
    assert other_queue.qsize() == 0

    manager.unsubscribe(target, target_queue)
    manager._on_notify(None, 0, "exec_log", str(target))
    assert target_queue.qsize() == 1  # после отписки новых не приходит


def test_listen_manager_fans_out_to_all_subscribers_of_same_execution() -> None:
    """Два соединения на один запуск — notify получают оба."""
    manager = ListenManager()
    execution_id = uuid.uuid4()
    first = manager.subscribe(execution_id)
    second = manager.subscribe(execution_id)

    manager._on_notify(None, 0, "exec_log", str(execution_id))

    assert first.qsize() == 1
    assert second.qsize() == 1


def test_per_user_connection_limit_is_counted() -> None:
    """register_connection упирается в лимит и освобождается release_connection."""
    manager = ListenManager()
    user_id = uuid.uuid4()

    for _ in range(settings.ws_max_connections_per_user):
        assert manager.register_connection(user_id) is True
    assert manager.register_connection(user_id) is False

    manager.release_connection(user_id)
    assert manager.register_connection(user_id) is True


# --- runner → NOTIFY (пункт 1) ------------------------------------------------


async def test_runner_notifies_on_each_step() -> None:
    """Реальный runner публикует NOTIFY: подписчик получает уведомление о запуске.

    Это проверка пункта 1 (NOTIFY в _record_step), а не канала WS: уведомления
    шлёт настоящий run_execution, слушаем отдельным asyncpg-соединением.

    ВАЖНО про количество: Postgres схлопывает ОДИНАКОВЫЕ уведомления внутри одной
    транзакции в одну доставку. Runner пишет все шаги в одной транзакции (коммит —
    в воркере один раз), payload — только execution_id, поэтому N шагов дают 1
    доставку. Именно поэтому здесь проверяем «уведомление пришло и совпадает с
    execution_id», а не «по уведомлению на шаг».
    """
    from app.engine.queue import claim_next
    from app.engine.runner import run_execution

    # данные через обычную async-сессию (этот тест уже в event loop pytest-asyncio)
    factory = async_sessionmaker(_engine(), expire_on_commit=False)
    listener = await asyncpg.connect(_dsn())

    received: list[str] = []

    def _record(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        received.append(payload)

    await listener.add_listener("exec_log", _record)

    try:
        async with factory() as session:
            suffix = uuid.uuid4().hex[:8]
            user = User(email=f"notify-{suffix}@example.com", password_hash="h")
            session.add(user)
            await session.flush()
            workspace = Workspace(name="W", slug=f"notify-{suffix}", created_by=user.id)
            session.add(workspace)
            await session.flush()
            workflow = Workflow(workspace_id=workspace.id, name="WF", created_by=user.id)
            session.add(workflow)
            await session.flush()
            graph = {
                "nodes": [
                    {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
                    {
                        "id": "d",
                        "type": "debug",
                        "params": {"message": "x"},
                        "position": {},
                    },
                ],
                "edges": [{"id": "e1", "source": "t", "target": "d"}],
                "layout": {},
            }
            version = WorkflowVersion(
                workflow_id=workflow.id, version=1, graph=graph, created_by=user.id
            )
            session.add(version)
            await session.flush()
            await enqueue(session, workflow.id, version.id, max_attempts=1)
            await session.commit()

            execution = await claim_next(session, "w1")
            assert execution is not None
            await session.commit()
            execution_id = str(execution.id)

            await run_execution(session, execution, version, "w1")
            # NOTIFY доставляется по COMMIT — без него уведомлений не будет
            await session.commit()

        # доставка асинхронна: даём серверу отправить уведомления
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.05)

        assert received, "runner не отправил ни одного NOTIFY"
        assert set(received) == {execution_id}
    finally:
        await listener.remove_listener("exec_log", _record)
        await listener.close()