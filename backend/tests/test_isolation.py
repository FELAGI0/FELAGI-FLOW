"""Кросс-tenant изоляция: user A не может ни читать, ни менять, ни удалять
данные workspace B. Проверки — только через публичный API (httpx).

Состояние чужого workspace проверяется глазами его законного владельца
(GET от user_b), а не запросом в БД.
"""

import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import WorkspaceMember
from app.shared.security import create_access_token

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
    assert resp.status_code == 200, resp.text
    return uuid.UUID(resp.json()["id"])


async def _my_workspace(client: httpx.AsyncClient, token: str) -> dict[str, object]:
    resp = await client.get("/api/workspaces", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    workspaces: list[dict[str, object]] = resp.json()
    assert len(workspaces) == 1, f"expected exactly one workspace, got {len(workspaces)}"
    return workspaces[0]


async def _add_member(
    session: AsyncSession,
    client: httpx.AsyncClient,
    ws_id: uuid.UUID,
    email: str,
    role: str,
) -> tuple[str, uuid.UUID]:
    """Наполнение ролями — единственное место, где тест пишет в БД напрямую
    (публичного API для назначения admin/owner нет; owner появляется только при register)."""
    token = await _register(client, email)
    uid = await _user_id(client, token)
    session.add(WorkspaceMember(workspace_id=ws_id, user_id=uid, role=role))
    await session.commit()
    return token, uid


@dataclass
class Tenant:
    token: str
    user_id: uuid.UUID
    ws_id: uuid.UUID
    ws_name: str


@dataclass
class Tenants:
    a: Tenant
    b: Tenant
    member_b_token: str
    member_b_uid: uuid.UUID


@pytest.fixture
async def tenants(client: httpx.AsyncClient, session: AsyncSession) -> Tenants:
    a_token = await _register(client, "tenant_a@example.com", "A")
    b_token = await _register(client, "tenant_b@example.com", "B")

    a_ws = await _my_workspace(client, a_token)
    b_ws = await _my_workspace(client, b_token)

    member_b_token, member_b_uid = await _add_member(
        session, client, uuid.UUID(str(b_ws["id"])), "member_b@example.com", "member"
    )

    return Tenants(
        a=Tenant(
            token=a_token,
            user_id=await _user_id(client, a_token),
            ws_id=uuid.UUID(str(a_ws["id"])),
            ws_name=str(a_ws["name"]),
        ),
        b=Tenant(
            token=b_token,
            user_id=await _user_id(client, b_token),
            ws_id=uuid.UUID(str(b_ws["id"])),
            ws_name=str(b_ws["name"]),
        ),
        member_b_token=member_b_token,
        member_b_uid=member_b_uid,
    )


async def _name_as_owner(client: httpx.AsyncClient, tenant: Tenant) -> str:
    """Имя workspace глазами его владельца — проверка «чужие данные не изменились»."""
    resp = await client.get(f"/api/workspaces/{tenant.ws_id}", headers=_auth(tenant.token))
    assert resp.status_code == 200, resp.text
    return str(resp.json()["name"])


# --- прямой доступ user_a к чужому workspace B ---------------------------------


async def test_read_foreign_workspace_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.get(f"/api/workspaces/{tenants.b.ws_id}", headers=_auth(tenants.a.token))
    assert resp.status_code == 403


async def test_patch_foreign_workspace_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.patch(
        f"/api/workspaces/{tenants.b.ws_id}",
        json={"name": "hijacked"},
        headers=_auth(tenants.a.token),
    )
    assert resp.status_code == 403
    assert await _name_as_owner(client, tenants.b) == tenants.b.ws_name


async def test_delete_foreign_workspace_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.delete(
        f"/api/workspaces/{tenants.b.ws_id}", headers=_auth(tenants.a.token)
    )
    assert resp.status_code == 403
    assert await _name_as_owner(client, tenants.b) == tenants.b.ws_name


async def test_list_foreign_members_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.get(
        f"/api/workspaces/{tenants.b.ws_id}/members", headers=_auth(tenants.a.token)
    )
    assert resp.status_code == 403


async def test_patch_foreign_member_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.patch(
        f"/api/workspaces/{tenants.b.ws_id}/members/{tenants.member_b_uid}",
        json={"role": "admin"},
        headers=_auth(tenants.a.token),
    )
    assert resp.status_code == 403

    # глазами владельца ws_b: роль member_b не изменилась
    members = await client.get(
        f"/api/workspaces/{tenants.b.ws_id}/members", headers=_auth(tenants.b.token)
    )
    roles = {m["user_id"]: m["role"] for m in members.json()}
    assert roles[str(tenants.member_b_uid)] == "member"


async def test_delete_foreign_member_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.delete(
        f"/api/workspaces/{tenants.b.ws_id}/members/{tenants.member_b_uid}",
        headers=_auth(tenants.a.token),
    )
    assert resp.status_code == 403

    members = await client.get(
        f"/api/workspaces/{tenants.b.ws_id}/members", headers=_auth(tenants.b.token)
    )
    assert str(tenants.member_b_uid) in [m["user_id"] for m in members.json()]


# --- чужой workspace B: инвайты ------------------------------------------------


async def test_create_invitation_in_foreign_workspace_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.post(
        f"/api/workspaces/{tenants.b.ws_id}/invitations",
        json={"email": "intruder@example.com", "role": "member"},
        headers=_auth(tenants.a.token),
    )
    assert resp.status_code == 403

    listing = await client.get(
        f"/api/workspaces/{tenants.b.ws_id}/invitations", headers=_auth(tenants.b.token)
    )
    assert listing.json() == []


async def test_list_foreign_invitations_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.get(
        f"/api/workspaces/{tenants.b.ws_id}/invitations", headers=_auth(tenants.a.token)
    )
    assert resp.status_code == 403


async def test_revoke_foreign_invitation_forbidden(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    created = await client.post(
        f"/api/workspaces/{tenants.b.ws_id}/invitations",
        json={"email": "guest_b@example.com", "role": "member"},
        headers=_auth(tenants.b.token),
    )
    assert created.status_code == 201, created.text
    invitation_id = created.json()["id"]

    resp = await client.delete(
        f"/api/workspaces/{tenants.b.ws_id}/invitations/{invitation_id}",
        headers=_auth(tenants.a.token),
    )
    assert resp.status_code == 403

    # инвайт на месте: владелец ws_b всё ещё видит его в списке
    listing = await client.get(
        f"/api/workspaces/{tenants.b.ws_id}/invitations", headers=_auth(tenants.b.token)
    )
    assert [i["id"] for i in listing.json()] == [invitation_id]


# --- список workspace и идентичность -------------------------------------------


async def test_workspace_list_is_tenant_scoped(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    resp = await client.get("/api/workspaces", headers=_auth(tenants.a.token))
    assert resp.status_code == 200
    ids = [w["id"] for w in resp.json()]
    assert str(tenants.a.ws_id) in ids
    assert str(tenants.b.ws_id) not in ids


async def test_cannot_accept_foreign_invitation(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    created = await client.post(
        f"/api/workspaces/{tenants.b.ws_id}/invitations",
        json={"email": "invited_b@example.com", "role": "member"},
        headers=_auth(tenants.b.token),
    )
    assert created.status_code == 201, created.text
    token = created.json()["invite_url"].rsplit("/", 1)[1]

    # user_a знает token, но инвайт выпущен на чужой email → отказ
    resp = await client.post(
        f"/api/invitations/{token}/accept", headers=_auth(tenants.a.token)
    )
    assert resp.status_code == 403

    # user_a так и не стал участником ws_b
    check = await client.get(f"/api/workspaces/{tenants.b.ws_id}", headers=_auth(tenants.a.token))
    assert check.status_code == 403


async def test_tampered_token_rejected(client: httpx.AsyncClient, tenants: Tenants) -> None:
    head, payload, signature = tenants.b.token.split(".")
    mid = len(signature) // 2
    flipped = "A" if signature[mid] != "A" else "B"
    tampered = f"{head}.{payload}.{signature[:mid]}{flipped}{signature[mid + 1:]}"

    resp = await client.get("/api/auth/me", headers=_auth(tampered))
    assert resp.status_code == 401


async def test_token_for_nonexistent_user_rejected(client: httpx.AsyncClient) -> None:
    # подпись валидна, но sub не соответствует ни одному пользователю
    orphan = create_access_token(uuid.uuid4())
    resp = await client.get("/api/auth/me", headers=_auth(orphan))
    assert resp.status_code == 401


async def test_foreign_token_is_scoped_to_its_subject(
    client: httpx.AsyncClient, tenants: Tenants
) -> None:
    # валидный токен user_b действует как user_b — доступа к ws_a у него нет
    resp = await client.get(f"/api/workspaces/{tenants.a.ws_id}", headers=_auth(tenants.b.token))
    assert resp.status_code == 403


# --- ролевые ограничения внутри своего workspace -------------------------------


async def test_member_cannot_patch_own_workspace(
    client: httpx.AsyncClient, session: AsyncSession, tenants: Tenants
) -> None:
    member_a, _ = await _add_member(
        session, client, tenants.a.ws_id, "member_a@example.com", "member"
    )

    resp = await client.patch(
        f"/api/workspaces/{tenants.a.ws_id}",
        json={"name": "not allowed"},
        headers=_auth(member_a),
    )
    assert resp.status_code == 403
    assert await _name_as_owner(client, tenants.a) == tenants.a.ws_name


async def test_admin_cannot_delete_own_workspace(
    client: httpx.AsyncClient, session: AsyncSession, tenants: Tenants
) -> None:
    admin_a, _ = await _add_member(
        session, client, tenants.a.ws_id, "admin_a@example.com", "admin"
    )

    resp = await client.delete(f"/api/workspaces/{tenants.a.ws_id}", headers=_auth(admin_a))
    assert resp.status_code == 403
    assert await _name_as_owner(client, tenants.a) == tenants.a.ws_name


async def test_admin_cannot_change_member_role(
    client: httpx.AsyncClient, session: AsyncSession, tenants: Tenants
) -> None:
    admin_a, _ = await _add_member(
        session, client, tenants.a.ws_id, "admin_a2@example.com", "admin"
    )
    _, target_uid = await _add_member(
        session, client, tenants.a.ws_id, "plain_a@example.com", "member"
    )

    resp = await client.patch(
        f"/api/workspaces/{tenants.a.ws_id}/members/{target_uid}",
        json={"role": "admin"},
        headers=_auth(admin_a),
    )
    assert resp.status_code == 403

    members = await client.get(
        f"/api/workspaces/{tenants.a.ws_id}/members", headers=_auth(tenants.a.token)
    )
    roles = {m["user_id"]: m["role"] for m in members.json()}
    assert roles[str(target_uid)] == "member"