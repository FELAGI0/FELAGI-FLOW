"""Тесты триггеров stage 5.A: cron-расписания, вебхуки, валидация.

Только Postgres: advisory-lock, FOR UPDATE SKIP LOCKED и sync при публикации
требуют настоящей БД.
"""

import os
import uuid

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.engine.graph_validator import validate_graph
from app.engine.node_schemas import NODE_SCHEMAS
from app.engine.trigger_sync import sync_triggers
from app.scheduler.__main__ import SCHEDULER_LOCK_ID, run_tick
from app.shared.models import (
    Execution,
    Schedule,
    User,
    WebhookRoute,
    Workflow,
    WorkflowVersion,
    Workspace,
)
from app.shared.schemas.workflow import Graph

pytestmark = pytest.mark.postgres

PASSWORD = "password123"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD, "name": "T"}
    )
    assert resp.status_code == 201, resp.text
    token: str = resp.json()["access_token"]
    return token


async def _ws_id(client: httpx.AsyncClient, token: str) -> str:
    resp = await client.get("/api/workspaces", headers=_auth(token))
    return str(resp.json()[0]["id"])


def _cron_graph(
    cron_expr: str = "0 9 * * *", timezone: str = "UTC", node_id: str = "c"
) -> dict[str, object]:
    """Manual-совместимый граф с cron-триггером: trigger_cron → debug."""
    return {
        "nodes": [
            {
                "id": node_id,
                "type": "trigger_cron",
                "params": {"cron_expr": cron_expr, "timezone": timezone},
                "position": {},
            },
            {"id": "d", "type": "debug", "params": {"message": "tick"}, "position": {}},
        ],
        "edges": [{"id": "e1", "source": node_id, "target": "d"}],
        "layout": {},
    }


def _webhook_graph(
    methods: list[str] | None = None, node_id: str = "w"
) -> dict[str, object]:
    params: dict[str, object] = {} if methods is None else {"methods": methods}
    return {
        "nodes": [
            {"id": node_id, "type": "trigger_webhook", "params": params, "position": {}},
            {"id": "d", "type": "debug", "params": {"message": "hook"}, "position": {}},
        ],
        "edges": [{"id": "e1", "source": node_id, "target": "d"}],
        "layout": {},
    }


async def _create_workflow(client: httpx.AsyncClient, token: str, name: str = "WF") -> str:
    ws_id = await _ws_id(client, token)
    created = await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": name}, headers=_auth(token)
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _save_and_publish(
    client: httpx.AsyncClient, token: str, wf_id: str, graph: dict[str, object]
) -> httpx.Response:
    saved = await client.post(
        f"/api/workflows/{wf_id}/versions",
        json={"graph": graph, "change_note": None},
        headers=_auth(token),
    )
    assert saved.status_code == 201, saved.text
    return await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(token))


# --- cron: sync при публикации ------------------------------------------------


