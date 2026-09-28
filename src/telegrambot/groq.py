"""Bounded text-only Groq fallback for approved Gemini requests."""

import json
import urllib.parse
from typing import Any, Dict, List, Optional

from ._transport import BoundedFetchError, fetch_bounded


MODEL = "openai/gpt-oss-120b"
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
API_HOST = "api.groq.com"
REQUEST_TIMEOUT_SECONDS = 30
RESPONSE_LIMIT_BYTES = 100_000
MAX_OUTPUT_TOKENS = 1_000


class GroqError(RuntimeError):
    """An operator-safe Groq protocol or validation failure."""

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


def _is_groq_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == API_HOST


_TRANSPORT_DESCRIPTIONS = {
    "REDIRECT": "Groq перенаправил запрос на другой сайт",
    "CONTENT-TYPE": "Groq вернул ответ не в формате JSON",
    "TIMEOUT": "Groq не ответил до истечения тайм-аута",
    "NETWORK": "не удалось установить соединение с Groq",
    "TOO-LARGE": "ответ Groq превысил допустимый размер",
}


def _text_content(parts: List[Dict[str, Any]]) -> str:
    texts = []
    for part in parts:
        if set(part) != {"text"} or not isinstance(part.get("text"), str):
            raise GroqError(
                "Unsupported Groq input part",
                code="INPUT",
                description="резервная модель принимает только текст",
            )
        text = part["text"].strip()
        if not text:
            raise GroqError(
                "Empty Groq text input",
                code="INPUT",
                description="резервная модель получила пустой текст",
            )
        texts.append(text)
    if not texts:
        raise GroqError(
            "Empty Groq input",
            code="INPUT",
            description="резервная модель не получила входных данных",
        )
    return "\n".join(texts)


def request_json(
    api_key: str,
    parts: List[Dict[str, Any]],
    schema: Optional[Dict[str, Any]],
    max_output_tokens: int,
) -> Dict[str, Any]:
    """Return one strict structured response from the pinned Groq fallback."""

    if not api_key or any(character in api_key for character in "\r\n"):
        raise GroqError(
            "Groq configuration is invalid",
            code="CONFIG",
            description="ключ Groq отсутствует или имеет неверный формат",
        )
    if not isinstance(schema, dict):
        raise GroqError(
            "Groq fallback requires a JSON schema",
            code="INPUT",
            description="для резервной модели не задана строгая схема",
        )
    if not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
        raise GroqError(
            "Groq output limit is invalid",
            code="INPUT",
            description="лимит ответа резервной модели имеет неверный формат",
        )

    body_data = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": _text_content(parts),
        }],
        "max_completion_tokens": min(max_output_tokens, MAX_OUTPUT_TOKENS),
        "temperature": 0,
        "reasoning_effort": "low",
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "guardamar_result",
                "strict": True,
                "schema": schema,
            },
        },
    }
    try:
        payload, _, _ = fetch_bounded(
            ENDPOINT,
            is_allowed_url=_is_groq_url,
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
        raise GroqError(
            f"Groq request failed: {exc.code}",
            code=exc.code,
            status=exc.status,
            description=(
                f"Groq вернул HTTP {exc.status}"
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
        raise GroqError(
            "Groq returned an invalid response",
            code="INVALID-RESPONSE",
            description="Groq вернул некорректный JSON-ответ",
        ) from exc
    if not isinstance(result, dict):
        raise GroqError(
            "Groq returned an invalid result",
            code="INVALID-STRUCTURE",
            description="структура результата Groq некорректна",
        )
    return result
