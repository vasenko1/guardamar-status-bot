"""Bounded OpenRouter fallback for Gemini structured requests."""

import json
import urllib.parse
from typing import Any, Dict, List, Optional

from ._transport import BoundedFetchError, fetch_bounded


MODEL = "openai/gpt-4.1-mini"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
API_HOST = "openrouter.ai"
REQUEST_TIMEOUT_SECONDS = 30
RESPONSE_LIMIT_BYTES = 100_000


class OpenRouterError(RuntimeError):
    """An operator-safe OpenRouter protocol or validation failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID",
        status: Optional[int] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = code
        self.server_status = status
        self.safe_description = description


def _is_openrouter_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == API_HOST


_TRANSPORT_DESCRIPTIONS = {
    "REDIRECT": "OpenRouter перенаправил запрос на другой сайт",
    "CONTENT-TYPE": "OpenRouter вернул ответ не в формате JSON",
    "TIMEOUT": "OpenRouter не ответил до истечения тайм-аута",
    "NETWORK": "не удалось установить соединение с OpenRouter",
    "TOO-LARGE": "ответ OpenRouter превысил допустимый размер",
}


def _content_from_parts(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = []
    for part in parts:
        text = part.get("text")
        if isinstance(text, str):
            content.append({"type": "text", "text": text})
            continue
        inline = part.get("inlineData")
        if not isinstance(inline, dict):
            raise OpenRouterError(
                "Unsupported OpenRouter input part",
                code="INPUT",
                description="резервная модель получила неподдерживаемые данные",
            )
        mime_type = inline.get("mimeType")
        encoded = inline.get("data")
        if not isinstance(mime_type, str) or not isinstance(encoded, str):
            raise OpenRouterError(
                "Invalid OpenRouter media input",
                code="INPUT",
                description="данные для резервной модели имеют неверный формат",
            )
        data_url = f"data:{mime_type};base64,{encoded}"
        if mime_type.startswith("image/"):
            content.append({
                "type": "image_url",
                "image_url": {"url": data_url},
            })
        elif mime_type == "application/pdf":
            content.append({
                "type": "file",
                "file": {
                    "filename": "municipal-agenda.pdf",
                    "file_data": data_url,
                },
            })
        else:
            raise OpenRouterError(
                "Unsupported OpenRouter media type",
                code="INPUT",
                description="формат файла не поддерживается резервной моделью",
            )
    if not content:
        raise OpenRouterError(
            "Empty OpenRouter input",
            code="INPUT",
            description="резервная модель не получила входных данных",
        )
    return content


def request_json(
    api_key: str,
    parts: List[Dict[str, Any]],
    schema: Optional[Dict[str, Any]],
    max_output_tokens: int,
) -> Dict[str, Any]:
    """Return one structured response from the pinned non-Google fallback."""

    if not api_key or any(character in api_key for character in "\r\n"):
        raise OpenRouterError(
            "OpenRouter configuration is invalid",
            code="CONFIG",
            description="ключ OpenRouter отсутствует или имеет неверный формат",
        )
    body_data: Dict[str, Any] = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": _content_from_parts(parts),
        }],
        "max_tokens": max_output_tokens,
        "temperature": 0,
        "provider": {"require_parameters": True},
    }
    if schema is not None:
        body_data["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "guardamar_result",
                "strict": True,
                "schema": schema,
            },
        }
    else:
        body_data["response_format"] = {"type": "json_object"}
    try:
        payload, _, _ = fetch_bounded(
            ENDPOINT,
            is_allowed_url=_is_openrouter_url,
            accepted_types=frozenset({"application/json"}),
            limit_bytes=RESPONSE_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "GuardamarMorningDigest/0.12",
            },
            method="POST",
            data=json.dumps(body_data, ensure_ascii=False).encode("utf-8"),
        )
    except BoundedFetchError as exc:
        raise OpenRouterError(
            f"OpenRouter request failed: {exc.code}",
            code=exc.code,
            status=exc.status,
            description=(
                f"OpenRouter вернул HTTP {exc.status}"
                if exc.status is not None
                else _TRANSPORT_DESCRIPTIONS.get(exc.code)
            ),
        ) from exc
    try:
        response_data = json.loads(payload.decode("utf-8"))
        text = response_data["choices"][0]["message"]["content"]
        result = json.loads(text)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise OpenRouterError(
            "OpenRouter returned an invalid response",
            code="INVALID-RESPONSE",
            description="OpenRouter вернул некорректный JSON-ответ",
        ) from exc
    if not isinstance(result, dict):
        raise OpenRouterError(
            "OpenRouter returned an invalid result",
            code="INVALID-STRUCTURE",
            description="структура результата OpenRouter некорректна",
        )
    return result
