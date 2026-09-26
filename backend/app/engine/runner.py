"""Движок выполнения: топологический обход графа с ветвлением If.

Запуск идёт строго против пиннутой версии графа. Узлы выполняются в
топологическом порядке (Kahn); невыбранные ветки If помечаются skipped
вместе со всеми потомками — merge в MVP отсутствует (DESIGN.md §4).
"""

import asyncio
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import expressions
from app.engine.node_schemas import NODE_SCHEMAS, RetryConfig
from app.engine.nodes import handle
from app.engine.notify import notify_exec_log
from app.engine.queue import heartbeat
from app.shared.models import Execution, ExecutionStep, WorkflowVersion
from app.shared.schemas.workflow import Graph, Node

IF_NODE_TYPE = "logic_if"

# точка подмены для тестов: patching asyncio.sleep задел бы весь процесс,
# включая пул соединений SQLAlchemy
_sleep = asyncio.sleep


class StepCounter:
    """Счётчик шагов в пределах одного запуска: sequence = 1, 2, 3...

    Вариант (b) из 5.B-fix: номер шага считаем в памяти, а не
    `SELECT MAX(sequence)+1` на каждый шаг. Сид задаётся один раз в начале
    run_execution (см. `_seed_counter`): при повторном запуске после reclaim
    он продолжает нумерацию, а не начинает с 1 — иначе sequence продублировался бы.
    """

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def take(self) -> int:
        value = self._next
        self._next += 1
        return value


async def _seed_counter(session: AsyncSession, execution_id: uuid.UUID) -> StepCounter:
    """Счётчик, продолжающий нумерацию уже записанных шагов запуска.

    При первичном запуске шагов нет → MAX = NULL → старт с 1.
    """
    last: int | None = await session.scalar(
        select(func.max(ExecutionStep.sequence)).where(
            ExecutionStep.execution_id == execution_id
        )
    )
    return StepCounter(start=(last or 0) + 1)


class NodeExecutionError(Exception):
    """Узел вернул ошибку или упал — запуск останавливается."""


class ExecutionCancelled(Exception):
    """Пользователь отменил запуск: прерываемся между узлами, без retry."""


def _backoff_delay(config: RetryConfig, attempt: int) -> float:
    """Задержка перед повтором после попытки номер `attempt` (1-based), в секундах.

    fixed: всегда base_s. exponential: base_s * 2**(attempt-1), то есть
    attempt=1 → base_s, attempt=2 → 2*base_s, attempt=3 → 4*base_s.
    """
    if config.backoff == "fixed":
        return config.base_s
    multiplier: float = float(2 ** (attempt - 1))
    return config.base_s * multiplier


def topological_order(graph: Graph) -> list[Node]:
    """Порядок выполнения: Kahn. Граф уже провалидирован при публикации."""
    by_id = {node.id: node for node in graph.nodes}
    indegree: dict[str, int] = dict.fromkeys(by_id, 0)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.source in by_id and edge.target in by_id:
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

    # стабильный порядок: триггеры первыми среди равных (indegree=0)
    roots = [nid for nid in by_id if indegree[nid] == 0]
    roots.sort(key=lambda nid: (not by_id[nid].type.startswith("trigger_"), nid))
    queue = deque(roots)

    order: list[Node] = []
    while queue:
        current = queue.popleft()
        order.append(by_id[current])
        for neighbour in adjacency[current]:
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                queue.append(neighbour)
    return order


