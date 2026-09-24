"""Интеграционные тесты runner: топологический обход, ветвление If, шаги.

Только Postgres (@pytest.mark.postgres): нужна реальная БД для очереди,
reclaim и SKIP LOCKED.
"""

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.queue import claim_next, complete, enqueue, reclaim_stale
from app.engine.runner import NodeExecutionError, run_execution
from app.shared.models import (
    Execution,
    ExecutionStep,
    User,
    Workflow,
    WorkflowVersion,
    Workspace,
)
from app.shared.schemas.workflow import Graph

pytestmark = pytest.mark.postgres


async def _fixture_workflow(
    session: AsyncSession, graph: dict[str, object]
) -> tuple[uuid.UUID, uuid.UUID]:
    """Создаёт user → workspace → workflow → version. Возвращает (workflow_id, version_id)."""
    suffix = uuid.uuid4().hex[:8]
    user = User(email=f"{suffix}@example.com", password_hash="h")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="W", slug=f"w-{suffix}", created_by=user.id)
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


def _linear_graph() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {
                "id": "s",
                "type": "transform_set",
                "params": {"fields": [{"name": "greeting", "value": "hi"}]},
                "position": {},
            },
            {
                "id": "d",
                "type": "debug",
                "params": {"level": "info", "message": "done"},
                "position": {},
            },
        ],
        "edges": [
            {"id": "e1", "source": "t", "target": "s"},
            {"id": "e2", "source": "s", "target": "d"},
        ],
        "layout": {},
    }


def _if_graph(branch_value: str) -> dict[str, object]:
    """Manual → If(1=1) → true:Debug  /  false:Debug."""
    return {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {
                "id": "i",
                "type": "logic_if",
                "params": {"left": branch_value, "op": "=", "right": branch_value},
                "position": {},
            },
            {"id": "dt", "type": "debug", "params": {"message": "yes"}, "position": {}},
            {"id": "df", "type": "debug", "params": {"message": "no"}, "position": {}},
        ],
        "edges": [
            {"id": "e1", "source": "t", "target": "i"},
            {"id": "e2", "source": "i", "target": "dt", "sourceHandle": "true"},
            {"id": "e3", "source": "i", "target": "df", "sourceHandle": "false"},
        ],
        "layout": {},
    }


async def _run(session: AsyncSession, graph: dict[str, object], worker_id: str = "w1") -> Execution:
    workflow_id, version_id = await _fixture_workflow(session, graph)
    await enqueue(session, workflow_id, version_id)
    await session.commit()
    execution = await claim_next(session, worker_id)
    assert execution is not None
    await session.commit()
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    with contextlib.suppress(NodeExecutionError):
        await run_execution(session, execution, version, worker_id)
    return execution


async def _steps(session: AsyncSession, execution_id: uuid.UUID) -> list[ExecutionStep]:
    rows = await session.scalars(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.created_at, ExecutionStep.node_id)
    )
    return list(rows)


async def test_linear_graph_all_steps_recorded(session: AsyncSession) -> None:
    execution = await _run(session, _linear_graph())
    steps = await _steps(session, execution.id)

    assert len(steps) == 3
    assert all(step.status == "succeeded" for step in steps)
    by_node = {step.node_id: step for step in steps}
    assert by_node["s"].output == {"greeting": "hi"}
    assert by_node["d"].output == {"level": "info", "message": "done"}
    assert by_node["t"].output == {"payload": {}}


async def test_set_resolves_expression(session: AsyncSession) -> None:
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {
                "id": "s",
                "type": "transform_set",
                "params": {"fields": [{"name": "who", "value": "{{ trigger.payload.name }}"}]},
                "position": {},
            },
        ],
        "edges": [{"id": "e1", "source": "t", "target": "s"}],
        "layout": {},
    }
    workflow_id, version_id = await _fixture_workflow(session, graph)
    await enqueue(session, workflow_id, version_id, trigger_payload={"name": "Alice"})
    await session.commit()
    execution = await claim_next(session, "w1")
    assert execution is not None
    await session.commit()
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None

    await run_execution(session, execution, version, "w1")

    steps = await _steps(session, execution.id)
    set_step = next(step for step in steps if step.node_id == "s")
    assert set_step.output == {"who": "Alice"}


