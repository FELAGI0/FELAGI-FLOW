"""LLM (Claude) — заглушка до 4.B.

Модель берётся из LLM_MODELS (см. DESIGN.md §1), реальный вызов anthropic SDK
с промптом и учётом usage — подэтап 4.B.
"""

from typing import Any


def handle_llm(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {"error": "not implemented yet: action_llm (planned for 4.B)"}