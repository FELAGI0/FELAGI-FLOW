"""Credentials + узел action_telegram (6.A).

Часть — чистые тесты крипто и роутов (SQLite ок), часть помечена postgres:
нужны реальные FK/транзакции и вызов узла с сессией БД. Внешний HTTP в узле
подменяется httpx.MockTransport через context — реальной сети нет.
"""

import json
import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.nodes.telegram import handle_telegram
from app.shared import config
from app.shared.crypto import CryptoError, decrypt, encrypt
from app.shared.models import Credential, User, Workspace

PASSWORD = "password123"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD, "name": "U"}
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["access_token"])


async def _ws_id(client: httpx.AsyncClient, token: str) -> str:
    resp = await client.get("/api/workspaces", headers=_auth(token))
    return str(resp.json()[0]["id"])


# --- crypto (чистые) ----------------------------------------------------------


def test_encrypt_decrypt_roundtrip() -> None:
    ciphertext = encrypt("bot-token-123")
    assert isinstance(ciphertext, bytes)
    assert ciphertext != b"bot-token-123"  # не открытый текст
    assert decrypt(ciphertext) == "bot-token-123"


def test_decrypt_wrong_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    ciphertext = encrypt("secret")
    # другой валидный Fernet-ключ → InvalidToken → наша CryptoError, not трейсбек
    monkeypatch.setattr(config.settings, "fernet_key", Fernet.generate_key().decode())
    with pytest.raises(CryptoError):
        decrypt(ciphertext)


def test_encrypt_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "fernet_key", "")
    with pytest.raises(CryptoError):
        encrypt("x")


# --- REST: создание/листинг/удаление ------------------------------------------


