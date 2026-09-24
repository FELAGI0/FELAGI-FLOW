"""If: сравнение двух значений, выбор ветки true/false.

Семантика несовпадения типов (DESIGN.md §4): узел НЕ падает — «невыполнимое»
сравнение даёт branch='false'. Ошибки сравнения возвращаются в 'warning',
runner пишет их в execution_steps.warnings, не трогая статус шага.
"""

from typing import Any


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _compare(left: Any, op: str, right: Any) -> tuple[bool, str | None]:
    """Возвращает (результат, warning)."""
    if op == "empty":
        return _is_empty(left), None
    if op == "not_empty":
        return not _is_empty(left), None

    if op == "=":
        return left == right, None
    if op == "!=":
        return left != right, None

    if op == "contains":
        if isinstance(left, str):
            return (str(right) in left), None
        if isinstance(left, list):
            return (right in left), None
        return False, f"'contains' не применим к {type(left).__name__} (null/число/объект)"

    if op in (">", "<"):
        left_num = _as_number(left)
        right_num = _as_number(right)
        if left_num is None or right_num is None:
            return False, f"'{op}' требует чисел, получено {type(left).__name__}"
        return (left_num > right_num if op == ">" else left_num < right_num), None

    return False, f"unknown operator '{op}'"


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def handle_logic_if(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    left = params.get("left")
    op = str(params.get("op", "="))
    right = params.get("right")

    result, warning = _compare(left, op, right)
    output: dict[str, Any] = {
        "branch": "true" if result else "false",
        "left": left,
        "right": right,
        "op": op,
    }
    if warning is not None:
        output["warning"] = warning
    return output