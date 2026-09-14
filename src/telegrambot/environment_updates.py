"""Deterministic, phone-first late environment update messages."""

from datetime import datetime
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from .branding import with_footer
from .models import AirQualitySummary, PollenSummary

GUARDAMAR_TIMEZONE = ZoneInfo("Europe/Madrid")


def _join_ru(values: Sequence[str]) -> str:
    values = tuple(values)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return " и ".join(values)
    return ", ".join(values[:-1]) + " и " + values[-1]


def _period_relevant(period: Optional[str], now: datetime) -> bool:
    """Conservatively suppress updates for coarse periods that already ended."""

    if not period:
        return True
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    end_hour = {
        "утром": 12,
        "днём": 16,
        "во второй половине дня": 20,
        "вечером": 24,
        "в течение дня": 24,
        "в разное время дня": 24,
    }.get(period)
    return end_hour is None or local.hour < end_hour


def _cams_attribution(now: datetime) -> str:
    year = now.astimezone(GUARDAMAR_TIMEZONE).year
    return (
        f"<i>Данные: CAMS / Copernicus, {year}. "
        "ЕС и ECMWF не несут ответственности за их использование.</i>"
    )


def _sanidad_attribution(now: datetime) -> str:
    local = now.astimezone(GUARDAMAR_TIMEZONE)
    return f"<i>Данные: Ministerio de Sanidad, {local:%d.%m.%Y}.</i>"


def air_material_change(
    old: Optional[AirQualitySummary],
    new: Optional[AirQualitySummary],
) -> bool:
    """Only a user-facing ICA severity change is material for air quality."""

    return (old.category if old else 0) != (new.category if new else 0)


def pollen_material_change(
    old: Optional[PollenSummary],
    new: Optional[PollenSummary],
) -> bool:
    """Ignore period-only model movement; allergen meaning must change."""

    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    return (
        frozenset(old.allergens),
        old.ragweed_present,
    ) != (
        frozenset(new.allergens),
        new.ragweed_present,
    )


def _air_change_relevant(
    old: Optional[AirQualitySummary],
    new: Optional[AirQualitySummary],
    now: datetime,
) -> bool:
    if not air_material_change(old, new):
        return False
    target = new if new is not None else old
    return target is not None and _period_relevant(target.period, now)


def _pollen_period(value: Optional[PollenSummary]) -> Optional[str]:
    if value is None:
        return None
    if value.allergens and value.period:
        return value.period
    return value.ragweed_period


def _pollen_change_relevant(
    old: Optional[PollenSummary],
    new: Optional[PollenSummary],
    now: datetime,
) -> bool:
    if not pollen_material_change(old, new):
        return False
    target = new if new is not None else old
    return _period_relevant(_pollen_period(target), now)


def _pollutant_line(value: AirQualitySummary) -> str:
    joined = _join_ru(value.pollutants)
    if len(value.pollutants) == 1:
        return f"Повышен {joined}."
    return f"Повышены {joined}."


def _air_advice(category: int) -> str:
    if category >= 4:
        return (
            "Чувствительным к качеству воздуха людям лучше сократить "
            "пребывание и нагрузки на улице. Остальным тоже стоит уменьшить "
            "длительные интенсивные нагрузки."
        )
    return (
        "Если планировали долгую прогулку или спорт на улице, лучше учитывать "
        "это. Чувствительным к качеству воздуха людям стоит сократить "
        "длительные и интенсивные нагрузки."
    )


def _air_body(
    old: Optional[AirQualitySummary],
    new: Optional[AirQualitySummary],
) -> tuple[str, str]:
    old_level = old.category if old else 0
    new_level = new.category if new else 0
    if new_level > old_level and new is not None:
        heading = (
            "😷 <b>Сегодня с воздухом лучше быть осторожнее</b>"
            if new.category >= 4
            else "😷 <b>Сегодня воздух может быть похуже</b>"
        )
        body = (
            f"По свежему прогнозу {new.period} ожидается ухудшение качества "
            f"воздуха. {_pollutant_line(new)}"
        )
        if new.dust_related and "PM10" in new.pollutants:
            body += " Возможно влияние переносимой пыли."
        body += "\n\n" + _air_advice(new.category)
        return heading, body

    if new is None:
        return (
            "😌 <b>С воздухом стало лучше</b>",
            "Прогноз уточнился: заметного ухудшения качества воздуха, "
            "которое ожидалось сегодня, больше не прогнозируется.",
        )

    return (
        "😌 <b>С воздухом стало лучше</b>",
        f"Прогноз уточнился: ситуация стала спокойнее, но {new.period} "
        f"качество воздуха всё ещё может быть неблагоприятным. "
        f"{_pollutant_line(new)}\n\n{_air_advice(new.category)}",
    )