async def test_create_credential_encrypts_payload(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    token = await _register(client, "credcreate@example.com")
    ws_id = await _ws_id(client, token)

    resp = await client.post(
        f"/api/workspaces/{ws_id}/credentials",
        json={"service": "telegram", "name": "My bot", "payload": {"token": "123:ABC"}},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["service"] == "telegram"
    assert body["auth_type"] == "bot_token"
    assert body["name"] == "My bot"
    # наружу секрет не отдаётся
    assert "payload" not in body
    assert "encrypted_payload" not in body

    # в БД лежит шифротекст, а не открытый токен
    stored = await session.get(Credential, uuid.UUID(body["id"]))
    assert stored is not None
    assert b"123:ABC" not in stored.encrypted_payload
    assert json.loads(decrypt(stored.encrypted_payload))["token"] == "123:ABC"
    assert stored.encryption_key_id == "default"


async def test_list_credentials_never_returns_payload(client: httpx.AsyncClient) -> None:
    token = await _register(client, "credlist@example.com")
    ws_id = await _ws_id(client, token)
    await client.post(
        f"/api/workspaces/{ws_id}/credentials",
        json={"service": "telegram", "name": "bot", "payload": {"token": "t"}},
        headers=_auth(token),
    )

    resp = await client.get(f"/api/workspaces/{ws_id}/credentials", headers=_auth(token))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    # ни в одном ответе нет секрета
    assert all("payload" not in item and "encrypted_payload" not in item for item in items)


async def test_delete_credential_is_soft(client: httpx.AsyncClient, session: AsyncSession) -> None:
    token = await _register(client, "creddel@example.com")
    ws_id = await _ws_id(client, token)
    created = await client.post(
        f"/api/workspaces/{ws_id}/credentials",
        json={"service": "telegram", "name": "bot", "payload": {"token": "t"}},
        headers=_auth(token),
    )
    cred_id = created.json()["id"]

    resp = await client.delete(
        f"/api/workspaces/{ws_id}/credentials/{cred_id}", headers=_auth(token)
    )
    assert resp.status_code == 204

    # в листинге больше нет
    listed = await client.get(f"/api/workspaces/{ws_id}/credentials", headers=_auth(token))
    assert listed.json()["items"] == []

    # но строка физически осталась — soft-delete
    stored = await session.get(Credential, uuid.UUID(cred_id))
    assert stored is not None
    assert stored.deleted_at is not None


async def test_member_cannot_create_credential(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    from app.shared.models import WorkspaceMember

    owner_token = await _register(client, "credowner@example.com")
    ws_id = await _ws_id(client, owner_token)

    # добавляем второго пользователя как member напрямую в БД
    ws_uuid = uuid.UUID(ws_id)
    member = User(email="credmember@example.com", password_hash="h")
    session.add(member)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=ws_uuid, user_id=member.id, role="member"))
    await session.commit()

    # member логинится и пытается создать credential → 403
    login = await client.post(
        "/api/auth/login", json={"email": "credmember@example.com", "password": PASSWORD}
    )
    assert login.status_code == 401  # пароль не тот — зададим явно
    from app.shared.security import hash_password

    member.password_hash = hash_password(PASSWORD)
    await session.commit()
    login = await client.post(
        "/api/auth/login", json={"email": "credmember@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    member_token = login.json()["access_token"]

    resp = await client.post(
        f"/api/workspaces/{ws_id}/credentials",
        json={"service": "telegram", "name": "x", "payload": {"token": "t"}},
        headers=_auth(member_token),
    )
    assert resp.status_code == 403


# --- узел action_telegram (MockTransport) -------------------------------------


async def _make_credential(session: AsyncSession, workspace_id: uuid.UUID) -> Credential:
    user = await session.scalar(select(User).where(User.email == "tg-owner@example.com"))
    if user is None:
        user = User(email="tg-owner@example.com", password_hash="h")
        session.add(user)
        await session.flush()
    credential = Credential(
        workspace_id=workspace_id,
        service="telegram",
        name="bot",
        auth_type="bot_token",
        encrypted_payload=encrypt(json.dumps({"token": "123:SECRET"})),
        encryption_key_id="default",
        created_by=user.id,
    )
    session.add(credential)
    await session.flush()
    return credential


async def _workspace(session: AsyncSession) -> Workspace:
    user = User(email=f"ws-{uuid.uuid4().hex[:8]}@example.com", password_hash="h")
    session.add(user)
    await session.flush()
    workspace = Workspace(name="W", slug=uuid.uuid4().hex[:12], created_by=user.id)
    session.add(workspace)
    await session.flush()
    return workspace


async def test_telegram_sends_message(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    credential = await _make_credential(session, workspace.id)
    await session.commit()

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 42, "date": 1700000000, "chat": {"id": 777}},
            },
        )

    transport = httpx.MockTransport(handler)
    result = await handle_telegram(
        {
            "credential_id": str(credential.id),
            "chat_id": "777",
            "text": "hello",
            "parse_mode": "",
            "disable_notification": False,
        },
        {"session": session, "workspace_id": workspace.id, "http_transport": transport},
    )

    assert result["message_id"] == 42
    assert result["chat_id"] == 777
    assert result["date"] == 1700000000
    # токен ушёл в URL, но не в тело; chat_id/text — в тело
    assert "123:SECRET" in str(captured["url"])
    assert captured["body"] == {"chat_id": "777", "text": "hello"}


async def test_telegram_api_error_returns_error(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    credential = await _make_credential(session, workspace.id)
    await session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"ok": False, "description": "Bad Request: chat not found"}
        )

    transport = httpx.MockTransport(handler)
    result = await handle_telegram(
        {"credential_id": str(credential.id), "chat_id": "1", "text": "x"},
        {"session": session, "workspace_id": workspace.id, "http_transport": transport},
    )
    assert "error" in result
    assert "chat not found" in str(result["error"])


async def test_telegram_deleted_credential_returns_clear_error(session: AsyncSession) -> None:
    from datetime import UTC, datetime

    workspace = await _workspace(session)
    credential = await _make_credential(session, workspace.id)
    credential.deleted_at = datetime.now(UTC)
    await session.commit()

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "result": {}}))
    result = await handle_telegram(
        {"credential_id": str(credential.id), "chat_id": "1", "text": "x"},
        {"session": session, "workspace_id": workspace.id, "http_transport": transport},
    )
    # внятная ошибка «credential deleted», не 500/трейсбек
    assert result.get("error") == "credential deleted"


async def test_telegram_missing_required_params() -> None:
    # без credential_id
    assert "error" in await handle_telegram({"chat_id": "1", "text": "x"}, {})
    # без text
    assert "error" in await handle_telegram({"credential_id": "c", "chat_id": "1"}, {})
    # без chat_id
    assert "error" in await handle_telegram({"credential_id": "c", "text": "x"}, {})


async def test_telegram_network_error_hides_token(session: AsyncSession) -> None:
    workspace = await _workspace(session)
    credential = await _make_credential(session, workspace.id)
    await session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    result = await handle_telegram(
        {"credential_id": str(credential.id), "chat_id": "1", "text": "x"},
        {"session": session, "workspace_id": workspace.id, "http_transport": transport},
    )
    assert "error" in result
    # токен не должен утечь в текст ошибки
    assert "123:SECRET" not in str(result["error"])