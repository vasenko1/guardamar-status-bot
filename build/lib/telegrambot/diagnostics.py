"""Stable, operator-safe source diagnostics for private previews."""

import urllib.error
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class SourceDiagnostic:
    code: str
    source: str
    description: str

    def render(self) -> str:
        return f"[{self.code}] {self.source}: {self.description}"


def _cause(exc: BaseException, kind) -> Optional[BaseException]:
    current: Optional[BaseException] = exc
    while current is not None:
        if isinstance(current, kind):
            return current
        current = current.__cause__
    return None


def _api_status(exc: BaseException) -> Optional[int]:
    current: Optional[BaseException] = exc
    while current is not None:
        value = vars(current).get("api_status")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        current = current.__cause__
    return None


def source_error(
    prefix: str,
    source: str,
    exc: BaseException,
    *,
    stage: str = "",
) -> SourceDiagnostic:
    """Classify a source failure without exposing URLs or response bodies."""

    code_prefix = f"{prefix}-{stage}" if stage else prefix
    current: Optional[BaseException] = exc
    while current is not None:
        diagnostic_code = vars(current).get("diagnostic_code")
        description = vars(current).get("safe_description")
        if (
            isinstance(diagnostic_code, str)
            and diagnostic_code
            and (
                diagnostic_code != "INVALID-RESPONSE"
                or isinstance(description, str)
            )
        ):
            return SourceDiagnostic(
                f"{code_prefix}-{diagnostic_code}",
                source,
                description
                if isinstance(description, str) and description
                else "источник вернул ошибку",
            )
        current = current.__cause__

    api_status = _api_status(exc)
    if api_status is not None:
        return SourceDiagnostic(
            f"{code_prefix}-API-{api_status}",
            source,
            f"API вернул служебный статус {api_status}",
        )
    http_error = _cause(exc, urllib.error.HTTPError)
    if isinstance(http_error, urllib.error.HTTPError):
        return SourceDiagnostic(
            f"{code_prefix}-HTTP-{http_error.code}",
            source,
            f"сервер вернул HTTP {http_error.code}",
        )
    if _cause(exc, TimeoutError) is not None:
        return SourceDiagnostic(
            f"{code_prefix}-TIMEOUT",
            source,
            "сервер не ответил до истечения тайм-аута",
        )
    if _cause(exc, urllib.error.URLError) is not None:
        return SourceDiagnostic(
            f"{code_prefix}-NETWORK",
            source,
            "не удалось установить сетевое соединение",
        )

    message = str(exc).casefold()
    classifications = (
        (
            "redirect",
            "REDIRECT",
            "источник перенаправил запрос на недопустимый адрес",
        ),
        (
            "not allowed",
            "URL-POLICY",
            "адрес источника не прошёл проверку безопасности",
        ),
        ("too large", "TOO-LARGE", "ответ превысил допустимый размер"),
        ("size limit", "TOO-LARGE", "ответ превысил допустимый размер"),
        ("invalid json", "INVALID-JSON", "ответ не является корректным JSON"),
        ("invalid cap xml", "INVALID-XML", "получен некорректный CAP XML"),
        (
            "archive was invalid",
            "INVALID-ARCHIVE",
            "получен повреждённый архив",
        ),
        (
            "did not provide a product download",
            "NO-PRODUCT",
            "API не предоставил файл продукта",
        ),
        (
            "did not contain a download url",
            "NO-DOWNLOAD",
            "API не вернул адрес файла продукта",
        ),
        ("was empty", "EMPTY", "источник вернул пустой набор данных"),
        (
            "did not include today",
            "NO-TODAY",
            "в ответе нет данных на текущую дату",
        ),
        (
            "no valid temperature range",
            "NO-TEMPERATURE",
            "нет корректного минимума и максимума температуры",
        ),
        (
            "invalid temperatures",
            "INVALID-TEMPERATURE",
            "температура имеет некорректный формат",
        ),
        (
            "invalid structure",
            "INVALID-STRUCTURE",
            "структура ответа не соответствует ожидаемой",
        ),
        (
            "invalid day list",
            "INVALID-DAYS",
            "список дней имеет некорректный формат",
        ),
        (
            "not a list",
            "INVALID-STRUCTURE",
            "структура ответа не соответствует ожидаемой",
        ),
        (
            "did not contain beach data",
            "NO-DATA",
            "на странице отсутствует блок данных пляжей",
        ),
        (
            "invalid beach data",
            "INVALID-DATA",
            "данные пляжей имеют некорректный формат",
        ),
        (
            "poster was not found",
            "NO-POSTER",
            "официальная месячная афиша не найдена",
        ),
        (
            "snapshot is invalid",
            "INVALID-SNAPSHOT",
            "локальный снимок афиши повреждён",
        ),
        (
            "invalid poster event",
            "INVALID-EVENT",
            "данные события в афише имеют некорректный формат",
        ),
        (
            "event end time has no start time",
            "INVALID-EVENT",
            "в событии указано окончание без времени начала",
        ),
        (
            "key is required",
            "NO-AI-KEY",
            "не настроен ключ Gemini для обработки афиши",
        ),
        (
            "translation failed",
            "TRANSLATION",
            "не удалось безопасно обработать официальный текст",
        ),
        (
            "extraction failed",
            "EXTRACTION",
            "не удалось безопасно извлечь данные",
        ),
        (
            "request failed",
            "REQUEST",
            "запрос завершился ошибкой без HTTP-статуса",
        ),
    )
    for marker, suffix, description in classifications:
        if marker in message:
            return SourceDiagnostic(
                f"{code_prefix}-{suffix}",
                source,
                description,
            )
    return SourceDiagnostic(
        f"{code_prefix}-INVALID",
        source,
        "ответ не прошёл проверку формата или достоверности",
    )


def render_diagnostics(items: Iterable[SourceDiagnostic]) -> str:
    unique = []
    seen = set()
    for item in items:
        key = (item.code, item.source, item.description)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if not unique:
        return ""
    return "\n\n🔧 Диагностика источников\n" + "\n".join(
        f"• {item.render()}" for item in unique
    )
