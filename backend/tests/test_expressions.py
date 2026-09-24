"""Тесты резолвера выражений — чистая логика без БД и FastAPI."""

import json

from app.engine.expressions import resolve, resolve_params


def test_node_output() -> None:
    ctx = {
        "nodes": {"a": {"output": {"text": "hello"}}},
        "trigger": {},
    }
    assert resolve("{{ nodes.a.output.text }}", ctx) == "hello"


def test_trigger_payload() -> None:
    ctx = {"nodes": {}, "trigger": {"payload": {"user_id": 42}}}
    assert resolve("{{ trigger.payload.user_id }}", ctx) == 42


def test_nested_array_access() -> None:
    ctx = {
        "nodes": {"items": {"output": [{"name": "Alice"}, {"name": "Bob"}]}},
        "trigger": {},
    }
    # path содержит индекс: items.output.0.name
    assert resolve("{{ nodes.items.output.0.name }}", ctx) == "Alice"


def test_multiple_expressions_in_string() -> None:
    ctx = {"nodes": {"x": {"output": "world"}, "y": {"output": "!"}}, "trigger": {}}
    assert resolve("Hello {{ nodes.x.output }}, {{ nodes.y.output }}", ctx) == "Hello world, !"


def test_missing_path_returns_empty() -> None:
    ctx: dict[str, object] = {"nodes": {}, "trigger": {}}
    assert resolve("{{ nodes.missing.foo.bar }}", ctx) == ""


def test_object_substituted_as_json() -> None:
    ctx = {
        "nodes": {"obj": {"output": {"a": 1, "b": "two"}}},
        "trigger": {},
    }
    result = resolve("prefix {{ nodes.obj.output }} suffix", ctx)
    assert isinstance(result, str)
    assert result.startswith("prefix ") and result.endswith(" suffix")
    # объект должен быть сериализован через json.dumps (не repr, не str):
    # вырезаем середину по границам префикса/суффикса, а не по пробелам
    inner = result[len("prefix ") : -len(" suffix")]
    assert json.loads(inner) == {"a": 1, "b": "two"}


def test_whole_expression_returns_value_not_string() -> None:
    """Целиком-выражение возвращает значение с сохранением типа, а не строку."""
    ctx_num: dict[str, object] = {"nodes": {"a": {"output": {"n": 3}}}, "trigger": {}}
    ctx_bool: dict[str, object] = {"nodes": {"b": {"output": {"flag": True}}}, "trigger": {}}
    assert resolve("{{ nodes.a.output.n }}", ctx_num) == 3
    assert resolve("{{ nodes.b.output.flag }}", ctx_bool) is True


def test_no_valid_template_returns_as_is() -> None:
    assert resolve("just plain text", {}) == "just plain text"


def test_resolve_params_recursively() -> None:

    params = {
        "message": "Hello {{ nodes.a.output.greeting }}, value={{ nodes.b.output.count }}",
        "settings": {"level": "info", "threshold": "{{ nodes.c.output.min }}"},
        "tags": ["tag1", "{{ nodes.d.output.tag }}"],
    }
    ctx = {
        "nodes": {
            "a": {"output": {"greeting": "World"}},
            "b": {"output": {"count": 5}},
            "c": {"output": {"min": 10}},
            "d": {"output": {"tag": "live"}},
        },
        "trigger": {},
    }
    result = resolve_params(params, ctx)
    assert result["message"] == "Hello World, value=5"
    # шаблон целиком-выражение сохраняет тип: min — число 10, а не строка "10"
    assert result["settings"]["threshold"] == 10
    assert result["tags"] == ["tag1", "live"]