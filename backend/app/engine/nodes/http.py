"""HTTP Request — заглушка до 4.B.

Возвращает error, runner пометит шаг failed. Реальная реализация (вызов
внешнего API с таймаутом, разбором ответа и idempotency-key) — подэтап 4.B.
"""

from typing import Any


def handle_http(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {"error": "not implemented yet: action_http (planned for 4.B)"}