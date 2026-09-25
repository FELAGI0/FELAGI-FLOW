"""Тесты REST /executions: ручной запуск, история, детали, отмена, HTTP-узел.

Пометка postgres: нужна реальная БД (очередь, SKIP LOCKED, курсорная пагинация).
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.executions import _decode_cursor, _encode_cursor
from app.engine.nodes.http import handle_http
from app.engine.queue import claim_next
from app.engine.runner import run_execution
from app.shared.models import Execution, User, Workflow, WorkflowVersion, Workspace

pytestmark = pytest.mark.postgres

PASSWORD = "password123"

VALID_GRAPH = {
    "nodes": [
        {"id": "t", "type": "trigger_manual", "params": {}, "position": {}},
        {
            "id": "d",
            "type": "debug",
            "params": {"level": "info", "message": "ok"},
            "position": {},
        },
    ],
    "edges": [{"id": "e1", "source": "t", "target": "d"}],
    "layout": {},
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, email: str, name: str = "U") -> str:
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD, "name": name}
    )
    assert resp.status_code == 201, resp.text
    token: str = resp.json()["access_token"]
    return token


async def _ws_id(client: httpx.AsyncClient, token: str) -> str:
    resp = await client.get("/api/workspaces", headers=_auth(token))
    return str(resp.json()[0]["id"])


async def _published_workflow(client: httpx.AsyncClient, token: str, ws_id: str) -> str:
    """Создаёт workflow, сохраняет версию и публикует. Возвращает workflow_id."""
    created = await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": "E2E"}, headers=_auth(token)
    )
    wf_id = created.json()["id"]
    await client.post(
        f"/api/workflows/{wf_id}/versions",
        json={"graph": VALID_GRAPH, "change_note": None},
        headers=_auth(token),
    )
    published = await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(token))
    assert published.status_code == 200, published.text
    return str(wf_id)


# --- ручной запуск ------------------------------------------------------------


async def test_run_unpublished_workflow_conflict(client: httpx.AsyncClient) -> None:
    token = await _register(client, "run403@example.com")
    ws_id = await _ws_id(client, token)
    created = await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": "Draft"}, headers=_auth(token)
    )
    wf_id = created.json()["id"]

    resp = await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    assert resp.status_code == 409


async def test_run_published_creates_queued_execution(client: httpx.AsyncClient) -> None:
    token = await _register(client, "run201@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)

    resp = await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["trigger_type"] == "manual"
    assert body["attempts"] == 0
    assert body["workflow_id"] == wf_id


async def test_run_with_payload_persists_trigger_payload(client: httpx.AsyncClient) -> None:
    token = await _register(client, "runpay@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)

    resp = await client.post(
        f"/api/workflows/{wf_id}/run",
        json={"payload": {"name": "Alice", "n": 5}},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["trigger_payload"] == {"name": "Alice", "n": 5}


async def test_run_foreign_workflow_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = await _register(client, "runfa@example.com")
    a_ws = await _ws_id(client, a)
    wf_id = await _published_workflow(client, a, a_ws)

    b = await _register(client, "runfb@example.com")
    resp = await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(b))
    assert resp.status_code == 403


# --- детали -------------------------------------------------------------------


async def test_get_execution_details(client: httpx.AsyncClient) -> None:
    token = await _register(client, "getdet@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)
    execution_id = (
        await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    ).json()["id"]

    resp = await client.get(f"/api/executions/{execution_id}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == execution_id
    assert body["steps"] == []  # ещё не выполнялся


async def test_get_execution_not_found(client: httpx.AsyncClient) -> None:
    token = await _register(client, "get404@example.com")
    resp = await client.get(f"/api/executions/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


async def test_get_foreign_execution_forbidden(client: httpx.AsyncClient) -> None:
    a = await _register(client, "getfa@example.com")
    a_ws = await _ws_id(client, a)
    wf_id = await _published_workflow(client, a, a_ws)
    execution_id = (
        await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(a))
    ).json()["id"]

    b = await _register(client, "getfb@example.com")
    resp = await client.get(f"/api/executions/{execution_id}", headers=_auth(b))
    assert resp.status_code == 403


async def test_execution_steps_after_run(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "steps@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)
    execution_id = (
        await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    ).json()["id"]

    # прогоняем воркером вручную (в тестах нет фонового цикла)
    from app.engine.queue import complete

    claimed = await claim_next(session, "test-worker")
    assert claimed is not None
    assert str(claimed.id) == execution_id
    await session.commit()
    version = await session.get(WorkflowVersion, claimed.workflow_version_id)
    assert version is not None
    await run_execution(session, claimed, version, "test-worker")
    await complete(session, claimed.id, success=True)
    await session.commit()

    resp = await client.get(f"/api/executions/{execution_id}", headers=_auth(token))
    body = resp.json()
    assert body["status"] == "succeeded"
    assert len(body["steps"]) == 2
    assert {s["node_id"] for s in body["steps"]} == {"t", "d"}
    assert all(s["status"] == "succeeded" for s in body["steps"])


# --- история и пагинация -------------------------------------------------------


async def test_list_only_own_workspace(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = await _register(client, "lista@example.com")
    a_ws = await _ws_id(client, a)
    a_wf = await _published_workflow(client, a, a_ws)
    await client.post(f"/api/workflows/{a_wf}/run", json={}, headers=_auth(a))

    b = await _register(client, "listb@example.com")
    b_ws = await _ws_id(client, b)
    b_wf = await _published_workflow(client, b, b_ws)
    await client.post(f"/api/workflows/{b_wf}/run", json={}, headers=_auth(b))

    a_list = await client.get(f"/api/workspaces/{a_ws}/executions", headers=_auth(a))
    assert a_list.status_code == 200
    assert all(item["workflow_id"] == a_wf for item in a_list.json()["items"])

    # чужой workspace — 403
    forbidden = await client.get(f"/api/workspaces/{a_ws}/executions", headers=_auth(b))
    assert forbidden.status_code == 403


async def test_list_filter_by_status(client: httpx.AsyncClient, session: AsyncSession) -> None:
    token = await _register(client, "filtstatus@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)

    first = (
        await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    ).json()["id"]
    await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))

    # первый прогоняем до succeeded
    from app.engine.queue import complete

    claimed = await claim_next(session, "w")
    assert claimed is not None
    assert str(claimed.id) == first
    await session.commit()
    version = await session.get(WorkflowVersion, claimed.workflow_version_id)
    assert version is not None
    await run_execution(session, claimed, version, "w")
    await complete(session, claimed.id, success=True)
    await session.commit()

    resp = await client.get(
        f"/api/workspaces/{ws_id}/executions?status=succeeded", headers=_auth(token)
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == first


async def test_list_filter_by_workflow(client: httpx.AsyncClient) -> None:
    token = await _register(client, "filtwf@example.com")
    ws_id = await _ws_id(client, token)
    wf1 = await _published_workflow(client, token, ws_id)

    created2 = await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": "W2"}, headers=_auth(token)
    )
    wf2 = created2.json()["id"]
    await client.post(
        f"/api/workflows/{wf2}/versions",
        json={"graph": VALID_GRAPH, "change_note": None},
        headers=_auth(token),
    )
    await client.post(f"/api/workflows/{wf2}/publish", headers=_auth(token))

    await client.post(f"/api/workflows/{wf1}/run", json={}, headers=_auth(token))
    await client.post(f"/api/workflows/{wf2}/run", json={}, headers=_auth(token))

    resp = await client.get(
        f"/api/workspaces/{ws_id}/executions?workflow_id={wf1}", headers=_auth(token)
    )
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["workflow_id"] == wf1


async def test_cursor_pagination(client: httpx.AsyncClient, session: AsyncSession) -> None:
    """25 executions, limit=10 → 10 + cursor, далее 10, затем 5 и cursor=null."""
    token = await _register(client, "paging@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)

    # создаём 25 напрямую через модель — быстрее, чем 25 HTTP-запросов
    workflow = await session.get(Workflow, uuid.UUID(wf_id))
    assert workflow is not None
    assert workflow.published_version_id is not None
    for _ in range(25):
        session.add(
            Execution(
                workflow_id=workflow.id,
                workflow_version_id=workflow.published_version_id,
                status="queued",
                attempts=0,
                max_attempts=3,
                trigger_type="manual",
                trigger_payload={},
            )
        )
    await session.commit()

    seen: set[str] = set()
    pages = 0
    cursor: str | None = None
    while True:
        url = f"/api/workspaces/{ws_id}/executions?limit=10"
        if cursor:
            url += f"&cursor={cursor}"
        resp = await client.get(url, headers=_auth(token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = [item["id"] for item in body["items"]]
        assert len(set(ids)) == len(ids)  # страницы не пересекаются
        seen.update(ids)
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 25


async def test_invalid_cursor_rejected(client: httpx.AsyncClient) -> None:
    token = await _register(client, "badcursor@example.com")
    ws_id = await _ws_id(client, token)
    resp = await client.get(
        f"/api/workspaces/{ws_id}/executions?cursor=not-a-cursor", headers=_auth(token)
    )
    assert resp.status_code == 400


def test_cursor_roundtrip() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    exec_id = uuid.uuid4()
    encoded = _encode_cursor(now, exec_id)
    decoded = _decode_cursor(encoded)
    assert decoded is not None
    assert decoded[1] == exec_id
    assert _decode_cursor("garbage") is None


# --- отмена --------------------------------------------------------------------


async def test_cancel_running_execution(client: httpx.AsyncClient, session: AsyncSession) -> None:
    token = await _register(client, "cancel@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)
    execution_id = (
        await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    ).json()["id"]

    claimed = await claim_next(session, "w")
    assert claimed is not None
    await session.commit()

    resp = await client.post(f"/api/executions/{execution_id}/cancel", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"


async def test_cancel_succeeded_conflict(client: httpx.AsyncClient, session: AsyncSession) -> None:
    token = await _register(client, "cancel409@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = await _published_workflow(client, token, ws_id)
    execution_id = (
        await client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth(token))
    ).json()["id"]

    from app.engine.queue import complete

    claimed = await claim_next(session, "w")
    assert claimed is not None
    await session.commit()
    version = await session.get(WorkflowVersion, claimed.workflow_version_id)
    assert version is not None
    await run_execution(session, claimed, version, "w")
    await complete(session, claimed.id, success=True)
    await session.commit()

    resp = await client.post(f"/api/executions/{execution_id}/cancel", headers=_auth(token))
    assert resp.status_code == 409


async def test_runner_stops_when_canceled(session: AsyncSession) -> None:
    """Отменённый между узлами запуск прерывается без выполнения следующих шагов."""
    from app.engine.runner import ExecutionCancelled

    suffix = uuid.uuid4().hex[:8]
    user = User(email=f"{suffix}@example.com", password_hash="h")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="W", slug=f"c-{suffix}", created_by=user.id)
    session.add(workspace)
    await session.flush()
    workflow = Workflow(workspace_id=workspace.id, name="WF", created_by=user.id)
    session.add(workflow)
    await session.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id, version=1, graph=VALID_GRAPH, created_by=user.id
    )
    session.add(version)
    await session.flush()

    from app.engine.queue import enqueue

    await enqueue(session, workflow.id, version.id)
    await session.commit()
    claimed = await claim_next(session, "w")
    assert claimed is not None
    await session.commit()

    # отменяем до старта обхода: runner увидит флаг на первом же узле
    claimed.status = "canceled"
    await session.commit()

    with pytest.raises(ExecutionCancelled):
        await run_execution(session, claimed, version, "w")


# --- узел action_http (MockTransport, без внешней сети) -------------------------


async def test_http_node_get_via_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    result = await handle_http(
        {"method": "GET", "url": "https://api.test/status/200", "headers": [], "query": []},
        {"http_transport": transport},
    )
    assert result["status"] == 200
    assert result["body"] == {"ok": True}
    assert "elapsed_ms" in result


async def test_http_node_posts_json_body_with_query() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        captured["method"] = request.method
        return httpx.Response(201, text="created", headers={"content-type": "text/plain"})

    transport = httpx.MockTransport(handler)
    result = await handle_http(
        {
            "method": "POST",
            "url": "https://api.test/items",
            "headers": [{"name": "X-Trace", "value": "abc"}],
            "query": [{"name": "page", "value": "2"}],
            "body": {"name": "thing"},
        },
        {"http_transport": transport},
    )
    assert result["status"] == 201
    assert result["body"] == "created"  # не-JSON → строка
    assert "page=2" in str(captured["url"])
    assert captured["method"] == "POST"
    assert '"name"' in str(captured["body"])


async def test_http_node_credential_warning_is_explicit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    result = await handle_http(
        {
            "method": "GET",
            "url": "https://api.test/x",
            "credential_id": "cred-1",
            "auth": "bearer",
        },
        {"http_transport": transport},
    )
    # заглушка credentials должна быть явной, не молчаливой
    assert "warning" in result
    assert "credentials not implemented" in str(result["warning"])


async def test_http_node_timeout_returns_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    transport = httpx.MockTransport(handler)
    result = await handle_http(
        {"method": "GET", "url": "https://api.test/slow", "timeout_s": 1},
        {"http_transport": transport},
    )
    assert "error" in result
    assert "timed out" in str(result["error"])