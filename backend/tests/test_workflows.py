import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Workflow, WorkflowVersion, WorkspaceMember

PASSWORD = "password123"

VALID_GRAPH = {
    "nodes": [
        {"id": "t", "type": "trigger_manual", "params": {}, "position": {"x": 0.0, "y": 0.0}},
        {
            "id": "s",
            "type": "transform_set",
            "params": {"fields": [{"name": "x", "value": "1"}]},
            "position": {"x": 1.0, "y": 0.0},
        },
        {
            "id": "d",
            "type": "debug",
            "params": {"level": "info", "message": "done"},
            "position": {"x": 2.0, "y": 0.0},
        },
    ],
    "edges": [
        {"id": "e1", "source": "t", "target": "s"},
        {"id": "e2", "source": "s", "target": "d"},
    ],
    "layout": None,
}

INVALID_GRAPH = {
    "nodes": [
        {"id": "s", "type": "transform_set", "params": {"fields": []}, "position": {}},
        {"id": "d", "type": "debug", "params": {"message": "x"}, "position": {}},
    ],
    "edges": [{"id": "e1", "source": "s", "target": "d"}],
    "layout": None,
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


async def _user_id(client: httpx.AsyncClient, token: str) -> uuid.UUID:
    resp = await client.get("/api/auth/me", headers=_auth(token))
    return uuid.UUID(resp.json()["id"])


async def _my_workspace(client: httpx.AsyncClient, token: str) -> dict[str, object]:
    resp = await client.get("/api/workspaces", headers=_auth(token))
    workspaces: list[dict[str, object]] = resp.json()
    assert len(workspaces) == 1
    return workspaces[0]


async def _ws_id(client: httpx.AsyncClient, token: str) -> uuid.UUID:
    return uuid.UUID(str((await _my_workspace(client, token))["id"]))


async def _add_member(
    session: AsyncSession, client: httpx.AsyncClient, ws_id: uuid.UUID, email: str, role: str
) -> tuple[str, uuid.UUID]:
    token = await _register(client, email)
    uid = await _user_id(client, token)
    session.add(WorkspaceMember(workspace_id=ws_id, user_id=uid, role=role))
    await session.commit()
    return token, uid


async def _create_workflow(
    client: httpx.AsyncClient, token: str, ws_id: uuid.UUID, name: str = "WF"
) -> httpx.Response:
    return await client.post(
        f"/api/workspaces/{ws_id}/workflows", json={"name": name}, headers=_auth(token)
    )


async def _save_version(
    client: httpx.AsyncClient, token: str, wf_id: str, graph: dict[str, object]
) -> httpx.Response:
    return await client.post(
        f"/api/workflows/{wf_id}/versions",
        json={"graph": graph, "change_note": "n"},
        headers=_auth(token),
    )


# --- CRUD ---------------------------------------------------------------------


async def test_create_workflow(client: httpx.AsyncClient) -> None:
    token = await _register(client, "cw@example.com")
    ws_id = await _ws_id(client, token)

    resp = await _create_workflow(client, token, ws_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "WF"
    assert body["status"] == "draft"
    assert body["published_version_id"] is None


async def test_member_can_create_but_not_publish(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner = await _register(client, "cw_owner@example.com")
    ws_id = await _ws_id(client, owner)
    member, _ = await _add_member(session, client, ws_id, "cw_member@example.com", "member")

    created = await _create_workflow(client, member, ws_id)
    assert created.status_code == 201, created.text
    wf_id = created.json()["id"]
    assert (await _save_version(client, member, wf_id, VALID_GRAPH)).status_code == 201

    published = await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(member))
    assert published.status_code == 403


async def test_list_workflows_scoped_to_workspace(client: httpx.AsyncClient) -> None:
    a = await _register(client, "lw_a@example.com")
    b = await _register(client, "lw_b@example.com")
    a_ws = await _ws_id(client, a)
    b_ws = await _ws_id(client, b)
    await _create_workflow(client, a, a_ws, "A-WF")
    await _create_workflow(client, b, b_ws, "B-WF")

    a_list = await client.get(f"/api/workspaces/{a_ws}/workflows", headers=_auth(a))
    assert [w["name"] for w in a_list.json()] == ["A-WF"]

    # чужой workspace в списке не виден
    b_list = await client.get(f"/api/workspaces/{a_ws}/workflows", headers=_auth(b))
    assert b_list.status_code == 403


async def test_get_foreign_workflow_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = await _register(client, "gw_a@example.com")
    a_ws = await _ws_id(client, a)
    wf_id = (await _create_workflow(client, a, a_ws)).json()["id"]

    b = await _register(client, "gw_b@example.com")
    resp = await client.get(f"/api/workflows/{wf_id}", headers=_auth(b))
    assert resp.status_code == 403
    assert (await client.get(f"/api/workflows/{wf_id}", headers=_auth(a))).status_code == 200


async def test_rename_workflow_by_owner(client: httpx.AsyncClient) -> None:
    token = await _register(client, "rw@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id, "Old")).json()["id"]

    resp = await client.patch(
        f"/api/workflows/{wf_id}", json={"name": "New"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


async def test_patch_status_active_rejected(client: httpx.AsyncClient) -> None:
    token = await _register(client, "pw@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]

    # 'active' — только через publish, иначе Literal → 422
    resp = await client.patch(
        f"/api/workflows/{wf_id}", json={"status": "active"}, headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_delete_workflow_cascades_versions(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "dw@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]
    await _save_version(client, token, wf_id, VALID_GRAPH)
    wf_uuid = uuid.UUID(wf_id)

    resp = await client.delete(f"/api/workflows/{wf_id}", headers=_auth(token))
    assert resp.status_code == 204

    assert await session.get(Workflow, wf_uuid) is None
    left = await session.scalars(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf_uuid)
    )
    assert left.all() == []


# --- версии -------------------------------------------------------------------


async def test_save_version_increments(client: httpx.AsyncClient) -> None:
    token = await _register(client, "sv@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]

    first = await _save_version(client, token, wf_id, VALID_GRAPH)
    assert first.status_code == 201, first.text
    assert first.json()["version"] == 1

    second = await _save_version(client, token, wf_id, VALID_GRAPH)
    assert second.status_code == 201
    assert second.json()["version"] == 2

    listing = await client.get(f"/api/workflows/{wf_id}/versions", headers=_auth(token))
    assert [v["version"] for v in listing.json()] == [2, 1]


async def test_save_invalid_graph_rejected(client: httpx.AsyncClient) -> None:
    token = await _register(client, "siv@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]

    resp = await _save_version(client, token, wf_id, INVALID_GRAPH)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["message"] == "Graph validation failed"
    assert any("trigger" in e for e in detail["errors"])


async def test_get_specific_version(client: httpx.AsyncClient) -> None:
    token = await _register(client, "gv@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]
    await _save_version(client, token, wf_id, VALID_GRAPH)

    resp = await client.get(f"/api/workflows/{wf_id}/versions/1", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["version"] == 1

    missing = await client.get(f"/api/workflows/{wf_id}/versions/99", headers=_auth(token))
    assert missing.status_code == 404


# --- публикация ---------------------------------------------------------------


async def test_publish_without_versions_conflict(client: httpx.AsyncClient) -> None:
    token = await _register(client, "pwv@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]

    resp = await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(token))
    assert resp.status_code == 409


async def test_publish_valid_version(client: httpx.AsyncClient) -> None:
    token = await _register(client, "pv@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]
    version_id = (await _save_version(client, token, wf_id, VALID_GRAPH)).json()["id"]

    resp = await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 1
    assert body["published_version_id"] == version_id

    detail = await client.get(f"/api/workflows/{wf_id}", headers=_auth(token))
    assert detail.json()["status"] == "active"
    assert detail.json()["published_version_id"] == version_id


async def test_publish_invalid_version_rejected(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "piv@example.com")
    ws_id = await _ws_id(client, token)
    wf_id = (await _create_workflow(client, token, ws_id)).json()["id"]
    uid = await _user_id(client, token)

    # версия в обход валидации роута — прямо через модель
    session.add(
        WorkflowVersion(
            workflow_id=uuid.UUID(wf_id),
            version=1,
            graph=INVALID_GRAPH,
            change_note=None,
            created_by=uid,
        )
    )
    await session.commit()

    resp = await client.post(f"/api/workflows/{wf_id}/publish", headers=_auth(token))
    assert resp.status_code == 422
    assert any("trigger" in e for e in resp.json()["detail"]["errors"])


# --- каталог node-types -------------------------------------------------------


async def test_node_types_catalog(client: httpx.AsyncClient) -> None:
    token = await _register(client, "nt@example.com")
    resp = await client.get("/api/node-types", headers=_auth(token))
    assert resp.status_code == 200
    by_type = {n["type"]: n for n in resp.json()}
    assert "trigger_manual" in by_type
    assert "logic_if" in by_type
    assert by_type["logic_if"]["outputs"] == ["true", "false"]
    assert by_type["trigger_manual"]["category"] == "trigger"
    assert "properties" in by_type["debug"]["params_schema"]


async def test_node_types_all_have_schema(client: httpx.AsyncClient) -> None:
    token = await _register(client, "nt2@example.com")
    resp = await client.get("/api/node-types", headers=_auth(token))
    for node in resp.json():
        assert node["params_schema"], node["type"]
        assert node["outputs"], node["type"]


async def test_workspace_untouched_after_foreign_ops(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = await _register(client, "iso_a@example.com")
    b = await _register(client, "iso_b@example.com")
    a_ws = await _ws_id(client, a)
    b_ws = await _ws_id(client, b)
    b_wf = (await _create_workflow(client, b, b_ws, "B")).json()["id"]

    # все попытки user_a против чужого workflow — отказ
    assert (await client.get(f"/api/workflows/{b_wf}", headers=_auth(a))).status_code == 403
    assert (
        await client.patch(f"/api/workflows/{b_wf}", json={"name": "X"}, headers=_auth(a))
    ).status_code == 403
    assert (await client.delete(f"/api/workflows/{b_wf}", headers=_auth(a))).status_code == 403
    assert (
        await _save_version(client, a, b_wf, VALID_GRAPH)
    ).status_code == 403

    # workflow B не изменился и виден владельцу
    still = await client.get(f"/api/workflows/{b_wf}", headers=_auth(b))
    assert still.status_code == 200
    assert still.json()["name"] == "B"
    assert a_ws != b_ws