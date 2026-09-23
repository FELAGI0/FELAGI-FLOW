import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Workspace, WorkspaceMember
from app.shared.security import create_access_token, decode_token

PASSWORD = "password123"


async def _register(
    client: httpx.AsyncClient,
    email: str = "u@example.com",
    password: str = PASSWORD,
    name: str | None = "U",
) -> httpx.Response:
    return await client.post(
        "/api/auth/register", json={"email": email, "password": password, "name": name}
    )


async def test_register_ok(client: httpx.AsyncClient) -> None:
    resp = await _register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "refresh_token" in resp.cookies


async def test_register_creates_owner_workspace(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    resp = await _register(client, "owner@example.com", name="Owner")
    assert resp.status_code == 201

    workspace = await session.scalar(select(Workspace).where(Workspace.slug == "owner"))
    assert workspace is not None
    assert workspace.name == "Owner's workspace"

    member = await session.scalar(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id)
    )
    assert member is not None
    assert member.role == "owner"
    assert member.user_id == workspace.created_by


async def test_register_duplicate_email(client: httpx.AsyncClient) -> None:
    assert (await _register(client, "dup@example.com")).status_code == 201
    resp = await _register(client, "dup@example.com")
    assert resp.status_code == 409


async def test_register_short_password_rejected(client: httpx.AsyncClient) -> None:
    resp = await _register(client, "short@example.com", password="1234567")
    assert resp.status_code == 422


async def test_login_ok(client: httpx.AsyncClient) -> None:
    await _register(client, "login@example.com")
    resp = await client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert "refresh_token" in resp.cookies


async def test_login_wrong_password(client: httpx.AsyncClient) -> None:
    await _register(client, "wp@example.com")
    resp = await client.post(
        "/api/auth/login", json={"email": "wp@example.com", "password": "wrongpass99"}
    )
    assert resp.status_code == 401


async def test_me_without_token(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_with_token(client: httpx.AsyncClient) -> None:
    reg = await _register(client, "me@example.com", name="Me User")
    token = reg.json()["access_token"]
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "me@example.com"
    assert body["name"] == "Me User"
    assert uuid.UUID(body["id"])
    assert "created_at" in body


async def test_me_expired_token(client: httpx.AsyncClient) -> None:
    reg = await _register(client, "exp@example.com")
    uid = uuid.UUID(decode_token(reg.json()["access_token"])["sub"])
    expired = create_access_token(uid, expires_minutes=-1)
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


async def test_refresh_rotates_cookie(client: httpx.AsyncClient) -> None:
    reg = await _register(client, "ref@example.com")
    old_refresh = reg.cookies["refresh_token"]
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    new_refresh = resp.cookies["refresh_token"]
    assert new_refresh
    assert new_refresh != old_refresh  # jti случайный → ротация видна


async def test_refresh_without_cookie(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


async def test_logout_clears_cookie(client: httpx.AsyncClient) -> None:
    await _register(client, "out@example.com")
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 204
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()