async def test_publish_creates_schedule(client: httpx.AsyncClient) -> None:
    token = await _register(client, "cron1@example.com")
    wf_id = await _create_workflow(client, token)

    published = await _save_and_publish(client, token, wf_id, _cron_graph())
    assert published.status_code == 200, published.text

    ws_id = await _ws_id(client, token)
    resp = await client.get(f"/api/workspaces/{ws_id}/schedules", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    schedules = resp.json()
    assert len(schedules) == 1
    assert schedules[0]["spec"] == "0 9 * * *"
    assert schedules[0]["workflow_id"] == wf_id
    assert schedules[0]["enabled"] is True
    assert schedules[0]["last_run_at"] is None
    assert schedules[0]["next_run_at"] is not None


async def test_republish_updates_spec_and_keeps_id(client: httpx.AsyncClient) -> None:
    """Повторная публикация меняет spec, но не пересоздаёт строку расписания."""
    token = await _register(client, "cron2@example.com")
    wf_id = await _create_workflow(client, token)
    await _save_and_publish(client, token, wf_id, _cron_graph("0 9 * * *"))

    ws_id = await _ws_id(client, token)
    first = (
        await client.get(f"/api/workspaces/{ws_id}/schedules", headers=_auth(token))
    ).json()
    assert len(first) == 1

    await _save_and_publish(client, token, wf_id, _cron_graph("30 7 * * *"))
    second = (
        await client.get(f"/api/workspaces/{ws_id}/schedules", headers=_auth(token))
    ).json()

    assert len(second) == 1
    assert second[0]["id"] == first[0]["id"]
    assert second[0]["spec"] == "30 7 * * *"


async def test_removing_cron_node_deletes_schedule(client: httpx.AsyncClient) -> None:
    token = await _register(client, "cron3@example.com")
    wf_id = await _create_workflow(client, token)
    await _save_and_publish(client, token, wf_id, _cron_graph())

    ws_id = await _ws_id(client, token)
    before = (
        await client.get(f"/api/workspaces/{ws_id}/schedules", headers=_auth(token))
    ).json()
    assert len(before) == 1

    # публикуем версию, где cron-узел заменён на manual
    manual_graph = {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {"id": "d", "type": "debug", "params": {"message": "x"}, "position": {}},
        ],
        "edges": [{"id": "e1", "source": "t", "target": "d"}],
        "layout": {},
    }
    published = await _save_and_publish(client, token, wf_id, manual_graph)
    assert published.status_code == 200, published.text

    remaining = (
        await client.get(f"/api/workspaces/{ws_id}/schedules", headers=_auth(token))
    ).json()
    assert remaining == []


# --- cron: тик планировщика ---------------------------------------------------


async def _cron_workflow(
    session: AsyncSession, graph: dict[str, object]
) -> tuple[uuid.UUID, uuid.UUID]:
    """Создаёт опубликованный workflow с синхронизированными триггерами."""
    suffix = uuid.uuid4().hex[:8]
    user = User(email=f"{suffix}@example.com", password_hash="h")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="W", slug=f"cr-{suffix}", created_by=user.id)
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
    workflow.published_version_id = version.id
    workflow.status = "active"
    await sync_triggers(session, workspace.id, workflow.id, Graph.model_validate(graph))
    await session.commit()
    return workflow.id, version.id