async def test_debug_without_message_fails_step(session: AsyncSession) -> None:
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {"id": "d", "type": "debug", "params": {}, "position": {}},
        ],
        "edges": [{"id": "e1", "source": "t", "target": "d"}],
        "layout": {},
    }
    execution = await _run(session, graph)
    steps = await _steps(session, execution.id)

    failed = next(step for step in steps if step.node_id == "d")
    assert failed.status == "failed"
    assert failed.error is not None


async def test_if_true_branch_skips_false(session: AsyncSession) -> None:
    execution = await _run(session, _if_graph("same"))
    steps = await _steps(session, execution.id)
    by_node = {step.node_id: step for step in steps}

    assert by_node["i"].status == "succeeded"
    assert by_node["i"].output is not None
    assert by_node["i"].output["branch"] == "true"
    assert by_node["dt"].status == "succeeded"
    assert by_node["df"].status == "skipped"
    # skipped-шаг записан с пустыми input/output
    assert by_node["df"].input is None
    assert by_node["df"].output is None


async def test_if_false_branch_skips_true(session: AsyncSession) -> None:
    graph = _if_graph("x")
    # делаем условие ложным: left != right
    graph["nodes"][1]["params"] = {"left": "a", "op": "=", "right": "b"}  # type: ignore[index]
    execution = await _run(session, graph)
    steps = await _steps(session, execution.id)
    by_node = {step.node_id: step for step in steps}

    assert by_node["i"].output is not None
    assert by_node["i"].output["branch"] == "false"
    assert by_node["df"].status == "succeeded"
    assert by_node["dt"].status == "skipped"


async def test_if_with_expressions_in_condition(session: AsyncSession) -> None:
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {
                "id": "i",
                "type": "logic_if",
                "params": {
                    "left": "{{ trigger.payload.role }}",
                    "op": "=",
                    "right": "admin",
                },
                "position": {},
            },
            {"id": "dt", "type": "debug", "params": {"message": "admin"}, "position": {}},
            {"id": "df", "type": "debug", "params": {"message": "user"}, "position": {}},
        ],
        "edges": [
            {"id": "e1", "source": "t", "target": "i"},
            {"id": "e2", "source": "i", "target": "dt", "sourceHandle": "true"},
            {"id": "e3", "source": "i", "target": "df", "sourceHandle": "false"},
        ],
        "layout": {},
    }
    workflow_id, version_id = await _fixture_workflow(session, graph)
    await enqueue(session, workflow_id, version_id, trigger_payload={"role": "admin"})
    await session.commit()
    execution = await claim_next(session, "w1")
    assert execution is not None
    await session.commit()
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None

    await run_execution(session, execution, version, "w1")

    steps = await _steps(session, execution.id)
    by_node = {step.node_id: step for step in steps}
    assert by_node["dt"].status == "succeeded"
    assert by_node["df"].status == "skipped"


async def test_two_executions_have_isolated_steps(session: AsyncSession) -> None:
    workflow_id, version_id = await _fixture_workflow(session, _linear_graph())
    first = await enqueue(session, workflow_id, version_id)
    second = await enqueue(session, workflow_id, version_id)
    await session.commit()
    version = await session.get(WorkflowVersion, version_id)
    assert version is not None

    for _ in (first, second):
        claimed = await claim_next(session, "w1")
        assert claimed is not None
        await session.commit()
        await run_execution(session, claimed, version, "w1")
        await session.commit()

    first_steps = await _steps(session, first.id)
    second_steps = await _steps(session, second.id)
    assert len(first_steps) == 3
    assert len(second_steps) == 3
    assert {s.id for s in first_steps}.isdisjoint({s.id for s in second_steps})


