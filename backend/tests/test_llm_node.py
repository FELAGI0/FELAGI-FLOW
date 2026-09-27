"""Тесты LLM-узла: OpenAI-совместимый API (backend/app/engine/nodes/llm.py).

Мокаем AsyncOpenAI целиком — реальных сетевых вызовов нет. Настройки
(api_key, base_url, LLM_MODELS) подменяем точечно через monkeypatch.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx2
import openai
import pytest

from app.engine.nodes import llm
from app.shared.config import settings


def _fake_client(create: AsyncMock) -> MagicMock:
    """AsyncOpenAI(...) → клиент, чей chat.completions.create — заданный мок."""
    client = MagicMock()
    client.chat.completions.create = create
    return client


def _patch_client(monkeypatch: pytest.MonkeyPatch, create: AsyncMock) -> MagicMock:
    factory = MagicMock(return_value=_fake_client(create))
    monkeypatch.setattr(llm, "AsyncOpenAI", factory)
    return factory


def _response(
    *,
    content: str = "hello",
    model: str = "gpt-5.6-luna",
    finish_reason: str = "stop",
    prompt_tokens: int = 9,
    completion_tokens: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        model=model,
    )


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "http://127.0.0.1:4100/v1")
    monkeypatch.setattr(settings, "llm_models", '["gpt-5.6-luna"]')


async def test_successful_call(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value=_response(content="Hi", completion_tokens=1))
    factory = _patch_client(monkeypatch, create)

    result = await llm.handle_llm({"prompt": "say hi", "model": "gpt-5.6-luna"}, {})

    assert result == {
        "text": "Hi",
        "usage": {"input_tokens": 9, "output_tokens": 1},
        "model": "gpt-5.6-luna",
        "stop_reason": "stop",
    }
    # клиент собран с base_url и ключом из настроек
    kwargs = factory.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["base_url"] == "http://127.0.0.1:4100/v1"
    # параметры запроса: модель, max_tokens, одно user-сообщение
    sent = create.call_args.kwargs
    assert sent["model"] == "gpt-5.6-luna"
    assert sent["max_tokens"] == 1024
    assert sent["messages"] == [{"role": "user", "content": "say hi"}]


async def test_api_error_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # openai 3.x типизирует APIError против своего форка httpx2, не httpx
    error = openai.APIError("boom", request=httpx2.Request("POST", "http://x"), body=None)
    create = AsyncMock(side_effect=error)
    _patch_client(monkeypatch, create)

    result = await llm.handle_llm({"prompt": "hi", "model": "gpt-5.6-luna"}, {})

    assert "error" in result
    assert "boom" in result["error"]


async def test_model_not_in_llm_models(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock()
    factory = _patch_client(monkeypatch, create)

    result = await llm.handle_llm({"prompt": "hi", "model": "some-other-model"}, {})

    assert "error" in result
    assert "some-other-model" in result["error"]
    # до сети не дошли
    create.assert_not_awaited()
    factory.assert_not_called()


async def test_empty_prompt_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock()
    factory = _patch_client(monkeypatch, create)

    result = await llm.handle_llm({"model": "gpt-5.6-luna"}, {})

    assert "error" in result
    create.assert_not_awaited()
    factory.assert_not_called()


async def test_missing_api_key_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "")
    create = AsyncMock()
    factory = _patch_client(monkeypatch, create)

    result = await llm.handle_llm({"prompt": "hi", "model": "gpt-5.6-luna"}, {})

    assert "error" in result
    assert "LLM_API_KEY" in result["error"]
    factory.assert_not_called()


async def test_system_prompt_sent_as_first_message(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value=_response())
    _patch_client(monkeypatch, create)

    await llm.handle_llm(
        {"prompt": "hi", "model": "gpt-5.6-luna", "system_prompt": "be terse"}, {}
    )

    sent = create.call_args.kwargs
    assert sent["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ]


async def test_without_system_prompt_only_user_message(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value=_response())
    _patch_client(monkeypatch, create)

    await llm.handle_llm({"prompt": "hi", "model": "gpt-5.6-luna"}, {})

    sent = create.call_args.kwargs
    assert sent["messages"] == [{"role": "user", "content": "hi"}]


async def test_model_defaults_to_first_of_llm_models(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value=_response())
    _patch_client(monkeypatch, create)

    # model не задан → берётся первая из LLM_MODELS
    await llm.handle_llm({"prompt": "hi"}, {})

    assert create.call_args.kwargs["model"] == "gpt-5.6-luna"


async def test_temperature_passed_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value=_response())
    _patch_client(monkeypatch, create)

    await llm.handle_llm({"prompt": "hi", "model": "gpt-5.6-luna", "temperature": 0.3}, {})

    assert create.call_args.kwargs["temperature"] == pytest.approx(0.3)


async def test_generic_exception_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(side_effect=RuntimeError("connection reset"))
    _patch_client(monkeypatch, create)

    result: dict[str, Any] = await llm.handle_llm({"prompt": "hi", "model": "gpt-5.6-luna"}, {})

    assert "error" in result
    assert "connection reset" in result["error"]