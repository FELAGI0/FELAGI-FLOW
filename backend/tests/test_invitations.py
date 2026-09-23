import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Invitation, Workspace, WorkspaceMember

PASSWORD = "password123"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, email: str, name: str = "U") -> str:
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD, "name": name}
    )
    assert resp.status_code == 201, resp.text
    access_token: str = resp.json()["access_token"]
    return access_token


async def _user_id(client: httpx.AsyncClient, token: str) -> uuid.UUID:
    resp = await client.get("/api/auth/me", headers=_auth(token))
    return uuid.UUID(resp.json()["id"])


async def _owner_workspace(session: AsyncSession, slug: str) -> Workspace:
    ws = await session.scalar(select(Workspace).where(Workspace.slug == slug))
    assert ws is not None
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


async def _create_invite(
    client: httpx.AsyncClient, token: str, ws_id: uuid.UUID, email: str, role: str = "member"
) -> httpx.Response:
    return await client.post(
        f"/api/workspaces/{ws_id}/invitations",
        json={"email": email, "role": role},
        headers=_auth(token),
    )


async def test_owner_creates_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner@example.com", "Owner")
    ws = await _owner_workspace(session, "owner")

    resp = await _create_invite(client, owner_token, ws.id, "invitee@example.com")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "invitee@example.com"
    assert body["role"] == "member"
    assert body["invite_url"].startswith("http://localhost/invite/")
    # в URL лежит token, а не id инвайта — проверяем, что хвост непустой
    assert len(body["invite_url"].rsplit("/", 1)[1]) >= 32


async def test_admin_creates_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _register(client, "owner2@example.com", "Owner")
    ws = await _owner_workspace(session, "owner2")
    admin_token, _ = await _add_member(session, client, ws.id, "admin@example.com", "admin")

    resp = await _create_invite(client, admin_token, ws.id, "newbie@example.com")
    assert resp.status_code == 201, resp.text


async def test_member_cannot_create_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _register(client, "owner3@example.com", "Owner")
    ws = await _owner_workspace(session, "owner3")
    member_token, _ = await _add_member(session, client, ws.id, "member@example.com", "member")

    resp = await _create_invite(client, member_token, ws.id, "x@example.com")
    assert resp.status_code == 403


