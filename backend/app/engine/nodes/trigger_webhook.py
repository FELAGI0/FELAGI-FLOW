"""Webhook-триггер: точка входа запуска от внешнего HTTP-запроса.

Выход по DESIGN.md §4 — `headers`, `query`, `body`. Значения приходят из
trigger_payload, который сформировал приёмник вебхука (/hooks/{token}).
"""

from typing import Any


async def handle_trigger_webhook(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    trigger = context.get("trigger", {})
    payload = trigger.get("payload", {}) if isinstance(trigger, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "headers": payload.get("headers", {}),
        "query": payload.get("query", {}),
        "body": payload.get("body"),
        "method": payload.get("method"),
    }