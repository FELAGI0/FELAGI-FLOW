"""Публичный приём вебхуков: POST/GET /hooks/{token} (DESIGN.md §5).

Без auth: token и есть секрет (генерируется при публикации, хранится в
webhook_routes). Роутер подключён БЕЗ префикса /api — путь /hooks/{token}
проксируется Caddy напрямую.

Приём только ставит запуск в очередь: тело вебхука попадает в trigger_payload,
а выполнение делает воркер. Ответ 202 — работа принята, не выполнена.
"""

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession
from app.engine.node_schemas import NODE_SCHEMAS
from app.engine.queue import enqueue
from app.shared.models import WebhookRoute, Workflow, WorkflowVersion

router = APIRouter(tags=["hooks"])

logger = structlog.get_logger()

# тело вебхука кладём в trigger_payload целиком — размер ограничиваем, чтобы
# не заливать JSONB мегабайтами (аналог MAX_BODY_CHARS в узле http)
MAX_BODY_CHARS = 100_000


class WebhookAcceptedResponse(BaseModel):
    execution_id: str


async def _read_body(request: Request) -> Any:
    """Тело как JSON, а иначе — строкой (curl без заголовка тоже должен работать)."""
    raw = await request.body()
    if not raw:
        return None
    try:
        return await request.json()
    except Exception:
        text = raw.decode("utf-8", errors="replace")
        if len(text) > MAX_BODY_CHARS:
            return text[:MAX_BODY_CHARS] + "... [truncated]"
        return text


async def _handle(
    token: str, method: Literal["GET", "POST"], request: Request, session: AsyncSession
) -> WebhookAcceptedResponse:
    route = await session.scalar(select(WebhookRoute).where(WebhookRoute.token == token))
    if route is None:
        # 404 и на несуществующий, и на удалённый маршрут: токен — секрет,
        # различать эти случаи наружу незачем
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown webhook token")

    workflow: Workflow | None = await session.get(Workflow, route.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if workflow.published_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Workflow is not published"
        )

    allowed = await _allowed_methods(session, workflow, route.node_id)
    if method not in allowed:
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail=f"Method {method} not allowed for this webhook",
            headers={"Allow": ", ".join(allowed)},
        )

    payload: dict[str, Any] = {
        "headers": dict(request.headers),
        "query": dict(request.query_params),
        "body": await _read_body(request),
        "method": method,
    }

    execution = await enqueue(
        session,
        workflow.id,
        workflow.published_version_id,
        trigger_type="webhook",
        trigger_payload=payload,
    )
    await session.commit()
    logger.info(
        "webhook.accepted",
        workflow_id=str(workflow.id),
        execution_id=str(execution.id),
        method=method,
    )
    return WebhookAcceptedResponse(execution_id=str(execution.id))


async def _allowed_methods(
    session: AsyncSession, workflow: Workflow, node_id: str
) -> list[str]:
    """methods из params узла-триггера опубликованной версии.

    Читаются из графа, а не из webhook_routes: так изменение списка методов
    вступает в силу при публикации, и нет второй копии параметра.
    """
    default = ["POST"]
    if workflow.published_version_id is None:
        return default
    version = await session.get(WorkflowVersion, workflow.published_version_id)
    if version is None:
        return default
    schema = NODE_SCHEMAS.get("trigger_webhook")
    for node in version.graph.get("nodes", []):
        if node.get("id") != node_id:
            continue
        params = node.get("params", {})
        if schema is not None:
            # прогоняем через схему: дефолт и валидация — в одном месте
            parsed = schema.params.model_validate(params)
            methods: list[str] = list(getattr(parsed, "methods", default))
            return methods
        methods = params.get("methods", default)
        return list(methods)
    return default


@router.post(
    "/hooks/{token}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookAcceptedResponse,
)
async def receive_webhook_post(
    token: str, request: Request, session: DbSession
) -> WebhookAcceptedResponse:
    return await _handle(token, "POST", request, session)


@router.get(
    "/hooks/{token}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookAcceptedResponse,
)
async def receive_webhook_get(
    token: str, request: Request, session: DbSession
) -> WebhookAcceptedResponse:
    return await _handle(token, "GET", request, session)