"""Резолвер выражений шаблонов воркфлоу.

Поддерживаемые формы:
    {{ nodes.<node_id>.output.<path> }}
    {{ trigger.payload.<path> }}

Где <path> — dot-path по JSON (foo.bar.0.baz).

Без eval/exec: собственный токенизатор, потому что вход — пользовательский
шаблон, а это trust boundary (DESIGN.md §4). Регулярками парсить не годится —
нужно различать «весь шаблон целиком одно выражение» (вернуть значение как
есть, сохранив тип) и «подстановка внутри строки» (вернуть строку).
"""

from typing import Any

OPEN = "{{"
CLOSE = "}}"
# защита от абсурдных выражений: путь глубже — почти наверняка ошибка
MAX_PATH_DEPTH = 32


class _Literal:
    """Сегмент шаблона, не являющийся выражением (текст между {{ }})."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


class _Expression:
    """Разобранное выражение {{ ... }}: корень + путь сегментов."""

    __slots__ = ("path", "raw", "root")

    def __init__(self, root: str, path: list[str], raw: str) -> None:
        self.root = root
        self.path = path
        self.raw = raw


_Token = _Literal | _Expression


def _parse(template: str) -> list[_Token] | None:
    """Токенизирует шаблон. None — если скобки не парны (шаблон считаем текстом)."""
    tokens: list[_Token] = []
    cursor = 0
    length = len(template)

    while cursor < length:
        start = template.find(OPEN, cursor)
        if start == -1:
            tokens.append(_Literal(template[cursor:]))
            break

        if start > cursor:
            tokens.append(_Literal(template[cursor:start]))

        end = template.find(CLOSE, start + len(OPEN))
        if end == -1:
            # незакрытая скобка — не выражение, весь остаток как текст
            tokens.append(_Literal(template[start:]))
            break

        inner = template[start + len(OPEN) : end].strip()
        expression = _parse_expression(inner)
        if expression is None:
            # содержимое не похоже на выражение — оставляем как текст дословно
            tokens.append(_Literal(template[start : end + len(CLOSE)]))
        else:
            tokens.append(expression)
        cursor = end + len(CLOSE)

    return tokens


def _parse_expression(inner: str) -> _Expression | None:
    parts = [part for part in inner.split(".") if part != ""]
    if len(parts) < 2:
        return None
    if len(parts) > MAX_PATH_DEPTH:
        return None
    root = parts[0]
    if root not in ("nodes", "trigger"):
        return None
    return _Expression(root=root, path=parts[1:], raw=inner)


def _lookup(expression: _Expression, context: dict[str, Any]) -> tuple[Any, bool]:
    """Идёт по dot-path. Возвращает (значение, найдено)."""
    node_id: object = expression.root
    if node_id == "nodes":
        if len(expression.path) < 2:
            return None, False
        node_id = expression.path[0]
        rest = expression.path[1:]
        scope: Any = context.get("nodes", {})
    else:  # trigger
        rest = expression.path
        scope = context.get("trigger", {})

    if not isinstance(scope, dict):
        return None, False

    current: Any = scope.get(str(node_id)) if expression.root == "nodes" else scope
    if current is None:
        return None, False

    for segment in rest:
        if isinstance(current, dict):
            if segment not in current:
                return None, False
            current = current[segment]
        elif isinstance(current, list):
            index = int(segment) if segment.lstrip("-").isdigit() else None
            if index is None or not (-len(current) <= index < len(current)):
                return None, False
            current = current[index]
        else:
            return None, False

    return current, True


def _render(value: Any) -> str:
    """Значение для строковой подстановки: объекты — через json.dumps."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    import json

    return json.dumps(value, ensure_ascii=False)


def resolve(template: str, context: dict[str, Any]) -> Any:
    """Подставляет выражения шаблона из контекста.

    - шаблон целиком "{{ ... }}" → значение как есть (int/bool/dict), без строки;
    - подстановка внутри строки → строка;
    - ненайденный путь → "" (не бросаем);
    - нет валидных выражений → шаблон как есть (проверено: type сохраняется).
    """
    if not isinstance(template, str):
        return template

    tokens = _parse(template)
    if tokens is None or not tokens:
        return template

    # целиком-выражение: вернуть значение с сохранением типа
    if len(tokens) == 1 and isinstance(tokens[0], _Expression):
        value, found = _lookup(tokens[0], context)
        return value if found else ""

    # смешанный шаблон: собрать строку
    pieces: list[str] = []
    for token in tokens:
        if isinstance(token, _Literal):
            pieces.append(token.text)
        else:
            value, found = _lookup(token, context)
            pieces.append(_render(value) if found else "")

    return "".join(pieces)


def resolve_params(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно резолвит все строковые значения в params (словари/списки — вглубь)."""
    resolved: dict[str, Any] = {}
    for key, value in params.items():
        resolved[key] = _resolve_value(value, context)
    return resolved


def _resolve_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return resolve(value, context)
    if isinstance(value, dict):
        return {k: _resolve_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, context) for item in value]
    return value