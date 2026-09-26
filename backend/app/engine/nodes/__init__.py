"""Реестр обработчиков узлов.

Все обработчики async: action_http и action_llm выполняют ввод-вывод
(httpx, anthropic SDK), поэтому единый интерфейс — coroutine-функция.

handler(params, context) -> dict — выход узла, который кладётся в
context["nodes"][node_id]["output"] и доступен другим узлам через
{{ nodes.<id>.output.<path> }}.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.engine.nodes.debug import handle_debug
from app.engine.nodes.http import handle_http
from app.engine.nodes.llm import handle_llm
from app.engine.nodes.logic_if import handle_logic_if
from app.engine.nodes.transform_set import handle_transform_set
from app.engine.nodes.trigger_cron import handle_trigger_cron
from app.engine.nodes.trigger_manual import handle_trigger_manual
from app.engine.nodes.trigger_webhook import handle_trigger_webhook

NodeHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]

HANDLERS: dict[str, NodeHandler] = {
    "trigger_manual": handle_trigger_manual,
    "trigger_cron": handle_trigger_cron,
    "trigger_webhook": handle_trigger_webhook,
    "transform_set": handle_transform_set,
    "debug": handle_debug,
    "logic_if": handle_logic_if,
    "action_http": handle_http,
    "action_llm": handle_llm,
}


async def handle(
    node_type: str, params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    handler = HANDLERS.get(node_type)
    if handler is None:
        return {"error": f"no handler for node type '{node_type}'"}
    return await handler(params, context)