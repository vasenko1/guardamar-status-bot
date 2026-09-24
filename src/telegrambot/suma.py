"""Lightweight SUMA tax-period reminders for Guardamar del Segura."""

import asyncio
import fcntl
import html
import json
import os
import re
import tempfile
import unicodedata
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Iterator, Optional, Sequence
from zoneinfo import ZoneInfo

from ._transport import BoundedFetchError, fetch_bounded
from .branding import with_footer

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")

MUNICIPAL_URL = "https://www.suma.es/cuerpo_infmunicipal.xhtml?m=76"
PAYMENT_PERIOD_URL = "https://www.suma.es/periodo-pago-voluntario"

STATE_VERSION = 1
HTML_LIMIT_BYTES = 512 * 1024
REQUEST_TIMEOUT_SECONDS = 15
MAX_SENT_KEYS = 64

_SPANISH_MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}
_RUSSIAN_MONTHS = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


class SumaError(RuntimeError):
    """SUMA source or local state cannot safely drive a public notice."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.diagnostic_code = code


class SumaDeliveryUncertain(RuntimeError):
    """Telegram may already contain the notice, so automatic resend is unsafe."""


@dataclass(frozen=True)
class SumaCampaign:
    starts_on: date
    ends_on: date
    direct_debit_deadline: date
    direct_debit_charge: date
    taxes: tuple[str, ...]


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs) -> None:
        if tag.casefold() in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag) -> None:
        if tag.casefold() in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data) -> None:
        if not self.hidden_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _visible_text(payload: bytes) -> str:
    if len(payload) > HTML_LIMIT_BYTES:
        raise SumaError("SUMA response is too large", code="TOO-LARGE")
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SumaError("SUMA response encoding is invalid") from exc
    parser = _VisibleTextParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:
        raise SumaError("SUMA response is invalid HTML") from exc
    text = "\n".join(parser.parts)
    if not text.strip():
        raise SumaError("SUMA response has no visible text")
    return text


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    ).upper()


def _month(value: str) -> int:
    month = _SPANISH_MONTHS.get(_fold(value).strip())
    if month is None:
        raise SumaError("SUMA month name is outside the expected contract")
    return month


def _date_within_period(day: int, month: int, start: date, end: date) -> date:
    candidates = []
    for year in {start.year, end.year}:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if start <= candidate <= end:
            candidates.append(candidate)
    if len(candidates) != 1:
        raise SumaError("SUMA date cannot be placed unambiguously in the period")
    return candidates[0]


def _parse_payment_period_text(text: str) -> tuple[date, date, date, date]:
    folded = " ".join(_fold(text).split())
    period_match = re.search(
        r"PERIODO DE PAGO DE ESTE ANO ES DEL\s+"
        r"(\d{1,2})\s+DE\s+([A-Z]+)\s+AL\s+"
        r"(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})",
        folded,
    )
    charge_match = re.search(
        r"FECHA DE CARGO DE DOMICILIACIONES ES EL\s+"
        r"(\d{1,2})\s+DE\s+([A-Z]+)",
        folded,
    )
    deadline_match = re.search(
        r"PLAZO PARA DOMICILIAR EL PAGO DE SUS RECIBOS FINALIZA EL\s+"
        r"(\d{1,2})\s+DE\s+([A-Z]+)",
        folded,
    )
    if period_match is None or charge_match is None or deadline_match is None:
        raise SumaError("SUMA payment-period markers are missing")

    end_year = int(period_match.group(5))
    start_month = _month(period_match.group(2))
    end_month = _month(period_match.group(4))
    start_year = end_year - 1 if start_month > end_month else end_year
    try:
        start = date(start_year, start_month, int(period_match.group(1)))
        end = date(end_year, end_month, int(period_match.group(3)))
    except ValueError as exc:
        raise SumaError("SUMA payment period is invalid") from exc
    if start >= end or end - start > timedelta(days=180):
        raise SumaError("SUMA payment period is outside the expected bounds")

    deadline = _date_within_period(
        int(deadline_match.group(1)),
        _month(deadline_match.group(2)),
        start,
        end,
    )
    charge = _date_within_period(
        int(charge_match.group(1)),
        _month(charge_match.group(2)),
        start,
        end,
    )
    if not (start <= deadline <= charge <= end):
        raise SumaError("SUMA direct-debit dates conflict with the payment period")
    return start, end, deadline, charge


_MUNICIPAL_ROW = re.compile(
    r"(?P<tax>[^;\n]{3,100})\s*;\s*"
    r"Periodo:\s*[^;\n]{1,40}\s*;\s*"
    r"Plazo de pago:\s*Del\s*"
    r"(?P<start>\d{2}/\d{2}/\d{4})\s*al\s*"
    r"(?P<end>\d{2}/\d{2}/\d{4})\s*\.",
    re.IGNORECASE,
)


def _parse_numeric_date(value: str) -> date:
    try:
        day, month, year = (int(part) for part in value.split("/"))
        return date(year, month, day)
    except (ValueError, TypeError) as exc:
        raise SumaError("SUMA municipal payment date is invalid") from exc


def _parse_municipal_text(
    text: str,
    *,
    expected_start: date,
    expected_end: date,
) -> tuple[str, ...]:
    folded = _fold(text)
    if (
        "GUARDAMAR DEL SEGURA" not in folded
        or "TRIBUTOS PUESTOS AL COBRO" not in folded
    ):
        raise SumaError("SUMA municipal page does not identify Guardamar")

    matches = []
    for match in _MUNICIPAL_ROW.finditer(text):
        start = _parse_numeric_date(match.group("start"))
        end = _parse_numeric_date(match.group("end"))
        if start != expected_start or end != expected_end:
            continue
        tax = " ".join(match.group("tax").split())
        matches.append(tax)

    if not matches:
        raise SumaError(
            "SUMA Guardamar page has no taxes matching the general payment period"
        )
    taxes = tuple(dict.fromkeys(matches))
    if not taxes or len(taxes) > 12:
        raise SumaError("SUMA Guardamar tax list is outside the expected bounds")
    return taxes


def parse_campaign(
    municipal_payload: bytes,
    payment_period_payload: bytes,
) -> SumaCampaign:
    """Cross-check Guardamar taxes against SUMA's current general period."""

    period_text = _visible_text(payment_period_payload)
    start, end, deadline, charge = _parse_payment_period_text(period_text)
    taxes = _parse_municipal_text(
        _visible_text(municipal_payload),
        expected_start=start,
        expected_end=end,
    )
    return SumaCampaign(
        start,
        end,
        deadline,
        charge,
        taxes,
    )


