"""Каталог типов узлов: метаданные + Pydantic-модель параметров каждого типа.

NODE_SCHEMAS — единственный источник истины для палитры редактора
(через GET /api/node-types) и для валидации графа (graph_validator).
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


class RetryConfig(BaseModel):
    """Политика повторов узла (DESIGN.md §4): общая для всех типов узлов.

    max_retries — сколько ПОВТОРОВ после первой попытки (0 = без повторов,
    всего попыток max_retries + 1).
    """

    max_retries: int = Field(default=0, ge=0, le=5)
    backoff: Literal["fixed", "exponential"] = "exponential"
    base_s: float = Field(default=1.0, gt=0, le=60)


class BaseNodeParams(BaseModel):
    """Общие параметры всех узлов: retry-политика и подпись на канвасе.

    Наследуется конкретными params-моделями, поэтому JSON-Schema каждого узла
    (GET /api/node-types) содержит retry/label наравне с его полями — на этом
    строится и валидация графа, и секция Retry в панели параметров.
    """

    retry: RetryConfig | None = None
    label: str | None = None


class TriggerManualParams(BaseNodeParams):
    """Ручной запуск — своих параметров нет."""


class SetField(BaseModel):
    name: str
    value: str


class TransformSetParams(BaseNodeParams):
    fields: list[SetField] = Field(default_factory=list)


class DebugParams(BaseNodeParams):
    level: Literal["info", "warn", "error"] = "info"
    message: str


class LogicIfParams(BaseNodeParams):
    left: str
    op: Literal["=", "!=", "contains", ">", "<", "empty", "not_empty"]
    right: str | None = None


class KeyValue(BaseModel):
    name: str
    value: str


class HttpParams(BaseNodeParams):
    """Параметры HTTP-узла по DESIGN.md §4: headers[]/query[] списками,
    auth — через credential (этап 6), timeout_s — таймаут запроса."""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str
    headers: list[KeyValue] = Field(default_factory=list)
    query: list[KeyValue] = Field(default_factory=list)
    body: dict[str, Any] | None = None
    auth: Literal["none", "basic", "bearer"] = "none"
    credential_id: str | None = None
    timeout_s: float = Field(default=30.0, gt=0)


class LlmParams(BaseNodeParams):
    model: str
    system_prompt: str | None = None
    prompt: str
    max_tokens: int = Field(default=1024, gt=0)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


@dataclass(frozen=True)
class NodeSchema:
    label: str
    category: str
    params: type[BaseModel]
    outputs: list[str]


NODE_SCHEMAS: dict[str, NodeSchema] = {
    "trigger_manual": NodeSchema("Manual Trigger", "trigger", TriggerManualParams, ["default"]),
    "transform_set": NodeSchema("Set", "transform", TransformSetParams, ["default"]),
    "debug": NodeSchema("Debug", "debug", DebugParams, ["default"]),
    "logic_if": NodeSchema("If", "logic", LogicIfParams, ["true", "false"]),
    "action_http": NodeSchema("HTTP Request", "action", HttpParams, ["default"]),
    "action_llm": NodeSchema("LLM (Claude)", "action", LlmParams, ["default"]),
}