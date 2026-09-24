"""Каталог типов узлов: метаданные + Pydantic-модель параметров каждого типа.

NODE_SCHEMAS — единственный источник истины для палитры редактора
(через GET /api/node-types) и для валидации графа (graph_validator).
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


class TriggerManualParams(BaseModel):
    """Ручной запуск — параметров нет."""


class SetField(BaseModel):
    name: str
    value: str


class TransformSetParams(BaseModel):
    fields: list[SetField] = Field(default_factory=list)


class DebugParams(BaseModel):
    level: Literal["info", "warn", "error"] = "info"
    message: str


class LogicIfParams(BaseModel):
    left: str
    op: Literal["=", "!=", "contains", ">", "<", "empty", "not_empty"]
    right: str | None = None


class HttpParams(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class LlmParams(BaseModel):
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