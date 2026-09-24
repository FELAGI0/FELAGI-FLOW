"""Движок выполнения: топологический обход графа с ветвлением If.

Запуск идёт строго против пиннутой версии графа. Узлы выполняются в
топологическом порядке (Kahn); невыбранные ветки If помечаются skipped
вместе со всеми потомками — merge в MVP отсутствует (DESIGN.md §4).
"""

import time
import uuid
from collections import defaultdict, deque
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import expressions
from app.engine.node_schemas import NODE_SCHEMAS
from app.engine.nodes import handle
from app.engine.queue import heartbeat
from app.shared.models import Execution, ExecutionStep, WorkflowVersion
from app.shared.schemas.workflow import Graph, Node

IF_NODE_TYPE = "logic_if"


class NodeExecutionError(Exception):
    """Узел вернул ошибку или упал — запуск останавливается."""


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
    node: Node,
    status: str,
    input_params: dict[str, Any] | None,
    output: dict[str, Any] | None,
    error: str | None = None,
    warnings: list[str] | None = None,
    duration_ms: int | None = None,
) -> None:
    session.add(
        ExecutionStep(
            execution_id=execution_id,
            node_id=node.id,
            node_type=node.type,
            status=status,
            input=input_params,
            output=output,
            error=error,
            warnings=warnings or [],
            duration_ms=duration_ms,
        )
    )
    await session.flush()


def load_graph(version: WorkflowVersion) -> Graph:
    return Graph.model_validate(version.graph)


async def run_execution(
    session: AsyncSession,
    execution: Execution,
    version: WorkflowVersion,
    worker_id: str,
) -> None:
    """Выполняет граф пиннутой версии. Бросает NodeExecutionError при падении узла.

    Коммит — за вызывающим (worker loop): здесь только flush, чтобы шаги
    фиксировались одной транзакцией с обновлением статуса execution.
    """
    graph = load_graph(version)
    order = topological_order(graph)

    context: dict[str, Any] = {
        "nodes": {},
        "trigger": {"payload": execution.trigger_payload or {}},
    }

    skipped: set[str] = set()
    if_branch: dict[str, str] = {}  # node_id If → выбранная ветка

    for node in order:
        # heartbeat перед каждым узлом: долгий граф не должен считаться зависшим
        await heartbeat(session, execution.id, worker_id)

        if node.id in skipped:
            await _record_step(session, execution.id, node, "skipped", None, None)
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
                await _record_step(session, execution.id, node, "skipped", None, None)
                continue

        schema = NODE_SCHEMAS.get(node.type)
        if schema is None:
            raise NodeExecutionError(f"unknown node type '{node.type}'")
        try:
            params = schema.params.model_validate(node.params).model_dump()
        except Exception as exc:
            await _record_step(
                session, execution.id, node, "failed", node.params, None, str(exc)
            )
            raise NodeExecutionError(f"node '{node.id}': {exc}") from exc

        resolved = expressions.resolve_params(params, context)

        started = time.perf_counter()
        result = handle(node.type, resolved, context)
        duration_ms = int((time.perf_counter() - started) * 1000)

        if "error" in result:
            await _record_step(
                session,
                execution.id,
                node,
                "failed",
                resolved,
                result,
                str(result["error"]),
                duration_ms=duration_ms,
            )
            raise NodeExecutionError(f"node '{node.id}': {result['error']}")

        warnings = [result["warning"]] if "warning" in result else []
        await _record_step(
            session,
            execution.id,
            node,
            "succeeded",
            resolved,
            result,
            warnings=warnings,
            duration_ms=duration_ms,
        )
        context["nodes"][node.id] = {"output": result}

        if node.type == IF_NODE_TYPE:
            branch = str(result.get("branch", "false"))
            if_branch[node.id] = branch
            # все узлы, достижимые только через невыбранный handle, — skipped
            for edge in graph.edges:
                if edge.source == node.id and edge.sourceHandle != branch:
                    skipped.update(_descendants(edge.target, graph))