"""Реестр обработчиков узлов.

handler(node_type, params, context) -> dict — выход узла, который кладётся
в context[node_id]["output"] и становится доступен другим узлам через
{{ nodes.<id>.output.<path> }}.

action_http и action_llm — заглушки до 4.B: возвращают {"error": ...},
и runner помечает такой шаг failed.
"""

from typing import Any

from app.engine.nodes.debug import handle_debug
from app.engine.nodes.http import handle_http
from app.engine.nodes.llm import handle_llm
from app.engine.nodes.logic_if import handle_logic_if
from app.engine.nodes.transform_set import handle_transform_set
from app.engine.nodes.trigger_manual import handle_trigger_manual

NodeHandler = "Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]"

HANDLERS: dict[str, Any] = {
    "trigger_manual": handle_trigger_manual,
    "transform_set": handle_transform_set,
    "debug": handle_debug,
    "logic_if": handle_logic_if,
    "action_http": handle_http,
    "action_llm": handle_llm,
}


def handle(node_type: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    handler = HANDLERS.get(node_type)
    if handler is None:
        return {"error": f"no handler for node type '{node_type}'"}
    result: dict[str, Any] = handler(params, context)
    return result