"""LLM: вызов OpenAI-совместимого API с промптом и учётом usage.

Ключ и base_url берутся из настроек (LLM_API_KEY / LLM_BASE_URL; этап 6 заменит
их на credentials воркспейса). Модель валидируется против LLM_MODELS, если
список задан.
"""

from typing import Any

import openai
from openai import AsyncOpenAI

from app.shared.config import settings

DEFAULT_TIMEOUT_SECONDS = 60.0


async def handle_llm(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    prompt = params.get("prompt")
    if not prompt:
        return {"error": "llm node requires 'prompt'"}

    model = str(params.get("model", ""))
    available = settings.llm_models_list
    # дефолт - первая из LLM_MODELS; только затем проверяем, что модель разрешена
    if not model:
        model = available[0] if available else ""
    if available and model not in available:
        return {
            "error": f"model '{model}' not in LLM_MODELS {available}",
        }

    api_key = settings.llm_api_key
    if not api_key:
        return {"error": "LLM_API_KEY is not configured"}

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=settings.llm_base_url,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )

    # system_prompt (если задан) идёт отдельным сообщением перед пользовательским
    messages: list[dict[str, str]] = []
    if params.get("system_prompt"):
        messages.append({"role": "system", "content": str(params["system_prompt"])})
    messages.append({"role": "user", "content": str(prompt)})

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": int(params.get("max_tokens", 1024)),
    }
    if params.get("temperature") is not None:
        kwargs["temperature"] = float(params["temperature"])

    try:
        response = await client.chat.completions.create(**kwargs)
    except openai.APIError as exc:
        return {"error": f"llm API error: {exc}"}
    except Exception as exc:
        return {"error": f"llm request failed: {exc}"}

    choice = response.choices[0]
    content = choice.message.content
    usage = response.usage
    return {
        "text": content or "",
        "usage": {
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
        },
        "model": response.model,
        "stop_reason": choice.finish_reason,
    }