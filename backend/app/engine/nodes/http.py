"""HTTP Request: вызов внешнего API с таймаутом и разбором ответа.

auth через credentials появится на этапе 6 (там Fernet-шифрование и
интеграции). До этого auth передаётся как none, а наличие credential_id
явно сигнализируется warning'ом — не молчаливой пустотой, чтобы пользователь
видел, что авторизация не применилась.
"""

import time
from typing import Any

import httpx

# ответы больше этого не имеет смысла класть в output шага (JSONB, история)
MAX_BODY_CHARS = 100_000
DEFAULT_TIMEOUT_SECONDS = 30.0


def _pairs_to_dict(pairs: Any) -> dict[str, str]:
    """list[{name, value}] → dict. Терпимо к кривым элементам."""
    result: dict[str, str] = {}
    if not isinstance(pairs, list):
        return result
    for item in pairs:
        if isinstance(item, dict) and "name" in item:
            result[str(item["name"])] = str(item.get("value", ""))
    return result


def _truncate(text: str) -> str:
    if len(text) <= MAX_BODY_CHARS:
        return text
    return text[:MAX_BODY_CHARS] + f"... [truncated, {len(text)} chars total]"


def _is_json_response(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return "json" in content_type.lower()


async def handle_http(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    method = str(params.get("method", "GET")).upper()
    url = params.get("url")
    if not url:
        return {"error": "http node requires 'url'"}

    headers = _pairs_to_dict(params.get("headers"))
    query = _pairs_to_dict(params.get("query"))
    body = params.get("body")

    # credentials (этап 6): сейчас не реализованы — предупреждаем явно
    warnings: list[str] = []
    credential_id = params.get("credential_id")
    if credential_id:
        warnings.append("credentials not implemented yet: auth skipped (planned for stage 6)")

    auth_type = params.get("auth", "none")
    if auth_type and auth_type != "none":
        warnings.append(f"auth '{auth_type}' ignored: credentials not implemented yet")

    timeout = float(params.get("timeout_s", DEFAULT_TIMEOUT_SECONDS))

    request_kwargs: dict[str, Any] = {"headers": headers, "params": query}
    if body is not None and method in ("POST", "PUT", "PATCH"):
        if isinstance(body, dict):
            request_kwargs["json"] = body
        else:
            request_kwargs["content"] = str(body)

    # transport инжектируется через context только в тестах (httpx.MockTransport);
    # в рантайме context['http_transport'] отсутствует — обычный сетевой клиент
    transport = context.get("http_transport")
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.request(method, str(url), **request_kwargs)
    except httpx.TimeoutException:
        return {"error": f"request to {url} timed out after {timeout}s"}
    except httpx.HTTPError as exc:
        return {"error": f"request to {url} failed: {exc}"}
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if _is_json_response(response):
        try:
            parsed_body: Any = response.json()
        except ValueError:
            parsed_body = _truncate(response.text)
    else:
        parsed_body = _truncate(response.text)

    output: dict[str, Any] = {
        "status": response.status_code,
        "headers": dict(response.headers),
        "body": parsed_body,
        "elapsed_ms": elapsed_ms,
    }
    if warnings:
        output["warning"] = "; ".join(warnings)
    return output