async def test_invite_existing_member_conflict(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner4@example.com", "Owner")
    ws = await _owner_workspace(session, "owner4")
    _, _ = await _add_member(session, client, ws.id, "already@example.com", "member")

    resp = await _create_invite(client, owner_token, ws.id, "already@example.com")
    assert resp.status_code == 409


async def test_invite_duplicate_active_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner5@example.com", "Owner")
    ws = await _owner_workspace(session, "owner5")

    assert (await _create_invite(client, owner_token, ws.id, "dup@example.com")).status_code == 201
    resp = await _create_invite(client, owner_token, ws.id, "dup@example.com")
    assert resp.status_code == 409


async def test_invite_role_owner_rejected(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner6@example.com", "Owner")
    ws = await _owner_workspace(session, "owner6")

    resp = await _create_invite(client, owner_token, ws.id, "second@example.com", role="owner")
    assert resp.status_code == 422


async def test_accept_valid_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner7@example.com", "Owner")
    ws = await _owner_workspace(session, "owner7")
    invite = (await _create_invite(client, owner_token, ws.id, "joiner@example.com")).json()

    token = invite["invite_url"].rsplit("/", 1)[1]
    joiner_token = await _register(client, "joiner@example.com", "Joiner")
    uid = await _user_id(client, joiner_token)

    resp = await client.post(f"/api/invitations/{token}/accept", headers=_auth(joiner_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace_id"] == str(ws.id)
    assert body["role"] == "member"

    member = await session.get(WorkspaceMember, (ws.id, uid))
    assert member is not None
    assert member.role == "member"


async def test_accept_expired_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner8@example.com", "Owner")
    ws = await _owner_workspace(session, "owner8")
    owner_uid = await _user_id(client, owner_token)

    expired = Invitation(
        workspace_id=ws.id,
        email="late@example.com",
        role="member",
        token="expired-token",
        expires_at=datetime.now(UTC) - timedelta(days=1),
        created_by=owner_uid,
    )
    session.add(expired)
    await session.commit()

    late_token = await _register(client, "late@example.com", "Late")
    resp = await client.post("/api/invitations/expired-token/accept", headers=_auth(late_token))
    assert resp.status_code == 410


async def test_accept_wrong_email_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner9@example.com", "Owner")
    ws = await _owner_workspace(session, "owner9")
    invite = (
        await _create_invite(client, owner_token, ws.id, "intended@example.com")
    ).json()
    token = invite["invite_url"].rsplit("/", 1)[1]

    other_token = await _register(client, "other@example.com", "Other")
    resp = await client.post(f"/api/invitations/{token}/accept", headers=_auth(other_token))
    assert resp.status_code == 403


async def test_accept_consumes_token(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner10@example.com", "Owner")
    ws = await _owner_workspace(session, "owner10")
    invite = (await _create_invite(client, owner_token, ws.id, "once@example.com")).json()
    token = invite["invite_url"].rsplit("/", 1)[1]

    join_token = await _register(client, "once@example.com", "Once")
    assert (
        await client.post(f"/api/invitations/{token}/accept", headers=_auth(join_token))
    ).status_code == 200

    resp = await client.post(f"/api/invitations/{token}/accept", headers=_auth(join_token))
    assert resp.status_code == 404


async def test_accept_when_already_member_conflict(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner11@example.com", "Owner")
    ws = await _owner_workspace(session, "owner11")
    owner_uid = await _user_id(client, owner_token)

    # инвайт создаём напрямую, минуя роут: участник уже в workspace, роут вернул бы 409
    token = "already-member-token"
    session.add(
        Invitation(
            workspace_id=ws.id,
            email="dupe@example.com",
            role="member",
            token=token,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_by=owner_uid,
        )
    )
    await session.commit()

    dupe_token = await _register(client, "dupe@example.com", "Dupe")
    uid = await _user_id(client, dupe_token)
    session.add(WorkspaceMember(workspace_id=ws.id, user_id=uid, role="member"))
    await session.commit()

    resp = await client.post(f"/api/invitations/{token}/accept", headers=_auth(dupe_token))
    assert resp.status_code == 409


async def test_revoke_by_member_forbidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner12@example.com", "Owner")
    ws = await _owner_workspace(session, "owner12")
    member_token, _ = await _add_member(session, client, ws.id, "revoker@example.com", "member")
    invite = (
        await _create_invite(client, owner_token, ws.id, "target@example.com")
    ).json()

    resp = await client.delete(
        f"/api/workspaces/{ws.id}/invitations/{invite['id']}", headers=_auth(member_token)
    )
    assert resp.status_code == 403


async def test_revoke_by_owner_removes_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner13@example.com", "Owner")
    ws = await _owner_workspace(session, "owner13")
    invite = (
        await _create_invite(client, owner_token, ws.id, "gone@example.com")
    ).json()

    resp = await client.delete(
        f"/api/workspaces/{ws.id}/invitations/{invite['id']}", headers=_auth(owner_token)
    )
    assert resp.status_code == 204

    left = await session.scalar(select(Invitation).where(Invitation.id == uuid.UUID(invite["id"])))
    assert left is None


async def test_list_invitations_requires_admin(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner14@example.com", "Owner")
    ws = await _owner_workspace(session, "owner14")
    await _create_invite(client, owner_token, ws.id, "listed@example.com")

    listed = await client.get(f"/api/workspaces/{ws.id}/invitations", headers=_auth(owner_token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    member_token, _ = await _add_member(session, client, ws.id, "viewer@example.com", "member")
    forbidden = await client.get(
        f"/api/workspaces/{ws.id}/invitations", headers=_auth(member_token)
    )
    assert forbidden.status_code == 403


async def test_non_member_cannot_create_invitation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _register(client, "owner15@example.com", "Owner")
    ws = await _owner_workspace(session, "owner15")
    outsider_token = await _register(client, "outsider@example.com", "Outsider")

    resp = await _create_invite(client, outsider_token, ws.id, "nope@example.com")
    assert resp.status_code == 403


async def test_invite_unknown_workspace_not_found(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    owner_token = await _register(client, "owner16@example.com", "Owner")

    resp = await _create_invite(client, owner_token, uuid.uuid4(), "ghost@example.com")
    assert resp.status_code == 404