def _pollen_current_text(value: PollenSummary) -> str:
    parts = []
    if value.allergens:
        period = value.period or "сегодня"
        parts.append(
            f"Высокий уровень {_join_ru(value.allergens)} ожидается {period}."
        )
    if value.ragweed_present:
        if value.ragweed_period == "в течение дня" or not value.ragweed_period:
            parts.append("Также ожидается присутствие амброзии.")
        else:
            parts.append(
                f"Амброзия ожидается {value.ragweed_period}."
            )
    return " ".join(parts)


def _pollen_cleared_text(value: PollenSummary) -> str:
    parts = []
    if value.allergens:
        parts.append(
            f"Высокий уровень {_join_ru(value.allergens)}, который ожидался "
            "сегодня, больше не прогнозируется."
        )
    if value.ragweed_present:
        parts.append(
            "Ожидавшееся присутствие амброзии тоже больше не прогнозируется."
        )
    return " ".join(parts)


def _pollen_body(
    old: Optional[PollenSummary],
    new: Optional[PollenSummary],
) -> tuple[str, str]:
    if new is None:
        assert old is not None
        return (
            "🌿 <b>Для аллергиков есть хорошие новости</b>",
            _pollen_cleared_text(old),
        )

    heading = (
        "🌿 <b>Аллергикам сегодня стоит иметь это в виду</b>"
        if old is None
        else "🌿 <b>Прогноз по пыльце уточнился</b>"
    )
    body = _pollen_current_text(new)
    body += (
        "\n\nЕсли вы реагируете на эту пыльцу, лучше сократить долгие "
        "прогулки и держать окна дома и автомобиля закрытыми. Назначенные "
        "препараты стоит принимать в обычном режиме."
    )
    return heading, body


def build_environment_update(
    old_air: Optional[AirQualitySummary],
    new_air: Optional[AirQualitySummary],
    old_pollen: Optional[PollenSummary],
    new_pollen: Optional[PollenSummary],
    now: datetime,
) -> Optional[str]:
    """Return one compact CAMS update, combining air and pollen when needed."""

    air_changed = _air_change_relevant(old_air, new_air, now)
    pollen_changed = _pollen_change_relevant(old_pollen, new_pollen, now)
    if not air_changed and not pollen_changed:
        return None

    sections = []
    if air_changed:
        sections.append(_air_body(old_air, new_air))
    if pollen_changed:
        sections.append(_pollen_body(old_pollen, new_pollen))

    if len(sections) == 1:
        heading, body = sections[0]
        message = f"{heading}\n\n{body}"
    else:
        bodies = [body for _, body in sections]
        message = "🌿 <b>Есть пара уточнений на сегодня</b>\n\n" + "\n\n".join(bodies)

    return with_footer(message + "\n\n" + _cams_attribution(now))


def _health_change_text(
    kind: str,
    old_level: Optional[int],
    new_level: Optional[int],
) -> Optional[str]:
    """Describe one verified Meteosalud change; unavailable is never a clear."""

    if new_level is None or new_level == old_level:
        return None
    labels = {1: "низкий", 2: "средний", 3: "высокий"}
    name = "жары" if kind == "heat" else "холода"
    if new_level == 0:
        if old_level and old_level > 0:
            return f"Риск {name} на сегодня отменён."
        return None
    if old_level is None or old_level == 0:
        return f"На сегодня появился {labels[new_level]} риск {name} для здоровья."
    direction = "повысился" if new_level > old_level else "снизился"
    return (
        f"Риск {name} на сегодня {direction}: "
        f"теперь {labels[new_level]}."
    )


def build_meteosalud_update(
    old_heat_level: Optional[int],
    new_heat_level: Optional[int],
    old_cold_level: Optional[int],
    new_cold_level: Optional[int],
    now: datetime,
) -> Optional[str]:
    """Render one concise notification for verified, material risk changes."""

    sections = []
    heat = _health_change_text("heat", old_heat_level, new_heat_level)
    if heat is not None:
        text = heat
        if new_heat_level is not None and new_heat_level >= 2:
            text += (
                " Пейте воду, по возможности оставайтесь в прохладе и "
                "сократите активность в самые жаркие часы."
            )
        sections.append(("❤️‍🩹 <b>Сегодня с жарой лучше поосторожнее</b>", text))
    cold = _health_change_text("cold", old_cold_level, new_cold_level)
    if cold is not None:
        text = cold
        if new_cold_level is not None and new_cold_level >= 2:
            text += (
                " Одевайтесь по погоде, сохраняйте тепло и уделите особое "
                "внимание детям, пожилым и другим уязвимым людям."
            )
        sections.append(("❤️‍🩹 <b>Сегодня с холодом лучше поосторожнее</b>", text))

    if not sections:
        return None
    if len(sections) == 1:
        heading, body = sections[0]
        message = f"{heading}\n\n{body}"
    else:
        message = (
            "❤️‍🩹 <b>Есть два уточнения по риску для здоровья</b>\n\n"
            + "\n\n".join(body for _, body in sections)
        )
    return with_footer(message + "\n\n" + _sanidad_attribution(now))
