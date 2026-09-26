"""Валидация графа воркфлоу перед сохранением версии и публикацией.

Возвращает список человекочитаемых ошибок; пустой список — граф корректен.
mvp-ограничения (DESIGN.md §4): ровно один триггер, ветвление только через If,
merge отсутствует — ветки If не сходятся.
"""

from collections import defaultdict, deque

from pydantic import ValidationError

from app.engine.cron import is_valid_cron, is_valid_timezone
from app.engine.node_schemas import DEFAULT_TIMEZONE, NodeSchema
from app.shared.schemas.workflow import Edge, Graph, Node

IF_NODE_TYPE = "logic_if"
IF_HANDLES = ("true", "false")
CRON_NODE_TYPE = "trigger_cron"
WEBHOOK_NODE_TYPE = "trigger_webhook"


def validate_graph(graph: Graph, node_schemas: dict[str, NodeSchema]) -> list[str]:
    errors: list[str] = []
    nodes = graph.nodes
    edges = graph.edges

    ids = [n.id for n in nodes]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"duplicate node id(s): {', '.join(dupes)}")

    by_id = {n.id: n for n in nodes}

    for node in nodes:
        if node.type not in node_schemas:
            errors.append(f"node '{node.id}': unknown type '{node.type}'")

    triggers = [n for n in nodes if n.type.startswith("trigger_")]
    if not triggers:
        errors.append("graph must contain exactly one trigger node (found none)")
    elif len(triggers) > 1:
        errors.append(f"graph must contain exactly one trigger node (found {len(triggers)})")

    for edge in edges:
        if edge.source not in by_id:
            errors.append(f"edge '{edge.id}': source node '{edge.source}' does not exist")
        if edge.target not in by_id:
            errors.append(f"edge '{edge.id}': target node '{edge.target}' does not exist")

    incoming: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        if edge.target in by_id:
            incoming[edge.target].append(edge)

    for node in nodes:
        count = len(incoming[node.id])
        if node.type.startswith("trigger_"):
            if count:
                errors.append(f"trigger node '{node.id}' must not have incoming edges")
        elif count == 0:
            errors.append(f"node '{node.id}' has no incoming edge")
        elif count > 1:
            errors.append(
                f"node '{node.id}' has {count} incoming edges (merge not supported in MVP)"
            )

    for node in nodes:
        if node.type != IF_NODE_TYPE:
            continue
        outgoing = [e for e in edges if e.source == node.id]
        handles = {e.sourceHandle for e in outgoing}
        for edge in outgoing:
            if edge.sourceHandle not in IF_HANDLES:
                errors.append(
                    f"If node '{node.id}': edge '{edge.id}' must set "
                    "sourceHandle 'true' or 'false'"
                )
        for handle in IF_HANDLES:
            if handle not in handles:
                errors.append(f"If node '{node.id}': missing '{handle}' branch")

    unique_ids = list(by_id)
    indegree: dict[str, int] = dict.fromkeys(unique_ids, 0)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.source in by_id and edge.target in by_id:
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1
    queue = deque([node_id for node_id in unique_ids if indegree[node_id] == 0])
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for neighbour in adjacency[current]:
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                queue.append(neighbour)
    if visited != len(unique_ids):
        errors.append("graph contains a cycle")

    for node in nodes:
        schema = node_schemas.get(node.type)
        if schema is None:
            continue
        try:
            schema.params.model_validate(node.params)
        except ValidationError as exc:
            for detail in exc.errors():
                location = ".".join(str(part) for part in detail["loc"]) or "(params)"
                errors.append(f"node '{node.id}': invalid parameter '{location}' — {detail['msg']}")

    # cron/webhook: схема проверяет типы, но не семантику (валидность выражения и
    # зоны, непустоту списка методов) — это отдельные проверки ниже. Выполняются
    # только если базовые типы прошли, иначе params.get вернул бы не то, что ждём
    for node in nodes:
        if node.type == CRON_NODE_TYPE:
            errors.extend(_check_cron_node(node))
        elif node.type == WEBHOOK_NODE_TYPE:
            errors.extend(_check_webhook_node(node))

    return errors


def _check_cron_node(node: Node) -> list[str]:
    """cron_expr валиден по croniter, timezone существует в базе зон."""
    errors: list[str] = []
    cron_expr = node.params.get("cron_expr")
    if isinstance(cron_expr, str) and cron_expr:
        if not is_valid_cron(cron_expr):
            errors.append(f"node '{node.id}': invalid cron_expr '{cron_expr}'")
    elif cron_expr is not None and not isinstance(cron_expr, str):
        errors.append(f"node '{node.id}': cron_expr must be a string")

    timezone = node.params.get("timezone", DEFAULT_TIMEZONE)
    if not isinstance(timezone, str) or not is_valid_timezone(timezone):
        errors.append(f"node '{node.id}': unknown timezone '{timezone}'")
    return errors


def _check_webhook_node(node: Node) -> list[str]:
    """methods — непустой список из GET/POST."""
    errors: list[str] = []
    methods = node.params.get("methods")
    if methods is None:
        # поле необязательное: дефолт схемы = ["POST"]
        return errors
    if not isinstance(methods, list) or not methods:
        errors.append(f"node '{node.id}': methods must be a non-empty list")
        return errors
    for method in methods:
        if method not in ("GET", "POST"):
            errors.append(f"node '{node.id}': unsupported method '{method}'")
    return errors