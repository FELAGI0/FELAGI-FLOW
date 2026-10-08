"""Telegram: отправка сообщения через Bot API.

Node type `action_telegram` (DESIGN.md, ПРАВКА 12). Bot-токен берётся из
credential воркспейса (`credential_id` в параметрах), расшифровывается Fernet и
в step'ах не светится: в `input` шага лежат только параметры без токена.

Внешний вызов идёт через httpx; в тестах transport инжектится через
`context["http_transport"]` (как в HTTP-узле). Сессия БД и workspace_id кладутся
runner'ом в `context` - узлу они нужны, чтобы загрузить credential.
"""

import time
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.crypto import CryptoError, decrypt
from app.shared.models import Credential

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 30.0


class CredentialError(Exception):
    """Credential не найден/удалён/непригоден - узел вернёт error, а не 500."""


async def _load_token(session: AsyncSession, workspace_id: uuid.UUID, credential_id: str) -> str:
    """Находит credential воркспейса (не удалённый) и расшифровывает bot-токен."""
    try:
        cred_uuid = uuid.UUID(str(credential_id))
    except (ValueError, TypeError) as exc:
        raise CredentialError(f"invalid credential_id '{credential_id}'") from exc

    credential: Credential | None = await session.get(Credential, cred_uuid)
    if credential is None or credential.workspace_id != workspace_id:
        raise CredentialError("credential not found")
    if credential.deleted_at is not None:
        # DESIGN.md: запуск с удалённым credential даёт внятную ошибку, а не 500
        raise CredentialError("credential deleted")

    try:
        payload = decrypt(credential.encrypted_payload)
    except CryptoError as exc:
        raise CredentialError(f"credential is unreadable: {exc}") from exc

    # payload - JSON {"token": "..."}; терпимо, если это голая строка токена
    import json

    try:
        data = json.loads(payload)
        token = data.get("token") if isinstance(data, dict) else None
    except ValueError:
        token = payload
    if not token:
        raise CredentialError("credential has no 'token' field")
    return str(token)


async def handle_telegram(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    credential_id = params.get("credential_id")
    if not credential_id:
        return {"error": "telegram node requires 'credential_id'"}

    chat_id = params.get("chat_id")
    if chat_id is None or chat_id == "":
        return {"error": "telegram node requires 'chat_id'"}
    text = params.get("text")
    if text is None or text == "":
        return {"error": "telegram node requires 'text'"}

    session: AsyncSession | None = context.get("session")
    workspace_id = context.get("workspace_id")
    if session is None or workspace_id is None:
        return {"error": "telegram node: execution context is missing session/workspace"}

    try:
        token = await _load_token(session, workspace_id, str(credential_id))
    except CredentialError as exc:
        return {"error": str(exc)}

    body: dict[str, Any] = {"chat_id": str(chat_id), "text": str(text)}
    parse_mode = params.get("parse_mode")
    if parse_mode:
        body["parse_mode"] = str(parse_mode)
    if params.get("disable_notification"):
        body["disable_notification"] = True

    url = f"{API_BASE}/bot{token}/sendMessage"
    timeout = float(params.get("timeout_s", DEFAULT_TIMEOUT_SECONDS))
    transport = context.get("http_transport")

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(url, json=body)
    except httpx.TimeoutException:
        return {"error": f"telegram request timed out after {timeout}s"}
    except httpx.HTTPError as exc:
        # в тексте ошибки может быть URL с токеном - вырезаем его
        return {"error": f"telegram request failed: {exc}".replace(token, "***")}

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    try:
        data = response.json()
    except ValueError:
        return {"error": f"telegram returned non-JSON response (HTTP {response.status_code})"}

    if response.status_code != 200 or not data.get("ok"):
        description = data.get("description") or f"HTTP {response.status_code}"
        return {"error": f"telegram API error: {description}"}

    result = data.get("result", {})
    chat = result.get("chat", {})
    return {
        "message_id": result.get("message_id"),
        "date": result.get("date"),
        "chat_id": chat.get("id", chat_id),
        "elapsed_ms": elapsed_ms,
    }
