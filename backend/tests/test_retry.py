"""Тесты per-node retry (4.C): backoff, номер попытки, heartbeat между попытками.

Отказ узла подменяется на уровне runner.handle (см. _stub_debug): так тест
проверяет именно retry-цикл runner'а, а не поведение конкретного узла, и
остаётся детерминированным (без сети и без реального узла, который «иногда»
падает). Граф при этом всегда валиден — иначе runner упал бы на валидации
параметров ещё до retry, и тест проверял бы не то, что заявлено.

Интеграционные тесты помечены postgres: нужна реальная БД для claim/heartbeat.
"""

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import runner
from app.engine.graph_validator import validate_graph
from app.engine.node_schemas import NODE_SCHEMAS, RetryConfig
from app.engine.queue import claim_next, complete, enqueue
from app.engine.queue import heartbeat as real_heartbeat
from app.engine.runner import NodeExecutionError, _backoff_delay, run_execution
from app.shared.models import (
    Execution,
    ExecutionStep,
    User,
    Workflow,
    WorkflowVersion,
    Workspace,
)
from app.shared.schemas.workflow import Graph

PASSWORD = "password123"


# --- чистые: _backoff_delay ---------------------------------------------------


def _config(backoff: str, base_s: float) -> RetryConfig:
    """RetryConfig с параметризуемым backoff: Literal проверяется в pydantic."""
    return RetryConfig.model_validate({"max_retries": 2, "backoff": backoff, "base_s": base_s})


def test_backoff_delay_fixed_returns_base_s() -> None:
    config = _config("fixed", 2.0)
    assert [_backoff_delay(config, attempt) for attempt in (1, 2, 3)] == [2.0, 2.0, 2.0]


def test_backoff_delay_exponential_doubles_each_attempt() -> None:
    config = _config("exponential", 0.5)
    # attempt=1 → base_s, attempt=2 → 2*base_s, attempt=3 → 4*base_s
    assert [_backoff_delay(config, attempt) for attempt in (1, 2, 3)] == [0.5, 1.0, 2.0]


def test_backoff_delay_one_second_default() -> None:
    """Дефолт exponential/base_s=1.0: 1, 2, 4 секунды."""
    config = RetryConfig()
    assert [_backoff_delay(config, attempt) for attempt in (1, 2, 3)] == [1.0, 2.0, 4.0]


def test_retry_config_defaults() -> None:
    config = RetryConfig()
    assert config.max_retries == 0
    assert config.backoff == "exponential"
    assert config.base_s == 1.0


# --- чистые: валидатор графа --------------------------------------------------


