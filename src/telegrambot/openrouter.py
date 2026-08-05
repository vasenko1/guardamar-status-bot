"""Bounded OpenRouter fallback for Gemini structured requests."""

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


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


class _OpenRouterRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if not _is_openrouter_url(new_url):
            raise OpenRouterError(
                "OpenRouter redirected outside its API host",
                code="REDIRECT",
                description="OpenRouter перенаправил запрос на другой сайт",
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


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


def _http_error(exc: urllib.error.HTTPError) -> OpenRouterError:
    return OpenRouterError(
        f"OpenRouter returned HTTP {exc.code}",
        code=f"HTTP-{exc.code}",
        status=exc.code,
        description=f"OpenRouter вернул HTTP {exc.code}",
    )


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
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body_data, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GuardamarMorningDigest/0.12",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_OpenRouterRedirectHandler())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if not _is_openrouter_url(response.geturl()):
                raise OpenRouterError(
                    "OpenRouter returned an unexpected response URL",
                    code="REDIRECT",
                    description="получен недопустимый адрес ответа OpenRouter",
                )
            if response.headers.get_content_type() != "application/json":
                raise OpenRouterError(
                    "OpenRouter returned an unexpected content type",
                    code="CONTENT-TYPE",
                    description="OpenRouter вернул ответ не в формате JSON",
                )
            payload = response.read(RESPONSE_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or (
            isinstance(exc, urllib.error.URLError)
            and isinstance(exc.reason, (TimeoutError, socket.timeout))
        )
        raise OpenRouterError(
            "OpenRouter request failed",
            code="TIMEOUT" if timed_out else "NETWORK",
            description=(
                "OpenRouter не ответил до истечения тайм-аута"
                if timed_out
                else "не удалось установить соединение с OpenRouter"
            ),
        ) from exc
    if len(payload) > RESPONSE_LIMIT_BYTES:
        raise OpenRouterError(
            "OpenRouter response was too large",
            code="TOO-LARGE",
            description="ответ OpenRouter превысил допустимый размер",
        )
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
