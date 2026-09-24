import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Workspace, WorkspaceMember

PASSWORD = "password123"


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


async def _owner_workspace(
    client: httpx.AsyncClient, session: AsyncSession, token: str
) -> Workspace:
    # по created_by, а не по slug: slug нормализуется из email (подчёркивания → дефисы)
    uid = await _user_id(client, token)
    ws = await session.scalar(select(Workspace).where(Workspace.created_by == uid))
    assert ws is not None, "registered owner has no workspace"
    return ws


async def _add_member(
    session: AsyncSession,
    client: httpx.AsyncClient,
    ws_id: uuid.UUID,
    email: str,
    role: str,
) -> tuple[str, uuid.UUID]:
    token = await _register(client, email)
    uid = await _user_id(client, token)
    session.add(WorkspaceMember(workspace_id=ws_id, user_id=uid, role=role))
    await session.commit()
    return token, uid


async def test_list_only_own_workspaces(client: httpx.AsyncClient) -> None:
    alice = await _register(client, "alice@example.com", "Alice")
    bob = await _register(client, "bob@example.com", "Bob")

    alice_list = await client.get("/api/workspaces", headers=_auth(alice))
    assert alice_list.status_code == 200
    assert [w["slug"] for w in alice_list.json()] == ["alice"]

    bob_list = await client.get("/api/workspaces", headers=_auth(bob))
    assert [w["slug"] for w in bob_list.json()] == ["bob"]


async def test_list_includes_current_user_role(client: httpx.AsyncClient) -> None:
    token = await _register(client, "role@example.com", "Role")
    resp = await client.get("/api/workspaces", headers=_auth(token))
    assert resp.json()[0]["current_user_role"] == "owner"


