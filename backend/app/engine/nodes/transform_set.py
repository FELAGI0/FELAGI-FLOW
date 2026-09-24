"""Set: формирует объект из перечисленных полей.

params.fields — список {name, value}. Значение резолвится runner'ом из
context ДО вызова handler'а (см. runner._resolve_params), поэтому здесь
work уже с готовыми значениями.
"""

from typing import Any


def handle_transform_set(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    fields = params.get("fields", [])
    if not isinstance(fields, list):
        return {"error": "fields must be a list"}

    output: dict[str, Any] = {}
    for index, field in enumerate(fields):
        if not isinstance(field, dict) or "name" not in field:
            return {"error": f"fields[{index}] must be an object with 'name'"}
        output[str(field["name"])] = field.get("value")

    return output