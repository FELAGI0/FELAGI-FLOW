"""Debug: пропускает сообщение через граф, ничего не меняя.

Полезен для наблюдения промежуточных значений в истории запусков.
"""

from typing import Any


async def handle_debug(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    message = params.get("message")
    if message is None:
        return {"error": "debug node requires 'message'"}
    return {"level": params.get("level", "info"), "message": message}