def _is_allowed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.suma.es"
        or parsed.params
        or parsed.fragment
    ):
        return False
    if parsed.path == "/periodo-pago-voluntario":
        return parsed.query == ""
    if parsed.path == "/cuerpo_infmunicipal.xhtml":
        return urllib.parse.parse_qs(
            parsed.query,
            keep_blank_values=True,
        ) == {"m": ["76"]}
    return False


def _fetch_html(url: str) -> bytes:
    try:
        payload, _, _ = fetch_bounded(
            url,
            is_allowed_url=_is_allowed_url,
            accepted_types=frozenset({"text/html", "application/xhtml+xml"}),
            limit_bytes=HTML_LIMIT_BYTES,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es",
                "User-Agent": "GuardamarMorningDigest/0.14",
            },
        )
    except BoundedFetchError as exc:
        raise SumaError(
            "SUMA source is unavailable",
            code=exc.code,
        ) from exc
    return payload


async def fetch_campaign() -> SumaCampaign:
    """Fetch the two small official HTML surfaces sequentially."""

    municipal = await asyncio.to_thread(_fetch_html, MUNICIPAL_URL)
    period = await asyncio.to_thread(_fetch_html, PAYMENT_PERIOD_URL)
    return parse_campaign(municipal, period)


def _ru_date(value: date) -> str:
    return f"{value.day} {_RUSSIAN_MONTHS[value.month]}"