async def test_tick_enqueues_due_schedule(session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    workflow_id, version_id = await _cron_workflow(session, _cron_graph("*/5 * * * *"))
    schedule = await session.scalar(select(Schedule).where(Schedule.workflow_id == workflow_id))
    assert schedule is not None

    # делаем расписание созревшим
    past = datetime.now(UTC) - timedelta(minutes=1)
    await session.execute(
        update(Schedule).where(Schedule.id == schedule.id).values(next_run_at=past)
    )
    await session.commit()

    created = await run_tick(session)
    await session.commit()

    assert created == 1
    execution = await session.scalar(
        select(Execution).where(Execution.workflow_id == workflow_id)
    )
    assert execution is not None
    assert execution.trigger_type == "cron"
    assert execution.status == "queued"
    assert execution.workflow_version_id == version_id

    refreshed = await session.get(Schedule, schedule.id)
    assert refreshed is not None
    assert refreshed.last_run_at is not None
    assert refreshed.next_run_at > past


async def test_tick_skips_not_due_schedule(session: AsyncSession) -> None:
    workflow_id, _ = await _cron_workflow(session, _cron_graph("0 9 * * *"))

    created = await run_tick(session)
    await session.commit()

    assert created == 0
    executions = list(
        await session.scalars(select(Execution).where(Execution.workflow_id == workflow_id))
    )
    assert executions == []


async def test_tick_skips_disabled_schedule(session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    workflow_id, _ = await _cron_workflow(session, _cron_graph("*/5 * * * *"))
    schedule = await session.scalar(select(Schedule).where(Schedule.workflow_id == workflow_id))
    assert schedule is not None
    await session.execute(
        update(Schedule)
        .where(Schedule.id == schedule.id)
        .values(next_run_at=datetime.now(UTC) - timedelta(minutes=1), enabled=False)
    )
    await session.commit()

    created = await run_tick(session)
    await session.commit()

    assert created == 0
    executions = list(
        await session.scalars(select(Execution).where(Execution.workflow_id == workflow_id))
    )
    assert executions == []


async def test_tick_skips_unpublished_workflow(session: AsyncSession) -> None:
    """workflow снят с публикации: запуска нет, расписание сдвигается."""
    from datetime import UTC, datetime, timedelta

    workflow_id, _ = await _cron_workflow(session, _cron_graph("*/5 * * * *"))
    schedule = await session.scalar(select(Schedule).where(Schedule.workflow_id == workflow_id))
    assert schedule is not None
    past = datetime.now(UTC) - timedelta(minutes=1)
    await session.execute(
        update(Schedule).where(Schedule.id == schedule.id).values(next_run_at=past)
    )
    await session.execute(
        update(Workflow).where(Workflow.id == workflow_id).values(published_version_id=None)
    )
    await session.commit()

    created = await run_tick(session)
    await session.commit()

    assert created == 0
    executions = list(
        await session.scalars(select(Execution).where(Execution.workflow_id == workflow_id))
    )
    assert executions == []

    refreshed = await session.get(Schedule, schedule.id)
    assert refreshed is not None
    # расписание не «застревает» на прошлом моменте
    assert refreshed.next_run_at > past


async def test_advisory_lock_excludes_second_scheduler(session: AsyncSession) -> None:
    """Второй планировщик не берёт лок, пока первый его держит."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    # отдельное СОЕДИНЕНИЕ: pg_try_advisory_lock реентерабелен внутри одной
    # сессии и вернул бы True на том же соединении, поэтому нужен второй коннект.
    # Движок берём у тестовой сессии (TEST_DATABASE_URL), а не из settings:
    # settings указывает на dev-БД с другими учётными данными
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])

    first = await session.scalar(select(func.pg_try_advisory_lock(SCHEDULER_LOCK_ID)))
    assert first is True

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as other:
            blocked = await other.scalar(select(func.pg_try_advisory_lock(SCHEDULER_LOCK_ID)))
            assert blocked is False

        released = await session.scalar(select(func.pg_advisory_unlock(SCHEDULER_LOCK_ID)))
        assert released is True

        async with factory() as other:
            after_release = await other.scalar(
                select(func.pg_try_advisory_lock(SCHEDULER_LOCK_ID))
            )
            assert after_release is True
            await other.execute(select(func.pg_advisory_unlock(SCHEDULER_LOCK_ID)))
    finally:
        await engine.dispose()


# --- webhook: sync и приём ----------------------------------------------------


async def test_publish_creates_webhook_route(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "hook1@example.com")
    wf_id = await _create_workflow(client, token)
    published = await _save_and_publish(client, token, wf_id, _webhook_graph())
    assert published.status_code == 200, published.text

    route = await session.scalar(
        select(WebhookRoute).where(WebhookRoute.workflow_id == uuid.UUID(wf_id))
    )
    assert route is not None
    assert route.node_id == "w"
    # token — секрет, а не id: значение достаточно длинное и непустое
    assert len(route.token) >= 40


async def _published_webhook_workflow(
    client: httpx.AsyncClient, session: AsyncSession, email: str, methods: list[str] | None = None
) -> str:
    """Публикует webhook-граф и возвращает token маршрута."""
    token = await _register(client, email)
    wf_id = await _create_workflow(client, token)
    published = await _save_and_publish(client, token, wf_id, _webhook_graph(methods))
    assert published.status_code == 200, published.text

    route = await session.scalar(
        select(WebhookRoute).where(WebhookRoute.workflow_id == uuid.UUID(wf_id))
    )
    assert route is not None
    return route.token


async def test_webhook_post_creates_execution(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    hook_token = await _published_webhook_workflow(client, session, "hook2@example.com")

    resp = await client.post(f"/hooks/{hook_token}", json={"hello": "world"})
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["execution_id"]

    execution = await session.get(Execution, uuid.UUID(execution_id))
    assert execution is not None
    assert execution.trigger_type == "webhook"
    assert execution.status == "queued"


async def test_webhook_get_rejected_when_only_post_allowed(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    hook_token = await _published_webhook_workflow(
        client, session, "hook3@example.com", methods=["POST"]
    )

    resp = await client.get(f"/hooks/{hook_token}")
    assert resp.status_code == 405
    assert "POST" in resp.headers.get("allow", "")


async def test_webhook_get_allowed_when_configured(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    hook_token = await _published_webhook_workflow(
        client, session, "hook4@example.com", methods=["GET", "POST"]
    )

    resp = await client.get(f"/hooks/{hook_token}", params={"a": "1"})
    assert resp.status_code == 202, resp.text


async def test_webhook_unknown_token_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.post("/hooks/definitely-not-a-real-token", json={})
    assert resp.status_code == 404


async def test_webhook_unpublished_workflow_conflict(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    hook_token = await _published_webhook_workflow(client, session, "hook5@example.com")

    route = await session.scalar(select(WebhookRoute).where(WebhookRoute.token == hook_token))
    assert route is not None
    await session.execute(
        update(Workflow).where(Workflow.id == route.workflow_id).values(published_version_id=None)
    )
    await session.commit()

    resp = await client.post(f"/hooks/{hook_token}", json={})
    assert resp.status_code == 409


async def test_webhook_payload_contains_request_data(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    hook_token = await _published_webhook_workflow(client, session, "hook6@example.com")

    resp = await client.post(
        f"/hooks/{hook_token}?q=1",
        json={"nested": {"a": 1}},
        headers={"X-Custom": "abc"},
    )
    assert resp.status_code == 202, resp.text
    execution = await session.get(Execution, uuid.UUID(resp.json()["execution_id"]))
    assert execution is not None
    payload = execution.trigger_payload
    assert payload is not None
    assert payload["body"] == {"nested": {"a": 1}}
    assert payload["query"] == {"q": "1"}
    assert payload["method"] == "POST"
    assert payload["headers"].get("x-custom") == "abc"


async def test_webhook_body_as_text_when_not_json(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    hook_token = await _published_webhook_workflow(client, session, "hook7@example.com")

    resp = await client.post(
        f"/hooks/{hook_token}",
        content=b"plain text body",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 202, resp.text
    execution = await session.get(Execution, uuid.UUID(resp.json()["execution_id"]))
    assert execution is not None
    assert execution.trigger_payload is not None
    assert execution.trigger_payload["body"] == "plain text body"


async def test_republish_keeps_webhook_token(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """token выдан наружу: повторная публикация не должна его менять."""
    token = await _register(client, "hook8@example.com")
    wf_id = await _create_workflow(client, token)
    await _save_and_publish(client, token, wf_id, _webhook_graph())

    route = await session.scalar(
        select(WebhookRoute).where(WebhookRoute.workflow_id == uuid.UUID(wf_id))
    )
    assert route is not None
    first_token = route.token

    # публикуем другую версию с тем же node_id, но иными methods
    await _save_and_publish(client, token, wf_id, _webhook_graph(methods=["GET", "POST"]))

    routes = list(
        await session.scalars(
            select(WebhookRoute).where(WebhookRoute.workflow_id == uuid.UUID(wf_id))
        )
    )
    assert len(routes) == 1
    assert routes[0].token == first_token


async def test_removing_webhook_node_deletes_route(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "hook9@example.com")
    wf_id = await _create_workflow(client, token)
    await _save_and_publish(client, token, wf_id, _webhook_graph())

    manual_graph = {
        "nodes": [
            {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
            {"id": "d", "type": "debug", "params": {"message": "x"}, "position": {}},
        ],
        "edges": [{"id": "e1", "source": "t", "target": "d"}],
        "layout": {},
    }
    await _save_and_publish(client, token, wf_id, manual_graph)

    routes = list(
        await session.scalars(
            select(WebhookRoute).where(WebhookRoute.workflow_id == uuid.UUID(wf_id))
        )
    )
    assert routes == []


# --- валидатор ----------------------------------------------------------------


def _graph_with_params(node_type: str, params: dict[str, object]) -> Graph:
    return Graph.model_validate(
        {
            "nodes": [
                {"id": "n", "type": node_type, "params": params, "position": {}},
                {"id": "d", "type": "debug", "params": {"message": "x"}, "position": {}},
            ],
            "edges": [{"id": "e1", "source": "n", "target": "d"}],
            "layout": {},
        }
    )


def test_validator_rejects_invalid_cron_expr() -> None:
    graph = _graph_with_params(
        "trigger_cron", {"cron_expr": "not a cron", "timezone": "UTC"}
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("cron_expr" in error for error in errors), errors


def test_validator_rejects_invalid_timezone() -> None:
    graph = _graph_with_params(
        "trigger_cron", {"cron_expr": "0 9 * * *", "timezone": "Not/AZone"}
    )
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("timezone" in error for error in errors), errors


def test_validator_rejects_empty_methods() -> None:
    graph = _graph_with_params("trigger_webhook", {"methods": []})
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("methods" in error for error in errors), errors


def test_validator_rejects_unsupported_method() -> None:
    graph = _graph_with_params("trigger_webhook", {"methods": ["DELETE"]})
    errors = validate_graph(graph, NODE_SCHEMAS)
    assert any("DELETE" in error for error in errors), errors


def test_validator_accepts_valid_cron_and_webhook() -> None:
    assert validate_graph(
        _graph_with_params("trigger_cron", {"cron_expr": "0 9 * * *", "timezone": "UTC"}),
        NODE_SCHEMAS,
    ) == []
    assert validate_graph(
        _graph_with_params("trigger_webhook", {"methods": ["GET", "POST"]}), NODE_SCHEMAS
    ) == []
    # timezone необязателен: дефолт UTC
    assert validate_graph(
        _graph_with_params("trigger_cron", {"cron_expr": "*/5 * * * *"}), NODE_SCHEMAS
    ) == []


def test_validator_accepts_real_timezone() -> None:
    graph = _graph_with_params(
        "trigger_cron", {"cron_expr": "0 9 * * *", "timezone": "Europe/Berlin"}
    )
    assert validate_graph(graph, NODE_SCHEMAS) == []


# --- расчёт следующего запуска ------------------------------------------------


def test_next_run_timezone_aware() -> None:
    """9:00 в Europe/Berlin летом = 07:00 UTC."""
    from datetime import UTC, datetime

    from app.engine.cron import next_run_at

    base = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    nxt = next_run_at("0 9 * * *", "Europe/Berlin", base)
    assert nxt.tzinfo is not None
    assert nxt.hour == 7
    assert nxt.minute == 0


def test_next_run_utc_default() -> None:
    from datetime import UTC, datetime

    from app.engine.cron import next_run_at

    base = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    nxt = next_run_at("0 9 * * *", "UTC", base)
    assert nxt.hour == 9


def test_cron_helpers_reject_garbage() -> None:
    from app.engine.cron import is_valid_cron, is_valid_timezone

    assert is_valid_cron("0 9 * * *") is True
    assert is_valid_cron("nonsense") is False
    assert is_valid_cron("") is False
    assert is_valid_timezone("UTC") is True
    assert is_valid_timezone("Not/AZone") is False
    assert is_valid_timezone("") is False