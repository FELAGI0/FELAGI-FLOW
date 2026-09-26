"""Live-логи execution через WebSocket (этап 5.B, DESIGN.md §3).

Auth — JWT в query-параметре: браузерный WebSocket не умеет кастомные
заголовки, поэтому токен приходит как `?token=<access_token>`.

Каждое соединение подписано на ОДИН execution (не на канал workspace): так
живёт ровно столько, сколько длится интерес к запуску. NOTIFY несёт только id
запуска, сами шаги клиент дочитывает из БД — источник истины всегда БД.
"""

import asyncio
import uuid

import jwt
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession
from app.api.routes.executions import _step_response, _to_response
from app.api.ws_manager import listen_manager
from app.shared.config import settings
from app.shared.models import Execution, ExecutionStep, Workflow, WorkspaceMember
from app.shared.security import ACCESS_TOKEN_TYPE, decode_token

router = APIRouter(tags=["ws"])

logger = structlog.get_logger()

# прикладные коды закрытия (RFC 6455: 4000–4999 зарезервированы под приложение)
CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_TOO_MANY = 4429
CLOSE_NORMAL = 1000

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "dead", "canceled"})


def _user_id_from_token(token: str | None) -> uuid.UUID | None:
    """Валидирует access-токен из query. None — если токена нет или он негоден."""
    if not token:
        return None
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        return None
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None


async def _authorize(
    session: AsyncSession, execution_id: uuid.UUID, user_id: uuid.UUID
) -> Execution | None:
    """Execution, если user — member workspace'а его workflow. Иначе None."""
    execution = await session.get(Execution, execution_id)
    if execution is None:
        return None
    workflow: Workflow | None = await session.get(Workflow, execution.workflow_id)
    if workflow is None:
        return None
    member = await session.get(WorkspaceMember, (workflow.workspace_id, user_id))
    if member is None:
        return None
    return execution


async def _all_steps(
    session: AsyncSession, execution_id: uuid.UUID
) -> list[dict[str, object]]:
    """Шаги запуска уже в виде payload'ов (dict).

    Сериализуем сразу, до возможного rollback: после rollback ORM-объекты
    «протухают», и обращение к их атрибутам синхронно дёрнуло бы refresh →
    MissingGreenlet. Отдаём словари — их можно слать в WS когда угодно.
    """
    rows = await session.scalars(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        # порядок — как в REST GET /executions/{id}: по sequence (номер шага),
        # который проставляет runner. created_at для порядка не годится — это
        # время транзакции, одинаковое у всех шагов запуска (5.B-fix)
        .order_by(ExecutionStep.sequence)
    )
    return [_step_response(step).model_dump(mode="json") for step in rows]


async def _read_status(
    session: AsyncSession, execution_id: uuid.UUID
) -> tuple[str, str | None]:
    """Свежие status/error без обращения к identity map (видит чужие commit)."""
    row = (
        await session.execute(
            select(Execution.status, Execution.error).where(Execution.id == execution_id)
        )
    ).one_or_none()
    if row is None:
        return "dead", "execution disappeared"
    return str(row[0]), row[1]


async def _reader(websocket: WebSocket) -> None:
    """Читает входящие (pong и т.п.), чтобы заметить разрыв соединения."""
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        return


@router.websocket("/ws/executions/{execution_id}")
async def execution_logs(
    websocket: WebSocket,
    execution_id: uuid.UUID,
    session: DbSession,
) -> None:
    user_id = _user_id_from_token(websocket.query_params.get("token"))
    if user_id is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    execution = await _authorize(session, execution_id, user_id)
    if execution is None:
        await websocket.close(code=CLOSE_NOT_FOUND)
        return

    if not listen_manager.register_connection(user_id):
        await websocket.close(code=CLOSE_TOO_MANY)
        return

    await websocket.accept()

    # подписка ДО снапшота: иначе шаг, добавленный между снапшотом и подпиской,
    # потерялся бы (гонка). Лишние уведомления отсеются по множеству sent_ids
    queue = listen_manager.subscribe(execution_id)
    sent_ids: set[str] = set()
    reader = asyncio.create_task(_reader(websocket))

    try:
        steps = await _all_steps(session, execution_id)
        execution_payload = _to_response(execution).model_dump(mode="json")
        sent_ids.update(str(step["id"]) for step in steps)
        await websocket.send_json(
            {"type": "snapshot", "execution": execution_payload, "steps": steps}
        )
        # освобождаем соединение пула между опросами: WS может жить минутами
        await session.rollback()

        status, error = await _read_status(session, execution_id)
        await session.rollback()
        if status in TERMINAL_STATUSES:
            await websocket.send_json(
                {"type": "finished", "status": status, "error": error}
            )
            await websocket.close(code=CLOSE_NORMAL)
            return

        while True:
            try:
                await asyncio.wait_for(
                    queue.get(), timeout=settings.ws_heartbeat_seconds
                )
            except TimeoutError:
                # ping против idle-таймаутов прокси (Caddy и т.п.)
                await websocket.send_json({"type": "ping"})

            if reader.done():
                break

            new_steps = [
                step
                for step in await _all_steps(session, execution_id)
                if str(step["id"]) not in sent_ids
            ]
            status, error = await _read_status(session, execution_id)
            await session.rollback()

            if new_steps:
                sent_ids.update(str(step["id"]) for step in new_steps)
                await websocket.send_json({"type": "steps", "steps": new_steps})

            if status in TERMINAL_STATUSES:
                await websocket.send_json(
                    {"type": "finished", "status": status, "error": error}
                )
                await websocket.close(code=CLOSE_NORMAL)
                break
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()
        listen_manager.unsubscribe(execution_id, queue)
        listen_manager.release_connection(user_id)