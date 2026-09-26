"""Cron-триггер: точка входа запуска по расписанию.

Выход по DESIGN.md §4 — `scheduled_time`. Значение берём из trigger_payload
(планировщик кладёт туда момент срабатывания), а не пересчитываем из cron_expr:
runner не должен зависеть от текущего времени, иначе один и тот же запуск,
перезапущенный вручную, дал бы другой результат.

Обработчик общий для cron/webhook/manual по смыслу: узел-триггер лишь
прокидывает наружу то, что пришло в запуск.
"""

from typing import Any


async def handle_trigger_cron(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    trigger = context.get("trigger", {})
    payload = trigger.get("payload", {}) if isinstance(trigger, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "scheduled_time": payload.get("scheduled_time"),
        "payload": payload,
    }