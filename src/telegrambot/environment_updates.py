"""Small deterministic late-day environment update decisions."""

from typing import Optional

from .models import AirQualitySummary, PollenSummary


def air_material_change(old: Optional[AirQualitySummary], new: Optional[AirQualitySummary]) -> bool:
    return (old.category if old else 0) != (new.category if new else 0)


def pollen_material_change(old: Optional[PollenSummary], new: Optional[PollenSummary]) -> bool:
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    return (old.allergens, old.period, old.ragweed_present, old.ragweed_period) != (
        new.allergens, new.period, new.ragweed_present, new.ragweed_period
    )


def build_environment_update(
    old_air: Optional[AirQualitySummary], new_air: Optional[AirQualitySummary],
    old_pollen: Optional[PollenSummary], new_pollen: Optional[PollenSummary],
) -> Optional[str]:
    parts = []
    if air_material_change(old_air, new_air):
        if new_air is None:
            parts.append("С воздухом стало лучше.")
        else:
            parts.append("Сегодня воздух может быть похуже. Ожидается ухудшение качества воздуха.")
    if pollen_material_change(old_pollen, new_pollen):
        if new_pollen is None:
            parts.append("Для аллергиков есть хорошие новости: значимого прогноза пыльцы больше нет.")
        else:
            parts.append("Аллергикам сегодня стоит иметь прогноз пыльцы в виду.")
    return "\n\n".join(parts) if parts else None