async def test_get_workspace_as_member(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "getter@example.com", "Getter")
    ws = await _owner_workspace(client, session, token)

    resp = await client.get(f"/api/workspaces/{ws.id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Getter's workspace"


async def test_get_workspace_non_member_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner = await _register(client, "owner_a@example.com", "OwnerA")
    ws = await _owner_workspace(client, session, owner)
    outsider = await _register(client, "outsider@example.com", "Outsider")

    resp = await client.get(f"/api/workspaces/{ws.id}", headers=_auth(outsider))
    assert resp.status_code == 403


async def test_get_workspace_not_found(client: httpx.AsyncClient) -> None:
    token = await _register(client, "nobody@example.com", "Nobody")
    resp = await client.get(f"/api/workspaces/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


async def test_rename_by_owner(client: httpx.AsyncClient, session: AsyncSession) -> None:
    token = await _register(client, "ren_owner@example.com", "RenOwner")
    ws = await _owner_workspace(client, session, token)

    resp = await client.patch(
        f"/api/workspaces/{ws.id}", json={"name": "Renamed"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


async def test_rename_by_admin(client: httpx.AsyncClient, session: AsyncSession) -> None:
    owner = await _register(client, "ren_admin_owner@example.com", "X")
    ws = await _owner_workspace(client, session, owner)
    admin, _ = await _add_member(session, client, ws.id, "ren_admin@example.com", "admin")

    resp = await client.patch(
        f"/api/workspaces/{ws.id}", json={"name": "ByAdmin"}, headers=_auth(admin)
    )
    assert resp.status_code == 200


async def test_rename_by_member_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner = await _register(client, "ren_member_owner@example.com", "X")
    ws = await _owner_workspace(client, session, owner)
    member, _ = await _add_member(session, client, ws.id, "ren_member@example.com", "member")

    resp = await client.patch(
        f"/api/workspaces/{ws.id}", json={"name": "Nope"}, headers=_auth(member)
    )
    assert resp.status_code == 403


async def test_delete_by_owner_cascades(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "del_owner@example.com", "DelOwner")
    ws = await _owner_workspace(client, session, token)
    ws_id = ws.id
    await _add_member(session, client, ws_id, "del_member@example.com", "member")

    resp = await client.delete(f"/api/workspaces/{ws_id}", headers=_auth(token))
    assert resp.status_code == 204

    assert await session.get(Workspace, ws_id) is None
    left = await session.scalars(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id)
    )
    assert left.all() == []


async def test_delete_by_admin_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner = await _register(client, "del_admin_owner@example.com", "X")
    ws = await _owner_workspace(client, session, owner)
    admin, _ = await _add_member(session, client, ws.id, "del_admin@example.com", "admin")

    resp = await client.delete(f"/api/workspaces/{ws.id}", headers=_auth(admin))
    assert resp.status_code == 403


async def test_list_members_with_roles(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "listm_owner@example.com", "Owner")
    ws = await _owner_workspace(client, session, token)
    await _add_member(session, client, ws.id, "listm_admin@example.com", "admin")

    resp = await client.get(f"/api/workspaces/{ws.id}/members", headers=_auth(token))
    assert resp.status_code == 200
    roles = {m["email"]: m["role"] for m in resp.json()}
    assert roles["listm_owner@example.com"] == "owner"
    assert roles["listm_admin@example.com"] == "admin"


async def test_update_role_by_owner(client: httpx.AsyncClient, session: AsyncSession) -> None:
    token = await _register(client, "upd_owner@example.com", "Owner")
    ws = await _owner_workspace(client, session, token)
    _, uid = await _add_member(session, client, ws.id, "promote@example.com", "member")

    resp = await client.patch(
        f"/api/workspaces/{ws.id}/members/{uid}", json={"role": "admin"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    target = await session.get(WorkspaceMember, (ws.id, uid))
    assert target is not None
    assert target.role == "admin"


async def test_update_role_by_admin_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner = await _register(client, "upd_admin_owner@example.com", "X")
    ws = await _owner_workspace(client, session, owner)
    admin, _ = await _add_member(session, client, ws.id, "upd_admin@example.com", "admin")
    _, target_uid = await _add_member(session, client, ws.id, "upd_target@example.com", "member")

    resp = await client.patch(
        f"/api/workspaces/{ws.id}/members/{target_uid}",
        json={"role": "admin"},
        headers=_auth(admin),
    )
    assert resp.status_code == 403


async def test_update_owner_role_conflict(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "upd_owner2@example.com", "Owner")
    ws = await _owner_workspace(client, session, token)
    _, uid = await _add_member(session, client, ws.id, "second2@example.com", "member")
    # делаем второго участника owner'ом напрямую: роут owner'а не назначает
    target = await session.get(WorkspaceMember, (ws.id, uid))
    assert target is not None
    target.role = "owner"
    await session.commit()

    resp = await client.patch(
        f"/api/workspaces/{ws.id}/members/{uid}", json={"role": "member"}, headers=_auth(token)
    )
    assert resp.status_code == 409


async def test_update_own_role_conflict(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "self_role@example.com", "Self")
    ws = await _owner_workspace(client, session, token)
    uid = await _user_id(client, token)

    resp = await client.patch(
        f"/api/workspaces/{ws.id}/members/{uid}", json={"role": "admin"}, headers=_auth(token)
    )
    assert resp.status_code == 409


async def test_remove_member_by_owner(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "rm_owner@example.com", "Owner")
    ws = await _owner_workspace(client, session, token)
    _, uid = await _add_member(session, client, ws.id, "removable@example.com", "member")

    resp = await client.delete(f"/api/workspaces/{ws.id}/members/{uid}", headers=_auth(token))
    assert resp.status_code == 204
    assert await session.get(WorkspaceMember, (ws.id, uid)) is None


async def test_remove_self_forbidden(client: httpx.AsyncClient, session: AsyncSession) -> None:
    token = await _register(client, "rm_self@example.com", "Self")
    ws = await _owner_workspace(client, session, token)
    uid = await _user_id(client, token)

    resp = await client.delete(f"/api/workspaces/{ws.id}/members/{uid}", headers=_auth(token))
    assert resp.status_code == 403


async def test_remove_owner_forbidden(client: httpx.AsyncClient, session: AsyncSession) -> None:
    owner = await _register(client, "rm_owner_target@example.com", "Owner")
    ws = await _owner_workspace(client, session, owner)
    admin, _ = await _add_member(session, client, ws.id, "rm_owner_admin@example.com", "admin")
    owner_row = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id, WorkspaceMember.role == "owner"
        )
    )
    assert owner_row is not None

    resp = await client.delete(
        f"/api/workspaces/{ws.id}/members/{owner_row.user_id}", headers=_auth(admin)
    )
    assert resp.status_code == 403


async def test_admin_remove_other_admin_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner = await _register(client, "adm_adm_owner@example.com", "Owner")
    ws = await _owner_workspace(client, session, owner)
    admin1, _ = await _add_member(session, client, ws.id, "admin1@example.com", "admin")
    _, admin2_uid = await _add_member(session, client, ws.id, "admin2@example.com", "admin")

    resp = await client.delete(
        f"/api/workspaces/{ws.id}/members/{admin2_uid}", headers=_auth(admin1)
    )
    assert resp.status_code == 403


async def test_admin_remove_member_ok(client: httpx.AsyncClient, session: AsyncSession) -> None:
    owner = await _register(client, "adm_mem_owner@example.com", "Owner")
    ws = await _owner_workspace(client, session, owner)
    admin, _ = await _add_member(session, client, ws.id, "adm_mem_admin@example.com", "admin")
    _, member_uid = await _add_member(session, client, ws.id, "plain@example.com", "member")

    resp = await client.delete(
        f"/api/workspaces/{ws.id}/members/{member_uid}", headers=_auth(admin)
    )
    assert resp.status_code == 204