def _descendants(start: str, graph: Graph) -> set[str]:
    """Все узлы, достижимые из start (включая его) — для пометки skipped."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        adjacency[edge.source].append(edge.target)

    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency[current])
    return seen


def _reaching_handle(node_id: str, graph: Graph) -> str | None:
    """Через какой sourceHandle If приходит это ребро (для определения ветки)."""
    for edge in graph.edges:
        if edge.target == node_id:
            return edge.sourceHandle
    return None


async def _record_step(
    session: AsyncSession,
    execution_id: uuid.UUID,
    sequence: int,
    node: Node,
    status: str,
    input_params: dict[str, Any] | None,
    output: dict[str, Any] | None,
    error: str | None = None,
    warnings: list[str] | None = None,
    duration_ms: int | None = None,
    attempt: int = 1,
) -> None:
    """Записывает шаг и СРАЗУ коммитит его (5.B-fix).

    Коммит на шаг, а не общий в конце запуска: live-логи показывают шаги по мере
    выполнения, и при падении узла уже выполненные шаги остаются записанными.
    NOTIFY идёт ДО коммита — Postgres доставляет уведомление только на commit
    своей транзакции; notify после commit попал бы в следующую транзакцию и
    уведомления по шагам схлопнулись бы.
    """
    session.add(
        ExecutionStep(
            execution_id=execution_id,
            node_id=node.id,
            node_type=node.type,
            sequence=sequence,
            attempt=attempt,
            status=status,
            input=input_params,
            output=output,
            error=error,
            warnings=warnings or [],
            duration_ms=duration_ms,
        )
    )
    await session.flush()
    await notify_exec_log(session, execution_id)
    await session.commit()


def load_graph(version: WorkflowVersion) -> Graph:
    return Graph.model_validate(version.graph)


async def _run_node_with_retry(
    session: AsyncSession,
    execution: Execution,
    node: Node,
    worker_id: str,
    resolved: dict[str, Any],
    context: dict[str, Any],
    retry: RetryConfig,
    counter: StepCounter,
) -> dict[str, Any]:
    """Выполняет узел, повторяя при ошибке до retry.max_retries раз.

    Каждая попытка пишется в execution_steps со своим номером (attempt=1,2,3...);
    между попытками — пауза backoff и heartbeat, иначе reclaim сочёл бы живого
    воркера зависшим и запустил бы узел параллельно.
    duration_ms последней записи покрывает ВСЕ попытки: это время, которое узел
    в сумме занимал в запуске.
    """
    started = time.perf_counter()
    attempt = 0
    while True:
        attempt += 1
        error: str | None = None
        result: dict[str, Any] = {}
        try:
            result = await handle(node.type, resolved, context)
        except Exception as exc:  # любая ошибка узла = ошибка попытки
            error = str(exc)
        else:
            if "error" in result:
                error = str(result["error"])

        if error is None:
            warnings = [result["warning"]] if "warning" in result else []
            await _record_step(
                session,
                execution.id,
                counter.take(),
                node,
                "succeeded",
                resolved,
                result,
                warnings=warnings,
                duration_ms=int((time.perf_counter() - started) * 1000),
                attempt=attempt,
            )
            return result

        # попытка провалилась: пишем failed и решаем, повторять ли
        error_payload = result if result else {"error": error}
        await _record_step(
            session,
            execution.id,
            counter.take(),
            node,
            "failed",
            resolved,
            error_payload,
            error,
            duration_ms=int((time.perf_counter() - started) * 1000),
            attempt=attempt,
        )

        if attempt > retry.max_retries:
            raise NodeExecutionError(f"node '{node.id}': {error}")

        await _sleep(_backoff_delay(retry, attempt))
        await heartbeat(session, execution.id, worker_id)


async def run_execution(
    session: AsyncSession,
    execution: Execution,
    version: WorkflowVersion,
    worker_id: str,
) -> None:
    """Выполняет граф пиннутой версии. Бросает NodeExecutionError при падении узла.

    Каждый шаг коммитится отдельно (внутри _record_step) — live-логи видят шаги
    по мере выполнения, а при падении узла выполненные шаги уже зафиксированы.
    Вызывающий (воркер) после успеха/падения коммитит только финальный статус
    execution.
    """
    graph = load_graph(version)
    order = topological_order(graph)
    # счётчик продолжает нумерацию: при rerun после reclaim старые шаги уже в БД
    counter = await _seed_counter(session, execution.id)

    context: dict[str, Any] = {
        "nodes": {},
        "trigger": {"payload": execution.trigger_payload or {}},
    }

    skipped: set[str] = set()
    if_branch: dict[str, str] = {}  # node_id If → выбранная ветка

    for node in order:
        # heartbeat перед каждым узлом: долгий граф не должен считаться зависшим.
        # Коммитим heartbeat сразу: шаги коммитятся сами, и без этого продление
        # лока потерялось бы между шагами.
        await heartbeat(session, execution.id, worker_id)
        await session.commit()

        # отмена — best effort: флаг читаем из БД перед каждым узлом. Отдельный
        # scalar-select (не session.get) идёт в БД и видит чужой commit, минуя
        # identity map сессии
        current_status = await session.scalar(
            select(Execution.status).where(Execution.id == execution.id)
        )
        if current_status == "canceled":
            raise ExecutionCancelled("canceled")

        if node.id in skipped:
            await _record_step(
                session, execution.id, counter.take(), node, "skipped", None, None
            )
            continue

        # узел, достижимый только через невыбранную ветку If, — пропускаем
        handle_taken = _reaching_handle(node.id, graph)
        if handle_taken is not None:
            parent = next(
                (e.source for e in graph.edges if e.target == node.id),
                None,
            )
            if parent is not None and if_branch.get(parent) not in (None, handle_taken):
                skipped.update(_descendants(node.id, graph))
                await _record_step(
                    session, execution.id, counter.take(), node, "skipped", None, None
                )
                continue

        schema = NODE_SCHEMAS.get(node.type)
        if schema is None:
            raise NodeExecutionError(f"unknown node type '{node.type}'")
        try:
            params = schema.params.model_validate(node.params).model_dump()
        except Exception as exc:
            await _record_step(
                session,
                execution.id,
                counter.take(),
                node,
                "failed",
                node.params,
                None,
                str(exc),
            )
            raise NodeExecutionError(f"node '{node.id}': {exc}") from exc

        resolved = expressions.resolve_params(params, context)

        # retry валидирован схемой узла; отсутствие retry → без повторов
        retry = RetryConfig.model_validate(params.get("retry") or {})
        result = await _run_node_with_retry(
            session, execution, node, worker_id, resolved, context, retry, counter
        )

        context["nodes"][node.id] = {"output": result}

        if node.type == IF_NODE_TYPE:
            branch = str(result.get("branch", "false"))
            if_branch[node.id] = branch
            # все узлы, достижимые только через невыбранный handle, — skipped
            for edge in graph.edges:
                if edge.source == node.id and edge.sourceHandle != branch:
                    skipped.update(_descendants(edge.target, graph))