def _graph_with_retry(retry: object) -> Graph:
    return Graph.model_validate(
        {
            "nodes": [
                {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
                {
                    "id": "d",
                    "type": "debug",
                    "params": {"message": "x", "retry": retry},
                    "position": {},
                },
            ],
            "edges": [{"id": "e1", "source": "t", "target": "d"}],
            "layout": {},
        }
    )


def test_validator_accepts_retry_within_limits() -> None:
    graph = _graph_with_retry({"max_retries": 5, "backoff": "fixed", "base_s": 60})
    assert validate_graph(graph, NODE_SCHEMAS) == []


def test_validator_rejects_max_retries_above_five() -> None:
    graph = _graph_with_retry({"max_retries": 10})
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("max_retries" in error for error in errors), errors


def test_validator_rejects_base_s_zero() -> None:
    graph = _graph_with_retry({"base_s": 0})
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("base_s" in error for error in errors), errors


def test_validator_rejects_base_s_above_sixty() -> None:
    graph = _graph_with_retry({"base_s": 61})
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("base_s" in error for error in errors), errors


def test_validator_rejects_invalid_backoff() -> None:
    """backoff вне {fixed, exponential} отсекается Literal в схеме."""
    graph = _graph_with_retry({"backoff": "invalid"})
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("backoff" in error for error in errors), errors


def test_validator_rejects_negative_max_retries() -> None:
    graph = _graph_with_retry({"max_retries": -1})
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("max_retries" in error for error in errors), errors


def test_validator_accepts_node_without_retry() -> None:
    """Узел без retry валиден: повторов нет (retry — необязательное поле)."""
    graph = _graph_with_retry(None)
    assert validate_graph(graph, NODE_SCHEMAS) == []


def test_retry_and_label_are_available_on_every_node_type() -> None:
    """retry/label объявлены в BaseNodeParams → попадают в JSON-Schema всех узлов."""
    for node_type, schema in NODE_SCHEMAS.items():
        properties = schema.params.model_json_schema()["properties"]
        assert "retry" in properties, node_type
        assert "label" in properties, node_type


# --- API: invalid backoff → 422 ----------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_save_version_with_invalid_backoff_returns_422(
    client: httpx.AsyncClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/auth/register",
        json={"email": f"retry-{suffix}@example.com", "password": PASSWORD, "name": "R"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    workspaces = (await client.get("/api/workspaces", headers=_auth(token))).json()
    ws_id = workspaces[0]["id"]
    created = await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": "WF"}, headers=_auth(token)
    )
    wf_id = created.json()["id"]

    graph = _graph_with_retry({"backoff": "invalid"})
    saved = await client.post(
        f"/api/workflows/{wf_id}/versions",
        json={"graph": graph.model_dump(mode="json"), "change_note": None},
        headers=_auth(token),
    )
    assert saved.status_code == 422, saved.text
    errors = saved.json()["detail"]["errors"]
    assert any("backoff" in error for error in errors), errors


# --- интеграционные: runner поверх реальной очереди ---------------------------


async def _fixture_workflow(
    session: AsyncSession, graph: dict[str, object], max_attempts: int = 1
) -> tuple[uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    user = User(email=f"{suffix}@example.com", password_hash="h")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="W", slug=f"rw-{suffix}", created_by=user.id)
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
    await enqueue(session, workflow.id, version.id, max_attempts=max_attempts)
    await session.commit()
    return workflow.id, version.id


def _debug_graph(retry: object | None) -> dict[str, object]:
    """Manual → Debug с ВАЛИДНЫМИ параметрами: отказ подменяется стабом."""
    params: dict[str, object] = {"message": "payload"}
    if retry is not None:
        params["retry"] = retry
    return {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {"id": "d", "type": "debug", "params": params, "position": {}},
        ],
        "edges": [{"id": "e1", "source": "t", "target": "d"}],
        "layout": {},
    }


def _stub_debug(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_times: int | None,
) -> dict[str, int]:
    """Подменяет runner.handle: узел debug падает первые fail_times раз.

    fail_times=None — падает всегда. Остальные узлы (триггер) идут в реальный
    обработчик, иначе запуск упал бы на первом же шаге.
    """
    from app.engine.nodes import handle as real_handle

    calls = {"count": 0}

    async def stub(
        node_type: str, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        if node_type == "debug":
            calls["count"] += 1
            if fail_times is None or calls["count"] <= fail_times:
                return {"error": f"boom {calls['count']}"}
        return await real_handle(node_type, params, context)

    monkeypatch.setattr(runner, "handle", stub)
    return calls


async def _claim(session: AsyncSession, worker_id: str = "w1") -> Execution:
    execution = await claim_next(session, worker_id)
    assert execution is not None
    await session.commit()
    return execution


async def _steps_for(session: AsyncSession, execution_id: uuid.UUID) -> list[ExecutionStep]:
    """Шаги конкретного узла 'd' в порядке попыток."""
    rows = await session.scalars(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id, ExecutionStep.node_id == "d")
        .order_by(ExecutionStep.attempt)
    )
    return list(rows)


async def _run_expecting_failure(
    session: AsyncSession, version_id: uuid.UUID
) -> Execution:
    execution = await _claim(session)
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    with pytest.raises(NodeExecutionError):
        await run_execution(session, execution, version, "w1")
    return execution


