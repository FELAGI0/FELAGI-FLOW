"""LLM (Claude): вызов Anthropic с промптом и учётом usage.

Ключ берётся из ANTHROPIC_API_KEY (этап 6 заменит на credentials воркспейса).
Модель валидируется против LLM_MODELS из настроек, если список задан.
"""

from typing import Any

import anthropic

from app.shared.config import settings

DEFAULT_TIMEOUT_SECONDS = 60.0


def _extract_text(message: anthropic.types.Message) -> str:
    """Собирает текстовые блоки ответа в одну строку."""
    parts: list[str] = []
    for block in message.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


async def handle_llm(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    prompt = params.get("prompt")
    if not prompt:
        return {"error": "llm node requires 'prompt'"}

    model = str(params.get("model", ""))
    available = settings.llm_models_list
    if available and model not in available:
        return {
            "error": f"model '{model}' not in LLM_MODELS {available}",
        }
    if not model:
        model = available[0] if available else ""

    api_key = settings.anthropic_api_key
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY is not configured"}

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS)

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": int(params.get("max_tokens", 1024)),
        "messages": [{"role": "user", "content": str(prompt)}],
    }
    if params.get("temperature") is not None:
        kwargs["temperature"] = float(params["temperature"])
    if params.get("system_prompt"):
        kwargs["system"] = str(params["system_prompt"])

    try:
        message = await client.messages.create(**kwargs)
    except anthropic.APIError as exc:
        return {"error": f"anthropic API error: {exc}"}
    except Exception as exc:
        return {"error": f"anthropic request failed: {exc}"}

    return {
        "text": _extract_text(message),
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
        "model": message.model,
        "stop_reason": message.stop_reason,
    }