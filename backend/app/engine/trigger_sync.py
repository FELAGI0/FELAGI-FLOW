"""Синхронизация расписаний и вебхук-маршрутов из графа при публикации.

DESIGN.md §2: schedules и webhook_routes синхронизируются при публикации, то
есть граф — источник истины, а эти таблицы — производные от него. Поэтому sync
идемпотентен и полон: он не только добавляет/обновляет строки для узлов
опубликованной версии, но и удаляет всё, чего в графе больше нет (узел убрали,
тип триггера сменили).

Ключ сопоставления — node_id внутри workflow:
  * schedules: пара (workflow_id, node_id);
  * webhook_routes: пара (workflow_id, node_id), чтобы token переживал
    повторную публикацию — он уже выдан наружу, и его смена молча сломала бы
    настроенные интеграции.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.cron import next_run_at
from app.engine.node_schemas import DEFAULT_TIMEZONE
from app.shared.models import Schedule, WebhookRoute
from app.shared.models.webhook_route import generate_token
from app.shared.schemas.workflow import Graph, Node

logger = structlog.get_logger()

CRON_NODE_TYPE = "trigger_cron"
WEBHOOK_NODE_TYPE = "trigger_webhook"


async def sync_triggers(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    workflow_id: uuid.UUID,
    graph: Graph,
    now: datetime | None = None,
) -> dict[str, int]:
    """Приводит schedules/webhook_routes в соответствие с графом.

    Возвращает счётчики для логов: {'schedules': N, 'webhooks': M}. Коммит — за
    вызывающим (publish коммитит одной транзакцией со сменой статуса workflow).
    """
    moment = now or datetime.now(UTC)
    cron_nodes = [node for node in graph.nodes if node.type == CRON_NODE_TYPE]
    webhook_nodes = [node for node in graph.nodes if node.type == WEBHOOK_NODE_TYPE]

    await _sync_schedules(session, workspace_id, workflow_id, cron_nodes, moment)
    await _sync_webhooks(session, workspace_id, workflow_id, webhook_nodes)

    return {"schedules": len(cron_nodes), "webhooks": len(webhook_nodes)}


async def _sync_schedules(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    workflow_id: uuid.UUID,
    cron_nodes: list[Node],
    now: datetime,
) -> None:
    existing = {
        row.node_id: row
        for row in await session.scalars(
            select(Schedule).where(Schedule.workflow_id == workflow_id)
        )
    }
    stale: list[uuid.UUID] = []

    for node in cron_nodes:
        spec = str(node.params.get("cron_expr", ""))
        timezone = str(node.params.get("timezone") or DEFAULT_TIMEZONE)
        row = existing.pop(node.id, None)
        if row is None:
            session.add(
                Schedule(
                    workspace_id=workspace_id,
                    workflow_id=workflow_id,
                    kind="cron",
                    spec=spec,
                    node_id=node.id,
                    next_run_at=next_run_at(spec, timezone, now),
                    enabled=True,
                )
            )
            continue
        # повторная публикация: spec мог измениться — next_run_at пересчитываем,
        # иначе расписание продолжило бы срабатывать по старым временам
        if row.spec != spec:
            row.spec = spec
            row.next_run_at = next_run_at(spec, timezone, now)
        row.enabled = True
        # id сохраняется: пересоздание сломало бы историю и сбросило last_run_at

    stale.extend(row.id for row in existing.values())
    if stale:
        await session.execute(delete(Schedule).where(Schedule.id.in_(stale)))
        logger.info("triggers.schedules_removed", count=len(stale))


async def _sync_webhooks(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    workflow_id: uuid.UUID,
    webhook_nodes: list[Node],
) -> None:
    existing = {
        row.node_id: row
        for row in await session.scalars(
            select(WebhookRoute).where(WebhookRoute.workflow_id == workflow_id)
        )
    }
    stale: list[str] = []

    for node in webhook_nodes:
        row = existing.pop(node.id, None)
        if row is None:
            session.add(
                WebhookRoute(
                    token=generate_token(),
                    workspace_id=workspace_id,
                    workflow_id=workflow_id,
                    node_id=node.id,
                )
            )
        # существующий маршрут не трогаем: token выдан наружу и должен пережить
        # повторную публикацию (methods читаются из графа в момент вебхука)

    stale.extend(row.token for row in existing.values())
    if stale:
        await session.execute(delete(WebhookRoute).where(WebhookRoute.token.in_(stale)))
        logger.info("triggers.webhooks_removed", count=len(stale))