@pytest.mark.postgres
async def test_retry_disabled_fails_on_first_attempt(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """retry отсутствует → повторов нет: 1 попытка, узел failed, запуск падает."""
    calls = _stub_debug(monkeypatch, fail_times=None)
    _, version_id = await _fixture_workflow(session, _debug_graph(None))

    execution = await _run_expecting_failure(session, version_id)

    steps = await _steps_for(session, execution.id)
    assert calls["count"] == 1
    assert len(steps) == 1
    assert steps[0].attempt == 1
    assert steps[0].status == "failed"

    # терминальный статус: у executions нет 'failed' — max_attempts=1 → dead
    result = await complete(session, execution.id, success=False, error="node failed")
    await session.commit()
    assert result is not None
    assert result.status == "dead"


@pytest.mark.postgres
async def test_max_retries_zero_fails_immediately(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Явный max_retries=0 — то же поведение, что и без retry: 1 попытка."""
    calls = _stub_debug(monkeypatch, fail_times=None)
    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 0, "backoff": "fixed", "base_s": 0.01})
    )

    execution = await _run_expecting_failure(session, version_id)

    steps = await _steps_for(session, execution.id)
    assert calls["count"] == 1
    assert [step.attempt for step in steps] == [1]
    assert steps[0].status == "failed"


@pytest.mark.postgres
async def test_max_retries_two_writes_three_attempts(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_retries=2, узел падает всегда → 3 попытки (attempt=1,2,3), запуск падает."""
    calls = _stub_debug(monkeypatch, fail_times=None)
    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 2, "backoff": "fixed", "base_s": 0.01})
    )

    execution = await _run_expecting_failure(session, version_id)

    steps = await _steps_for(session, execution.id)
    assert calls["count"] == 3
    assert [step.attempt for step in steps] == [1, 2, 3]
    assert all(step.status == "failed" for step in steps)
    assert all(step.error for step in steps)


@pytest.mark.postgres
async def test_max_retries_two_succeeds_on_third_attempt(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Падает дважды, на третьей попытке успех → запуск succeeded, 3 шага."""
    calls = _stub_debug(monkeypatch, fail_times=2)
    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 2, "backoff": "fixed", "base_s": 0.01})
    )

    execution = await _claim(session)
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    await run_execution(session, execution, version, "w1")
    await complete(session, execution.id, success=True)
    await session.commit()

    steps = await _steps_for(session, execution.id)
    assert calls["count"] == 3
    assert [step.attempt for step in steps] == [1, 2, 3]
    assert [step.status for step in steps] == ["failed", "failed", "succeeded"]

    refreshed = await session.get(Execution, execution.id)
    assert refreshed is not None
    assert refreshed.status == "succeeded"


@pytest.mark.postgres
async def test_fixed_backoff_sleeps_base_s_between_attempts(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(runner, "_sleep", fake_sleep)
    _stub_debug(monkeypatch, fail_times=None)

    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 2, "backoff": "fixed", "base_s": 2.0})
    )
    await _run_expecting_failure(session, version_id)

    # 2 повтора → 2 паузы, обе равны base_s
    assert delays == [2.0, 2.0]


@pytest.mark.postgres
async def test_exponential_backoff_sleeps_doubling_delays(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(runner, "_sleep", fake_sleep)
    _stub_debug(monkeypatch, fail_times=None)

    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 2, "backoff": "exponential", "base_s": 0.5})
    )
    await _run_expecting_failure(session, version_id)

    # attempt=1 → 0.5, attempt=2 → 1.0
    assert delays == [0.5, 1.0]


@pytest.mark.postgres
async def test_no_sleep_when_retries_exhausted_check_order(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пауз ровно max_retries (не max_retries+1): после последней попытки не спим."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(runner, "_sleep", fake_sleep)
    _stub_debug(monkeypatch, fail_times=None)

    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 5, "backoff": "fixed", "base_s": 0.01})
    )
    execution = await _run_expecting_failure(session, version_id)

    steps = await _steps_for(session, execution.id)
    assert len(steps) == 6  # 1 попытка + 5 повторов
    assert len(delays) == 5


@pytest.mark.postgres
async def test_heartbeat_called_between_attempts(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Между попытками воркер продлевает лок — иначе reclaim подберёт живого."""
    calls: list[uuid.UUID] = []

    async def recording_heartbeat(
        db: AsyncSession, execution_id: uuid.UUID, worker_id: str
    ) -> None:
        calls.append(execution_id)
        await real_heartbeat(db, execution_id, worker_id)

    monkeypatch.setattr(runner, "heartbeat", recording_heartbeat)
    _stub_debug(monkeypatch, fail_times=None)

    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 2, "backoff": "fixed", "base_s": 0.01})
    )
    execution = await _run_expecting_failure(session, version_id)

    # 1 на узел t + 1 на узел d + 2 между попытками узла d = 4
    assert len(calls) == 4
    assert set(calls) == {execution.id}

    # locked_at реально продлевался: метка свежая
    refreshed = await session.get(Execution, execution.id)
    assert refreshed is not None
    assert refreshed.locked_at is not None
    assert refreshed.locked_at > datetime.now(UTC) - timedelta(seconds=30)