def _tax_label(value: str) -> str:
    folded = _fold(value)
    if "BIENES INMUEBLES URBANA" in folded:
        return "IBI urbana"
    if "BIENES INMUEBLES RUSTICA" in folded:
        return "IBI rústica"
    if "ACTIVIDADES ECONOMICAS" in folded:
        return "IAE"
    if folded.strip() == "VADOS" or "ENTRADA VEHICULOS" in folded:
        return "vados"
    return html.escape(value)


def _join_russian(items: Sequence[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} и {items[1]}"
    return f"{', '.join(items[:-1])} и {items[-1]}"


def _tax_summary(campaign: SumaCampaign) -> str:
    labels = tuple(dict.fromkeys(_tax_label(value) for value in campaign.taxes))
    return _join_russian(labels)


def _format_opening(campaign: SumaCampaign) -> str:
    return with_footer(
        "🧾 <b>Открыт период оплаты SUMA</b>\n\n"
        "В Гуардамаре начался добровольный период оплаты: "
        f"<b>{_tax_summary(campaign)}</b>.\n\n"
        "Оплатить без просрочки можно до "
        f"<b>{_ru_date(campaign.ends_on)}</b>.\n\n"
        "Источник: SUMA Gestión Tributaria"
    )


def _format_direct_debit(campaign: SumaCampaign) -> str:
    return with_footer(
        "🧾 <b>SUMA: ещё неделя для оформления автоплатежа</b>\n\n"
        f"До <b>{_ru_date(campaign.direct_debit_deadline)}</b> можно "
        "оформить domiciliación для квитанций текущего периода SUMA.\n\n"
        "После этой даты новая domiciliación уже не будет действовать "
        "для текущего периода.\n\n"
        "Списание по действующей domiciliación — "
        f"<b>{_ru_date(campaign.direct_debit_charge)}</b>.\n\n"
        "Источник: SUMA Gestión Tributaria"
    )


def _format_charge(campaign: SumaCampaign, today: date) -> str:
    remaining = (campaign.ends_on - today).days
    if remaining == 1:
        deadline = (
            "Для остальных добровольный срок оплаты заканчивается "
            f"<b>завтра, {_ru_date(campaign.ends_on)}</b>."
        )
    else:
        deadline = (
            "Для остальных до конца добровольного периода — "
            f"<b>{remaining} дней</b>: срок заканчивается "
            f"<b>{_ru_date(campaign.ends_on)}</b>."
        )
    return with_footer(
        "🧾 <b>SUMA: сегодня списание по domiciliación</b>\n\n"
        "Если у вас подключена автоматическая оплата SUMA, "
        f"<b>сегодня, {_ru_date(today)}</b>, запланировано списание "
        "по текущему периоду.\n\n"
        f"{deadline}\n\n"
        "Источник: SUMA Gestión Tributaria"
    )


def _format_final(campaign: SumaCampaign) -> str:
    return with_footer(
        "🧾 <b>SUMA: завтра заканчивается срок оплаты</b>\n\n"
        f"<b>{_ru_date(campaign.ends_on)}</b> — последний день "
        "добровольной оплаты текущего периода SUMA в Гуардамаре.\n\n"
        "Если квитанция ещё не оплачена, лучше сделать это до окончания "
        "срока. После добровольного периода к неоплаченным суммам могут "
        "применяться предусмотренные законом доплаты, проценты и расходы.\n\n"
        "Источник: SUMA Gestión Tributaria"
    )


def _trigger_schedule(campaign: SumaCampaign) -> tuple[tuple[str, date], ...]:
    return (
        ("opening", campaign.starts_on),
        (
            "direct-debit",
            campaign.direct_debit_deadline - timedelta(days=7),
        ),
        ("charge", campaign.direct_debit_charge),
        ("final", campaign.ends_on - timedelta(days=1)),
    )


def _trigger_key(kind: str, trigger_date: date) -> str:
    return f"{kind}:{trigger_date.isoformat()}"


def _today_notice(
    campaign: SumaCampaign,
    today: date,
) -> Optional[tuple[str, str]]:
    by_priority = (
        ("charge", campaign.direct_debit_charge, _format_charge),
        ("final", campaign.ends_on - timedelta(days=1), _format_final),
        (
            "direct-debit",
            campaign.direct_debit_deadline - timedelta(days=7),
            _format_direct_debit,
        ),
        ("opening", campaign.starts_on, _format_opening),
    )
    for kind, trigger_date, formatter in by_priority:
        if today != trigger_date:
            continue
        key = _trigger_key(kind, trigger_date)
        message = (
            formatter(campaign, today)
            if kind == "charge"
            else formatter(campaign)
        )
        return key, message
    return None


_SENT_KEY = re.compile(
    r"^(opening|direct-debit|charge|final):(\d{4}-\d{2}-\d{2})$"
)


def _key_date(value: str) -> date:
    match = _SENT_KEY.fullmatch(value)
    if match is None:
        raise SumaError("SUMA state contains an invalid trigger key", code="STATE")
    try:
        return date.fromisoformat(match.group(2))
    except ValueError as exc:
        raise SumaError("SUMA state contains an invalid trigger date", code="STATE") from exc


def _prune_sent(values: Sequence[str], today: date) -> list[str]:
    cutoff = today - timedelta(days=730)
    kept = sorted(
        {
            value
            for value in values
            if _key_date(value) >= cutoff
        }
    )
    return kept[-MAX_SENT_KEYS:]


class SumaState:
    """Tiny atomic set of already-accounted semantic trigger dates."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Optional[list[str]]:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SumaError("SUMA state is unreadable", code="STATE") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SumaError("SUMA state is corrupt", code="STATE") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "sent"}
            or value.get("version") != STATE_VERSION
            or not isinstance(value.get("sent"), list)
            or len(value["sent"]) > MAX_SENT_KEYS
            or any(not isinstance(item, str) for item in value["sent"])
        ):
            raise SumaError("SUMA state is corrupt", code="STATE")
        for item in value["sent"]:
            _key_date(item)
        return list(dict.fromkeys(value["sent"]))

    def write(self, sent: Sequence[str], today: date) -> None:
        values = _prune_sent(sent, today)
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                dir=self.path.parent,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(
                    {"version": STATE_VERSION, "sent": values},
                    output,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise SumaError("SUMA state could not be saved", code="STATE") from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        except BlockingIOError as exc:
            raise SumaError("another SUMA run is active", code="BUSY") from exc
        except OSError as exc:
            raise SumaError("SUMA state could not be locked", code="STATE") from exc


async def monitor_suma(
    state: SumaState,
    now: datetime,
    send: Callable[[str], Awaitable[int]],
    *,
    fetch_campaign_fn: Callable[[], Awaitable[SumaCampaign]] = fetch_campaign,
) -> str:
    """Publish at most one exact-date notice; first successful run is silent."""

    today = now.astimezone(GUARDAMAR_TIMEZONE).date()
    with state.exclusive_run():
        campaign = await fetch_campaign_fn()
        current = state.read()
        schedule = _trigger_schedule(campaign)

        if current is None:
            baseline = [
                _trigger_key(kind, trigger_date)
                for kind, trigger_date in schedule
                if trigger_date <= today
            ]
            state.write(baseline, today)
            return "baseline"

        sent = set(_prune_sent(current, today))
        notice = _today_notice(campaign, today)
        if notice is None:
            return "no_trigger"

        key, message = notice
        if key in sent:
            return "duplicate"

        sent.add(key)
        state.write(sorted(sent), today)
        try:
            await send(message)
        except SumaDeliveryUncertain:
            raise
        except Exception:
            sent.remove(key)
            state.write(sorted(sent), today)
            raise
        return "published"
