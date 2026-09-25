"""Ручной триггер: точка входа графа.

Реальные триггеры (webhook/cron/poll) появятся на этапе 5; здесь payload
пустой — runner подставляет его из Execution.trigger_payload, когда появится.
"""

from typing import Any


async def handle_trigger_manual(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    trigger = context.get("trigger", {})
    payload = trigger.get("payload", {}) if isinstance(trigger, dict) else {}
    return {"payload": payload}