@pytest.mark.postgres
async def test_heartbeat_prevents_reclaim_while_retrying(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Состаренный лок + retry с heartbeat → задача не отбирается у живого воркера."""
    from app.engine.queue import reclaim_stale

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(runner, "_sleep", fake_sleep)
    _stub_debug(monkeypatch, fail_times=None)

    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 1, "backoff": "fixed", "base_s": 0.01})
    )
    execution = await _claim(session)

    # воркер «молчал» дольше heartbeat-таймаута — до первого heartbeat внутри run
    await session.execute(
        update(Execution)
        .where(Execution.id == execution.id)
        .values(locked_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    await session.commit()

    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    with pytest.raises(NodeExecutionError):
        await run_execution(session, execution, version, "w1")

    refreshed = await session.get(Execution, execution.id)
    assert refreshed is not None
    assert refreshed.locked_at is not None
    assert await reclaim_stale(session, heartbeat_timeout_seconds=60) == 0


@pytest.mark.postgres
async def test_steps_of_other_nodes_keep_attempt_one(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Номер попытки локален для узла: у триггера остаётся attempt=1."""
    _stub_debug(monkeypatch, fail_times=None)
    _, version_id = await _fixture_workflow(
        session, _debug_graph({"max_retries": 1, "backoff": "fixed", "base_s": 0.01})
    )
    execution = await _run_expecting_failure(session, version_id)

    trigger_steps = list(
        await session.scalars(
            select(ExecutionStep).where(
                ExecutionStep.execution_id == execution.id, ExecutionStep.node_id == "t"
            )
        )
    )
    assert len(trigger_steps) == 1
    assert trigger_steps[0].attempt == 1
    assert trigger_steps[0].status == "succeeded"


@pytest.mark.postgres
async def test_expression_resolved_once_before_retries(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Параметры резолвятся один раз до цикла: все попытки видят один и тот же input."""
    _stub_debug(monkeypatch, fail_times=None)
    graph = _debug_graph({"max_retries": 1, "backoff": "fixed", "base_s": 0.01})
    # в message кладём выражение — runner резолвит его до вызова узла
    nodes = graph["nodes"]
    assert isinstance(nodes, list)
    debug_node = nodes[1]
    assert isinstance(debug_node, dict)
    debug_node["params"] = {
        "message": "{{ trigger.payload.name }}",
        "retry": {"max_retries": 1, "backoff": "fixed", "base_s": 0.01},
    }

    _, version_id = await _fixture_workflow(session, graph)
    execution = await _claim(session)
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    with contextlib.suppress(NodeExecutionError):
        await run_execution(session, execution, version, "w1")

    steps = await _steps_for(session, execution.id)
    assert len(steps) == 2
    assert all(step.input is not None for step in steps)
    assert all(step.input["message"] == "" for step in steps if step.input is not None)


@pytest.mark.postgres
async def test_execution_detail_exposes_step_attempt(
    client: httpx.AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /executions/{id} отдаёт attempt каждого шага — UI показывает попытки."""
    suffix = uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/auth/register",
        json={"email": f"attempt-{suffix}@example.com", "password": PASSWORD, "name": "A"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    workspaces = (await client.get("/api/workspaces", headers=_auth(token))).json()
    ws_id = workspaces[0]["id"]
    created = await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": "WF"}, headers=_auth(token)
    )
    wf_id = created.json()["id"]

    graph = _debug_graph({"max_retries": 2, "backoff": "fixed", "base_s": 0.01})
    saved = await client.post(
        f"/api/workflows/{wf_id}/versions",
        json={"graph": graph, "change_note": None},
        headers=_auth(token),
    )
    assert saved.status_code == 201, saved.text
    published = await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(token))
    assert published.status_code == 200, published.text

    run = await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    assert run.status_code == 201, run.text
    execution_id = run.json()["id"]

    # узел debug падает 3 раза (retry.max_retries=2)
    _stub_debug(monkeypatch, fail_times=None)
    claimed = await claim_next(session, "w1")
    assert claimed is not None
    await session.commit()
    version = await session.get(WorkflowVersion, claimed.workflow_version_id)
    assert version is not None
    with contextlib.suppress(NodeExecutionError):
        await run_execution(session, claimed, version, "w1")
    await session.commit()

    detail = await client.get(f"/api/executions/{execution_id}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    steps = [step for step in detail.json()["steps"] if step["node_id"] == "d"]
    assert [step["attempt"] for step in steps] == [1, 2, 3]
    assert all(step["status"] == "failed" for step in steps)