async def test_worker_killed_reclaim_and_rerun(session: AsyncSession) -> None:
    """Воркер упал посреди выполнения: reclaim вернул, второй воркер повторил."""
    workflow_id, version_id = await _fixture_workflow(session, _linear_graph())
    await enqueue(session, workflow_id, version_id, max_attempts=3)
    await session.commit()

    claimed = await claim_next(session, "worker-a")
    assert claimed is not None
    assert claimed.attempts == 1
    await session.commit()

    # A «умирает»: стареем locked_at, чтобы reclaim сработал
    await session.execute(
        update(Execution)
        .where(Execution.id == claimed.id)
        .values(locked_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    await session.commit()
    assert await reclaim_stale(session, heartbeat_timeout_seconds=60) == 1
    await session.commit()

    # B подхватывает ту же задачу и доводит до конца
    claimed_b = await claim_next(session, "worker-b")
    assert claimed_b is not None
    assert claimed_b.id == claimed.id
    assert claimed_b.attempts == 2
    await session.commit()

    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    await run_execution(session, claimed_b, version, "worker-b")
    await complete(session, claimed_b.id, success=True)
    await session.commit()

    refreshed = await session.get(Execution, claimed.id)
    assert refreshed is not None
    assert refreshed.status == "succeeded"


async def test_heartbeat_extends_lock_during_long_node(session: AsyncSession) -> None:
    """run_execution продлевает locked_at на каждом узле — reclaim не тронет живого."""
    workflow_id, version_id = await _fixture_workflow(session, _linear_graph())
    await enqueue(session, workflow_id, version_id)
    await session.commit()
    claimed = await claim_next(session, "w1")
    assert claimed is not None
    await session.commit()

    # искусственно состарим locked_at: без heartbeat reclaim вернул бы задачу
    await session.execute(
        update(Execution)
        .where(Execution.id == claimed.id)
        .values(locked_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    await session.commit()

    version = await session.get(WorkflowVersion, version_id)
    assert version is not None
    await run_execution(session, claimed, version, "w1")
    await session.commit()

    refreshed = await session.get(Execution, claimed.id)
    assert refreshed is not None
    assert refreshed.locked_at is not None
    assert refreshed.locked_at > datetime.now(UTC) - timedelta(seconds=30)
    # значит reclaim не должен счесть её зависшей
    assert await reclaim_stale(session, heartbeat_timeout_seconds=60) == 0


async def test_success_sets_status_and_finished_at(session: AsyncSession) -> None:
    execution = await _run(session, _linear_graph())
    await complete(session, execution.id, success=True)
    await session.commit()

    refreshed = await session.get(Execution, execution.id)
    assert refreshed is not None
    assert refreshed.status == "succeeded"
    assert refreshed.finished_at is not None


async def test_failure_records_error_and_reschedules(session: AsyncSession) -> None:
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {
                "id": "h",
                "type": "action_http",
                "params": {"method": "GET", "url": "https://example.com"},
                "position": {},
            },
        ],
        "edges": [{"id": "e1", "source": "t", "target": "h"}],
        "layout": {},
    }
    execution = await _run(session, graph)
    assert execution.attempts == 1

    result = await complete(session, execution.id, success=False, error="node failed")
    await session.commit()

    assert result is not None
    assert result.status == "queued"  # attempts=1 < max=3 → retry
    assert result.error == "node failed"
    assert result.status != "succeeded"


async def test_exhausted_failure_goes_dead(session: AsyncSession) -> None:
    workflow_id, version_id = await _fixture_workflow(session, _linear_graph())
    await enqueue(session, workflow_id, version_id, max_attempts=1)
    await session.commit()
    claimed = await claim_next(session, "w1")
    assert claimed is not None
    assert claimed.attempts == 1
    assert claimed.max_attempts == 1
    await session.commit()

    result = await complete(session, claimed.id, success=False, error="final failure")
    await session.commit()

    assert result is not None
    assert result.status == "dead"


async def test_topological_order_puts_trigger_first(session: AsyncSession) -> None:
    from app.engine.runner import topological_order

    graph = Graph.model_validate(_linear_graph())
    order = topological_order(graph)
    assert order[0].type == "trigger_manual"
    assert [node.id for node in order] == ["t", "s", "d"]