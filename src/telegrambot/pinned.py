"""Static linked city guide and one-shot Telegram publication."""

import asyncio
import fcntl
import html
import json
import os
import tempfile
import urllib.parse
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import (
    Awaitable,
    Callable,
    Dict,
    Iterator,
    Mapping,
    Optional,
    Sequence,
)

from .branding import FOOTER, with_footer
from .music_school import (
    SCHOOL_ADDRESS,
    SCHOOL_EMAIL,
    SCHOOL_MAP_URL,
    SCHOOL_PHONE,
    SCHOOL_SITE_URL,
    registration_is_open as music_registration_is_open,
)
from .sporttia import (
    SPORTTIA_ACTIVITY_KEYS,
    SPORTTIA_CENTER_URL,
    select_sport_groups,
)
from .state import StateError
from .wifi import WIFI_BASELINE_POINTS
from .telegram import TelegramError, is_ambiguous_send_failure

PINNED_CONTENT_VERSION = 2
DEFAULT_PINNED_STATE_PATH = "state/pinned_guide.json"
MAX_RECONCILIATION_PASSES = 3
AQUALIDER_BOOKING_URL = "https://aqualidernatacion.simplybook.it/v2/"
FISHING_GVA_LICENSE_URL = "https://sede.gva.es/es/detall-tramit?id_proc=G647"
FISHING_PESCAREC_URL = (
    "https://www.mapa.gob.es/es/pesca/temas/pesca-maritima-de-recreo/pesca-rec"
)
FISHING_RESTRICTIONS_URL = (
    "https://www.mapa.gob.es/es/pesca/temas/control-inspeccion-lucha-pesca-ilegal/"
    "aperturasycierres"
)
AIRPORT_STOP_MAP_URL = "https://maps.app.goo.gl/V3REb7P6CmdJtgom7"
GUARDAMAR_BUS_STATION_MAP_URL = (
    "https://www.google.com/maps/search/?api=1&"
    "query=38.0877707496%2C-0.6560185196"
)
YOUTH_CENTRE_MAP_URL = "https://maps.app.goo.gl/HhfDRr6tpbbKekjM7"
POLIDEPORTIVO_MAP_URL = "https://maps.app.goo.gl/KSZV3aVX75UxATQ68"
POOL_INDOOR_MAP_URL = "https://maps.app.goo.gl/p9GqBDQEbnyQQNaAA"
POOL_OUTDOOR_MAP_URL = "https://maps.app.goo.gl/dnCq36EzS8DTcq4T6"
PALAU_SANT_JAUME_MAP_URL = "https://maps.app.goo.gl/Jp7EA9RqrZQPcVq17"
LES_RABOSES_MAP_URL = "https://maps.app.goo.gl/tGXyANAYgRREeajP8"
MOLIVENT_MAP_URL = "https://maps.app.goo.gl/kS2wM2V8x2twhuBCA"
SPORT_MEDICAL_CERTIFICATE_URL = (
    "https://www.guardamardelsegura.es/wp-content/uploads/2023/03/"
    "Certificado-medico-deportivo-ACTUALIZADO.pdf"
)
SPORTS_CONTACT_EMAIL = "deportesguardamar@hotmail.com"
TENNIS_COURT_MAP_URL = "https://maps.app.goo.gl/tzMkY17nvVPA4CWx6"
FOOTBALL_FORM_URL = "https://guardamarsoccercd.com/inscripcion-a-futbol-base/"
FOOTBALL_EMAIL = "info@guardamarsoccercd.com"

PALAU_ACTIVITY_KEYS = (
    "rhythmic_gymnastics",
    "judo",
    "multisport",
    "inclusive_multisport",
    "senior_gymnastics",
    "women_gymnastics",
)
LES_RABOSES_SOURCE_ACTIVITY_KEYS = ("deporte_plus",)
MOLIVENT_SOURCE_ACTIVITY_KEYS = ("psychomotricity",)
SPORT_ACTIVITY_META = {
    "rhythmic_gymnastics": ("🤸", "Художественная гимнастика"),
    "judo": ("🥋", "Дзюдо"),
    "multisport": ("🏃", "Мультиспорт"),
    "inclusive_multisport": ("♿", "Инклюзивный мультиспорт"),
    "senior_gymnastics": ("🧓", "Гимнастика для старшего возраста"),
    "women_gymnastics": ("👩", "Гимнастика Asociación Mujeres"),
    "deporte_plus": ("🏃", "DEPORTE +"),
    "psychomotricity": ("🧒", "Психомоторика"),
}
MUSIC_ACTIVITY_KEYS = (
    "music_basics",
    "music_vocal",
    "music_instruments",
)
MUSIC_ACTIVITY_META = {
    "music_basics": ("🎶", "Музыкальное развитие и грамота"),
    "music_vocal": ("🎤", "Вокал и хор"),
    "music_instruments": ("🎷", "Музыкальные инструменты"),
}

SPORT_ACTIVITY_INDEX_KEYS = (
    "rhythmic_gymnastics",
    "judo",
    "multisport",
    "psychomotricity",
    "deporte_plus",
    "inclusive_multisport",
    "senior_gymnastics",
    "women_gymnastics",
)
SPORT_ACTIVITY_INDEX_LABELS = {
    "psychomotricity": "Психомоторика · 2–6 лет",
    "inclusive_multisport": "Инклюзивный мультиспорт · 7+",
    "senior_gymnastics": "Гимнастика для старших",
    "women_gymnastics": "Гимнастика Mujeres",
}
MUSIC_ACTIVITY_INDEX_LABELS = {
    "music_basics": "Музыкальная грамота",
    "music_instruments": "Инструменты",
}

RECURRING_ACTIVITY_KEYS = (
    "chess",
    "literary_group",
    "dinamizacion",
)
RECURRING_ACTIVITY_META = {
    "chess": ("♟️", "Шахматы"),
    "literary_group": ("✍️", "Литературное творчество"),
    "dinamizacion": ("🤝", "Муниципальные занятия и мастерские"),
}
DINAMIZACION_GROUP_TITLES = {
    "mindful_movement": "Осознанное движение",
    "mobile": "Как пользоваться смартфоном",
    "recycled_art": "Творчество из переработанных материалов",
    "textile_painting": "Роспись по ткани",
    "senior_hiking": "Прогулки для старшего возраста",
    "senior_memory": "Тренировка памяти",
    "senior_computing": "Компьютерная грамотность",
    "emotions_school": "Школа эмоций",
}

Send = Callable[[str], Awaitable[int]]
Edit = Callable[[int, str], Awaitable[None]]
Pin = Callable[[int], Awaitable[None]]


CAMERAS = with_footer(
    """📹 <b>Гуардамар в прямом эфире</b>

🏙 <b>Город</b>

• <a href="https://www.guardamardelsegura.es/2024/11/21/vista-desde-el-castillo/"><b>Вид с Castillo</b></a>
Панорама Гуардамара с крепостного холма.

• <a href="https://www.guardamardelsegura.es/2024/11/21/plaza-del-ayuntamiento/"><b>Площадь Ayuntamiento</b></a>
Главная площадь города и церковь Sant Jaume.

• <a href="https://www.guardamardelsegura.es/2025/06/27/avda-los-pinos-en-directo/"><b>Проспект Los Pinos</b></a>
Одна из центральных пешеходных улиц Гуардамара.

🌊 <b>Море</b>

• <a href="https://www.comunitatvalenciana.com/es/alacant-alicante/guardamar-del-segura/webcams/guardamar-del-segura-1"><b>Пляжи Centro и La Roqueta</b></a>
Официальная камера Comunitat Valenciana.

• <a href="https://www.skylinewebcams.com/es/webcam/espana/comunidad-valenciana/alicante/guardamar-del-segura.html"><b>Пляж La Roqueta</b></a>
Панорамный вид на пляж и море."""
)


WIFI_POINT_META = {
    "music_school": (
        "🎵", "Escola de Música", "C/ Mercat, 2",
        "Escola de Música, C/ Mercat 2, Guardamar del Segura",
    ),
    "culture_house": (
        "🎭", "Casa de Cultura", "C/ Colón, 60",
        "Casa de Cultura, C/ Colón 60, Guardamar del Segura",
    ),
    "los_pinos": (
        "🌴", "Avda. Los Pinos", None,
        "Avenida Los Pinos, Guardamar del Segura",
    ),
    "constitution_square": (
        "🏛", "Plaza de la Constitución", None,
        "Plaza de la Constitución, Guardamar del Segura",
    ),
    "seafront": (
        "🌊", "Paseo Marítimo · Avda. de Europa", None,
        "Paseo Marítimo, Avenida de Europa, Guardamar del Segura",
    ),
    "study_room": (
        "📚", "Sala de Estudios 24/365", "C/ Mayor, 69",
        "C/ Mayor 69, Guardamar del Segura",
    ),
    "library": (
        "📖", "Biblioteca Pública", "C/ San Jaime, 5",
        "Biblioteca Pública, C/ San Jaime 5, Guardamar del Segura",
    ),
}
WIFI_POINT_ORDER = tuple(key for key, _ in WIFI_BASELINE_POINTS)


LEAF_MESSAGES: Dict[str, str] = {
    "line_1": with_footer(
        """🚌 <b>Городской автобус · Линия 1</b>
Маршрут соединяет Puerto Deportivo (порт), центр Гуардамара, автовокзал, пляжную зону, Hotel Playas de Guardamar и Campomar. Автобус ходит в обоих направлениях.

🗓 <b>В июле и августе:</b> автобус ходит ежедневно.
🗓 <b>С сентября по июнь:</b> с понедельника по субботу. По воскресеньям действует отдельное расписание.

⭐ Рейсы, отмеченные звёздочкой, дополнительно заезжают в Los Secanos.

🛍 В дни работы рынка, обычно по средам утром, автобус останавливается рядом с рынком: La Redona, 56."""
    ),
    "line_2": with_footer(
        """🚌 <b>Городской автобус · Линия 2</b>
Маршрут соединяет Polideportivo (спортивный комплекс) и автовокзал с районами Pórtico Mediterráneo, El Raso, Campico, El Edén, Los Estaños, La Rosa и Pinomar. Автобус ходит в обоих направлениях.

🗓 <b>В июле и августе:</b> автобус ходит ежедневно.
🗓 <b>С сентября по июнь:</b> с понедельника по субботу. По воскресеньям действует отдельное расписание.

🛍 По средам автобус также останавливается рядом с рынком: La Redona, 56."""
    ),
    "airport": with_footer(
        f"""✈️ <b>Гуардамар ↔ аэропорт Alicante-Elche</b>
До аэропорта можно доехать без пересадок на автобусе Bus Sigüenza.

🗓 Автобус ходит каждый день. Рейсы на текущую дату обновляются здесь каждое утро.

📍 <b>Откуда и куда</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">автовокзал Гуардамара</a> ↔ <a href="{AIRPORT_STOP_MAP_URL}">остановка у терминала аэропорта</a>

🕒 <a href="https://www.bus-siguenza.com/index.php?page=urbano">Найти расписание на нужную дату</a>"""
    ),
    "hospital": with_footer(
        f"""🏥 <b>Гуардамар ↔ Hospital de Torrevieja</b>
До больницы можно доехать без пересадок на линии 6 Avanza.

🗓 <b>По рабочим дням, с понедельника по пятницу</b>

<b>Гуардамар → Hospital de Torrevieja</b>
07:30 · 09:00 · 11:00 · 13:00 · 15:00 · 17:30

<b>Hospital de Torrevieja → Гуардамар</b>
08:00 · 09:30 · 11:30 · 13:30 · 15:30 · 18:00

🗓 <b>По выходным и праздникам</b>

<b>Гуардамар → Hospital de Torrevieja</b>
07:30 · 09:00 · 13:00 · 16:30

<b>Hospital de Torrevieja → Гуардамар</b>
08:00 · 09:30 · 13:30 · 17:00

⏱ Около 30 минут

📍 <b>Остановки по пути</b>

<b>В больницу</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">Guardamar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0583071959%2C-0.6569832033">La Rosa</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0241372606%2C-0.6570898059">La Mata</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a>

<b>Обратно</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0262439991%2C-0.655954">La Mata</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0560738544%2C-0.6568971718">La Rosa</a> · <a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">Guardamar</a>

ℹ️ <a href="https://www.gva.es/es/web/arees/infraestructures-i-transports/-/asset_publisher/21dbI2RUgqwC/content/nuevas-concesiones-de-atuob%25C3%259As-en-la-comarca-de-la-vega-baja/20081096?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_21dbI2RUgqwC_assetEntryId=412097993">Подробнее о линии</a>"""
    ),
    "alicante": with_footer(
        f"""🚌 <b>Гуардамар ↔ Alicante</b>
Доехать можно без пересадок на автобусе Avanza.

По дороге автобус заезжает в La Marina, Santa Pola и El Altet.

📍 <b>Откуда и куда</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">автовокзал Гуардамара</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses+de+Alicante">автовокзал в Alicante</a>

🕒 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Найти расписание на нужную дату</a>"""
    ),
    "elche": with_footer(
        f"""🚌 <b>Гуардамар ↔ Elche</b>
Доехать можно без пересадок на автобусе Avanza.

По дороге автобус заезжает в San Fulgencio, Dolores, Catral и Crevillente.

📍 <b>Откуда и куда</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">автовокзал Гуардамара</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Av.+Vicente+Quiles%2C+Elche">остановка на проспекте Vicente Quiles в Elche</a>

🕒 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Найти расписание на нужную дату</a>"""
    ),
    "south": with_footer(
        f"""🚌 <b>Гуардамар ↔ Torrevieja ↔ Pilar de la Horadada</b>
До Torrevieja и Pilar de la Horadada можно доехать без пересадок на автобусе Avanza.

По дороге автобус проходит через La Rosa, Pinomar, La Mata, Playa Flamenca, Campoamor и Mil Palmeras.

📍 <b>Основные остановки</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">Гуардамар</a> → <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+del+Mar+40%2C+Torrevieja">Torrevieja</a> → <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Emilio+Tarraga+18%2C+Pilar+de+la+Horadada">Pilar de la Horadada</a>

🕒 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Найти расписание на нужную дату</a>"""
    ),
    "zenia": with_footer(
        f"""🛍 <b>Гуардамар - Zenia Boulevard</b>
До торгового центра можно доехать без пересадок на автобусе Avanza.

🚌 <b>Автобусы:</b> Guardamar - Pilar de la Horadada и Alicante - Pilar de la Horadada
Туда садитесь в сторону <b>Pilar de la Horadada</b>. Обратно - в сторону <b>Guardamar</b> или <b>Alicante</b>.

⏱ <b>В пути:</b> около 1 часа

🗓 Рейсы на текущую дату обновляются здесь каждое утро.

📍 <b>Откуда и куда</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">автовокзал Гуардамара</a> → <a href="https://www.google.com/maps/search/?api=1&amp;query=37.9292298333%2C-0.7346398333">ТЦ Zenia Boulevard</a>

🕒 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Найти расписание на нужную дату</a>"""
    ),
    "inland": with_footer(
        f"""🚌 <b>Гуардамар ↔ Orihuela</b>
Доехать можно без пересадок на автобусе Bus Sigüenza.

По дороге автобус заезжает в Daya Vieja, Rojales, Formentera del Segura, Las Heredades, Daya Nueva, Almoradí, Hospital Vega Baja, Benejúzar, Jacarilla и Bigastro.

📍 <b>Откуда и куда</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">автовокзал Гуардамара</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Orihuela">автовокзал в Orihuela</a>

🕒 <a href="https://www.bus-siguenza.com/index.php?page=urbano">Найти расписание на нужную дату</a>"""
    ),
    "university": with_footer(
        f"""🎓 <b>Гуардамар ↔ Universidad de Alicante</b>
В учебный период до университета ходит прямой автобус Avanza.

Для поездки нужно быть членом ADEUGT.

📍 <b>Где садиться</b>

<b>В университет</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Pintor+Sorolla+2%2C+Guardamar+del+Segura">улица Pintor Sorolla, 2</a> · <a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">автовокзал Гуардамара</a>

<b>Обратно</b>
<a href="{html.escape(GUARDAMAR_BUS_STATION_MAP_URL, quote=True)}">автовокзал Гуардамара</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Pintor+Sorolla+1%2C+Guardamar+del+Segura">улица Pintor Sorolla, 1</a>

🕒 <a href="https://web.ua.es/es/oia/transporte-universitario/vega-baja.html">Расписание и условия поездки</a>"""
    ),
}

GUIDE_MESSAGE_KEYS = (
    "places",
    "polideportivo",
    "pool_indoor",
    "pool_outdoor",
    "palau_sant_jaume",
    "les_raboses",
    "molivent",
    "music_school",
    "youth_centre",
    "wifi",
    "fishing",
    "activities",
    "swimming",
    "football",
)
PINNED_MESSAGE_KEYS = (
    *LEAF_MESSAGES,
    "cameras",
    "transport",
    *GUIDE_MESSAGE_KEYS,
    "root",
)
PINNED_PARENT_KEYS = {
    **{key: "transport" for key in LEAF_MESSAGES},
    "cameras": "root",
    "transport": "root",
    "places": "root",
    "polideportivo": "places",
    "pool_indoor": "polideportivo",
    "pool_outdoor": "polideportivo",
    "palau_sant_jaume": "polideportivo",
    "les_raboses": "places",
    "molivent": "places",
    "music_school": "places",
    "youth_centre": "places",
    "wifi": "root",
    "fishing": "root",
    "activities": "root",
    "swimming": "activities",
    "football": "activities",
}


def telegram_message_link(chat_id: str, message_id: int) -> str:
    """Build a member-visible link for a public or private supergroup."""

    if message_id <= 0:
        raise ValueError("message_id must be positive")
    value = chat_id.strip()
    if value.startswith("@") and len(value) > 1:
        return f"https://t.me/{value[1:]}/{message_id}"
    if value.startswith("-100") and value[4:].isdigit():
        return f"https://t.me/c/{value[4:]}/{message_id}"
    raise ValueError(
        "TELEGRAM_CHAT_ID must be @username or a -100 supergroup ID"
    )


def _linked(label: str, key: str, links: Optional[Mapping[str, str]]) -> str:
    if links is None:
        return f"<b>{label}</b>"
    url = links[key]
    return f'<a href="{url}"><b>{label}</b></a>'


def _direct_link(label: str, url: Optional[str]) -> str:
    if url is None:
        return f"<b>{label}</b>"
    return f'<a href="{url}"><b>{label}</b></a>'


def _with_back_link(
    message: str,
    label: str,
    url: Optional[str],
) -> str:
    """Insert one visible return link immediately before the shared footer."""

    suffix = f"\n\n{FOOTER}"
    if not message.endswith(suffix):
        raise ValueError("guide message must end with the shared footer")
    target = f"<b>{label}</b>"
    if url is not None:
        target = f'<a href="{url}"><b>{label}</b></a>'
    return with_footer(f"{message[:-len(suffix)]}\n\n⬅️ {target}")


def build_leaf_message(
    key: str,
    transport_link: Optional[str] = None,
) -> str:
    """Build one route detail with a return to the transport navigator."""

    return _with_back_link(
        LEAF_MESSAGES[key],
        "К списку транспорта",
        transport_link,
    )


def build_cameras(root_link: Optional[str] = None) -> str:
    """Build the camera list with a return to the compact root."""

    return _with_back_link(
        CAMERAS,
        "Полезное о Гуардамаре",
        root_link,
    )


def build_transport_index(
    links: Optional[Mapping[str, str]] = None,
    root_link: Optional[str] = None,
) -> str:
    """Build the transport navigator with live links or preview labels."""

    message = f"""🧭 <b>Транспорт из Гуардамара</b>

🏙 <b>Городские маршруты:</b> {_linked('Линия 1', 'line_1', links)} · {_linked('Линия 2', 'line_2', links)}

✈️ {_linked('Аэропорт Alicante-Elche', 'airport', links)}

🏥 {_linked('Больница в Торревьехе', 'hospital', links)}

🚌 <b>Другие направления</b>

• {_linked('Аликанте', 'alicante', links)}
• {_linked('Эльче', 'elche', links)}
• {_linked('Ла-Мата', 'south', links)}
• {_linked('Торревьеха', 'south', links)}
• {_linked('ТЦ Zenia Boulevard', 'zenia', links)}
• {_linked('Рохалес', 'inland', links)}
• {_linked('Ориуэла', 'inland', links)}

🎓 {_linked('Университет Аликанте', 'university', links)}
Только в учебный период · для членов ADEUGT"""
    target = "<b>Полезное о Гуардамаре</b>"
    if root_link is not None:
        target = (
            f'<a href="{root_link}"><b>Полезное о Гуардамаре</b></a>'
        )
    return f"{message}\n\n⬅️ {target}"


def build_places(
    polideportivo_link: Optional[str] = None,
    root_link: Optional[str] = None,
    youth_centre_link: Optional[str] = None,
    les_raboses_link: Optional[str] = None,
    molivent_link: Optional[str] = None,
    music_school_link: Optional[str] = None,
) -> str:
    """Build the durable places branch."""

    return _with_back_link(
        with_footer(
            "📍 <b>Места</b>\n\n"
            f"🏟 {_direct_link('Polideportivo Municipal', polideportivo_link)}\n"
            "Муниципальный спортивный комплекс Гуардамара.\n\n"
            f"🏟 {_direct_link('Complejo Deportivo Les Raboses', les_raboses_link)}\n"
            "Муниципальный спортивный комплекс и стадион.\n\n"
            f"🏫 {_direct_link('CEIP Molivent', molivent_link)}\n"
            "Здесь проходят муниципальные занятия для детей.\n\n"
            f"🎼 {_direct_link('Escuela de Música', music_school_link)}\n"
            "Музыкальная школа Agrupación Musical de Guardamar.\n\n"
            f"👥 {_direct_link('Centro Social Juvenil', youth_centre_link)}\n"
            "Пространство для подростков и молодёжи."
        ),
        "Полезное о Гуардамаре",
        root_link,
    )


def build_polideportivo(
    indoor_link: Optional[str] = None,
    outdoor_link: Optional[str] = None,
    places_link: Optional[str] = None,
    palau_link: Optional[str] = None,
) -> str:
    """Build the municipal sports-complex card."""

    palau_target = palau_link or PALAU_SANT_JAUME_MAP_URL
    return _with_back_link(
        with_footer(
            "🏟 <b>Polideportivo Municipal</b>\n\n"
            "Муниципальный спортивный комплекс Гуардамара.\n\n"
            f'📍 <a href="{POLIDEPORTIVO_MAP_URL}"><b>Открыть на карте</b></a>\n\n'
            "<b>Объекты:</b>\n"
            f"🏊 {_direct_link('Крытый бассейн Manel Estiarte', indoor_link)}\n"
            f"☀️ {_direct_link('Открытый муниципальный бассейн', outdoor_link)}\n"
            f"🏟 {_direct_link('Palau Sant Jaume', palau_target)}\n\n"
            "<b>Другие зоны:</b>\n"
            f"🎾 <a href=\"{TENNIS_COURT_MAP_URL}\">теннис и падель</a>\n"
            "💪 тренажёрный зал и калистеника\n"
            "🥎 frontón"
        ),
        "К списку мест",
        places_link,
    )


def build_palau_sant_jaume(
    sport_links: Optional[Mapping[str, str]] = None,
    polideportivo_link: Optional[str] = None,
) -> str:
    """Build the Palau place card and its source-backed activity links."""

    lines = [
        "🏟 <b>Palau Sant Jaume</b>",
        "",
        "Крытый спортивный павильон в составе Polideportivo Municipal.",
        "",
        f'<a href="{PALAU_SANT_JAUME_MAP_URL}">📍 <b>Открыть на карте</b></a>',
        "📞 <b>Телефон:</b> <code>965357693</code>",
        "✉️ <b>Email:</b>",
        f"<code>{SPORTS_CONTACT_EMAIL}</code>",
        "",
        "<b>Внутри:</b>",
        "🏟 Центральная спортивная площадка",
        "🏀 баскетбол · футзал · волейбол · бадминтон",
        "🤸 2 многофункциональных зала",
        "🏋️ Зал силовых тренировок",
    ]
    sport_links = sport_links or {}
    linked_sports = [
        (key, sport_links[key])
        for key in PALAU_ACTIVITY_KEYS
        if key in sport_links
    ]
    if linked_sports:
        lines.extend(["", "🎓 <b>Занятия:</b>"])
        for key, link in linked_sports:
            emoji, label = SPORT_ACTIVITY_META[key]
            lines.append(f"{emoji} {_direct_link(label, link)}")
    return _with_back_link(
        with_footer("\n".join(lines)),
        "Polideportivo Municipal",
        polideportivo_link,
    )


def build_les_raboses(
    deporte_plus_link: Optional[str] = None,
    football_link: Optional[str] = None,
    places_link: Optional[str] = None,
) -> str:
    """Build the durable Les Raboses place card."""

    return _with_back_link(
        with_footer(
            "🏟 <b>Complejo Deportivo Les Raboses</b>\n\n"
            "Муниципальный спортивный комплекс и стадион José García Campillo.\n\n"
            f'📍 <a href="{LES_RABOSES_MAP_URL}"><b>Открыть на карте</b></a>\n\n'
            "<b>Объекты:</b>\n"
            "⚽ 2 футбольных поля\n"
            "🏃 легкоатлетическая дорожка\n"
            "💪 зона калистеники\n"
            "🏹 поле для стрельбы из лука\n\n"
            "🎓 <b>Занятия:</b>\n"
            f"🏃 {_direct_link('DEPORTE +', deporte_plus_link)}\n"
            f"⚽ {_direct_link('Футбол', football_link)}"
        ),
        "К списку мест",
        places_link,
    )


def build_molivent(
    psychomotricity_link: Optional[str] = None,
    places_link: Optional[str] = None,
) -> str:
    """Build the durable CEIP Molivent place card."""

    return _with_back_link(
        with_footer(
            "🏫 <b>CEIP Molivent</b>\n\n"
            "Здесь проходят муниципальные занятия для детей.\n\n"
            f'📍 <a href="{MOLIVENT_MAP_URL}"><b>Открыть на карте</b></a>\n\n'
            "🎓 <b>Занятия:</b>\n"
            f"🧒 {_direct_link('Психомоторика', psychomotricity_link)}"
        ),
        "К списку мест",
        places_link,
    )


def build_music_school(
    music_links: Optional[Mapping[str, str]] = None,
    places_link: Optional[str] = None,
    catalog: Optional[Mapping[str, object]] = None,
    local_day: Optional[date] = None,
) -> str:
    """Build the durable school card shared by music activity cards."""

    lines = [
        "🎼 <b>Escuela de Música</b>",
        "",
        "Музыкальная школа Agrupación Musical de Guardamar.",
        "",
        f'<a href="{html.escape(SCHOOL_MAP_URL, quote=True)}">📍 <b>Открыть на карте</b></a>',
        html.escape(SCHOOL_ADDRESS),
        "",
        f"📞 <b>Телефон:</b> <code>{SCHOOL_PHONE}</code>",
        "✉️ <b>Email:</b>",
        f"<code>{SCHOOL_EMAIL}</code>",
        f'<a href="{html.escape(SCHOOL_SITE_URL, quote=True)}">🌐 <b>Сайт школы</b></a>',
    ]
    music_links = music_links or {}
    linked = [
        (key, music_links[key])
        for key in MUSIC_ACTIVITY_KEYS
        if key in music_links
    ]
    if linked:
        lines.extend(["", "🎓 <b>Занятия:</b>"])
        for key, link in linked:
            emoji, label = MUSIC_ACTIVITY_META[key]
            lines.append(f"{emoji} {_direct_link(label, link)}")

    if catalog is not None:
        if local_day is None:
            raise ValueError("local_day is required with music-school catalogue")
        registration = catalog.get("school_registration")
        if isinstance(registration, Mapping):
            start_raw = registration.get("start")
            end_raw = registration.get("end")
            url = registration.get("url")
            if (
                isinstance(start_raw, str)
                and isinstance(end_raw, str)
                and isinstance(url, str)
                and url
            ):
                start = date.fromisoformat(start_raw)
                end = date.fromisoformat(end_raw)
                if start <= local_day <= end:
                    lines.extend([
                        "",
                        "📝 <b>Matrícula Escuela de Música:</b> "
                        f"до {_format_date_ru(end_raw)}",
                        f'<a href="{html.escape(url, quote=True)}"><b>Открыть форму записи</b></a>',
                    ])
                elif local_day < start:
                    lines.extend([
                        "",
                        "📝 <b>Следующая matrícula:</b> "
                        f"{_format_date_ru(start_raw)} — {_format_date_ru(end_raw)}",
                    ])
    return _with_back_link(
        with_footer("\n".join(lines)),
        "К списку мест",
        places_link,
    )


def build_pool_indoor(
    swimming_link: Optional[str] = None,
    polideportivo_link: Optional[str] = None,
) -> str:
    """Build the indoor municipal pool card."""

    return _with_back_link(
        with_footer(
            "🏊 <b>Крытый бассейн Manel Estiarte</b>\n\n"
            "Работает с <b>16 сентября по 15 июня</b>.\n\n"
            f"📍 <a href=\"{POOL_INDOOR_MAP_URL}\"><b>Открыть на карте</b></a>\n"
            "📞 <b>Телефон:</b> <code>966726593</code>\n\n"
            f"🎓 <b>Занятия:</b> {_direct_link('🏊 Плавание', swimming_link)}."
        ),
        "Polideportivo Municipal",
        polideportivo_link,
    )


def build_pool_outdoor(
    swimming_link: Optional[str] = None,
    polideportivo_link: Optional[str] = None,
) -> str:
    """Build the outdoor municipal pool card."""

    return _with_back_link(
        with_footer(
            "☀️ <b>Открытый муниципальный бассейн</b>\n\n"
            "Работает с <b>16 июня по 15 сентября</b>.\n\n"
            f"📍 <a href=\"{POOL_OUTDOOR_MAP_URL}\"><b>Открыть на карте</b></a>\n"
            "📞 <b>Телефон:</b> <code>966726335</code>\n\n"
            f"🎓 <b>Занятия:</b> {_direct_link('🏊 Плавание', swimming_link)}."
        ),
        "Polideportivo Municipal",
        polideportivo_link,
    )


def build_youth_centre(places_link: Optional[str] = None) -> str:
    """Build the current verified Centro Social Juvenil place card."""

    return _with_back_link(
        with_footer(
            "👥 <b>Centro Social Juvenil</b>\n\n"
            "Пространство для подростков и молодёжи от <b>12 до 30 лет</b>.\n\n"
            "🎲 Настольные игры, настольный футбол, пинг-понг, аэрохоккей, "
            "игровой автомат и другие занятия.\n\n"
            "🕒 <b>Режим работы в сентябре 2026</b>\n"
            "Пн–Пт: 08:30–14:00\n"
            "Ср–Чт: 17:00–21:00\n"
            "Пт: 17:00–22:00\n"
            "Сб: 17:00–22:00\n\n"
            f"📍 <a href=\"{YOUTH_CENTRE_MAP_URL}\"><b>Открыть на карте</b></a>\n"
            "📱 <b>WhatsApp:</b> <code>609006754</code>\n"
            "✉️ <b>Email:</b>\n"
            "<code>juventudguardamar@gmail.com</code>"
        ),
        "К списку мест",
        places_link,
    )



def build_wifi(
    root_link: Optional[str] = None,
    wifi_snapshot: Optional[Mapping[str, object]] = None,
) -> str:
    """Build the municipal Wi-Fi card from the accepted normalized snapshot."""

    if wifi_snapshot is None:
        points = {
            key: {
                "key": key,
                "networks": [
                    {"ssid": ssid, "password": password}
                    for ssid, password in networks
                ],
            }
            for key, networks in WIFI_BASELINE_POINTS
        }
    else:
        points = {
            str(item["key"]): item
            for item in wifi_snapshot.get("points", ())
            if isinstance(item, Mapping) and isinstance(item.get("key"), str)
        }
    lines = [
        "📶 <b>Бесплатный Wi-Fi в Гуардамаре</b>",
        "",
        f"В городе есть <b>{len(points)} муниципальных точек</b> бесплатного Wi-Fi.",
    ]
    if any(
        any(
            isinstance(network, Mapping)
            and network.get("ssid") == "WiFi4EU"
            and network.get("password") is None
            for network in item.get("networks", ())
        )
        for item in points.values()
    ):
        lines.extend([
            "",
            "🔓 <b>WiFi4EU · пароль не нужен</b>",
            "При первом подключении откроется страница входа — достаточно подтвердить подключение. Документ и местная регистрация не нужны.",
        ])
    password_section_added = False
    for key in WIFI_POINT_ORDER:
        item = points.get(key)
        if item is None:
            continue
        networks = tuple(
            network for network in item.get("networks", ())
            if isinstance(network, Mapping)
        )
        if (
            not password_section_added
            and any(network.get("password") is not None for network in networks)
        ):
            lines.extend(["", "🔑 <b>Сети с паролем</b>"])
            password_section_added = True
        emoji, title, address, query = WIFI_POINT_META[key]
        map_url = (
            "https://www.google.com/maps/search/?api=1&query="
            + urllib.parse.quote_plus(query)
        )
        lines.extend([
            "",
            f'{emoji} <a href="{html.escape(map_url, quote=True)}"><b>{html.escape(title)}</b></a>',
        ])
        if address:
            lines.append(f"📍 {html.escape(address)}")
        for network in networks:
            ssid = html.escape(str(network["ssid"]))
            password = network.get("password")
            if key == "library" and password is not None:
                lines.append(
                    f"• <code>{ssid}</code> → 🔑 <code>{html.escape(str(password))}</code>"
                )
            else:
                lines.append(f"📡 <code>{ssid}</code>")
                if password is not None:
                    lines.append(f"🔑 <code>{html.escape(str(password))}</code>")
    body = with_footer("\n".join(lines))
    return _with_back_link(
        body,
        "Полезное о Гуардамаре",
        root_link,
    )


def build_activities(
    swimming_link: Optional[str] = None,
    root_link: Optional[str] = None,
    sport_links: Optional[Mapping[str, str]] = None,
    football_link: Optional[str] = None,
    music_links: Optional[Mapping[str, str]] = None,
    recurring_links: Optional[Mapping[str, str]] = None,
) -> str:
    """Build the recurring activities branch."""

    sport_links = sport_links or {}
    lines = [
        "🎓 <b>Занятия и секции</b>",
        "",
        "🏃 <b>Спорт и движение</b>",
        f"⚽ {_direct_link('Футбол', football_link)}",
        f"🏊 {_direct_link('Плавание', swimming_link)}",
    ]
    for key in SPORT_ACTIVITY_INDEX_KEYS:
        link = sport_links.get(key)
        if link is None:
            continue
        emoji, default_label = SPORT_ACTIVITY_META[key]
        label = SPORT_ACTIVITY_INDEX_LABELS.get(key, default_label)
        lines.append(f"{emoji} {_direct_link(label, link)}")
    music_links = music_links or {}
    linked_music = [
        (key, music_links[key])
        for key in MUSIC_ACTIVITY_KEYS
        if key in music_links
    ]
    if linked_music:
        lines.extend(["", "🎵 <b>Музыка</b>"])
        for key, link in linked_music:
            emoji, default_label = MUSIC_ACTIVITY_META[key]
            label = MUSIC_ACTIVITY_INDEX_LABELS.get(key, default_label)
            lines.append(f"{emoji} {_direct_link(label, link)}")

    recurring_links = recurring_links or {}
    linked_recurring = [
        (key, recurring_links[key])
        for key in RECURRING_ACTIVITY_KEYS
        if key in recurring_links
    ]
    if linked_recurring:
        lines.extend(["", "🧩 <b>Другие занятия</b>"])
        for key, link in linked_recurring:
            emoji, label = RECURRING_ACTIVITY_META[key]
            lines.append(f"{emoji} {_direct_link(label, link)}")
    return _with_back_link(
        with_footer("\n".join(lines)),
        "Полезное о Гуардамаре",
        root_link,
    )


_RU_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def _format_date_ru(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {_RU_MONTHS[parsed.month]} {parsed.year}"


def _venue_markup(
    value: str,
    palau_link: Optional[str] = None,
    les_raboses_link: Optional[str] = None,
    molivent_link: Optional[str] = None,
) -> str:
    if value.startswith("Palau Sant Jaume"):
        remainder = value[len("Palau Sant Jaume"):].lstrip(" .")
        target = palau_link or PALAU_SANT_JAUME_MAP_URL
        result = f'<a href="{target}"><b>Palau Sant Jaume</b></a>'
        if remainder:
            result += f" · {html.escape(remainder)}"
        return result
    if value.startswith("Complejo Deportivo Les Raboses"):
        remainder = value[len("Complejo Deportivo Les Raboses"):].lstrip(" .")
        target = les_raboses_link or LES_RABOSES_MAP_URL
        result = (
            f'<a href="{target}"><b>Complejo Deportivo Les Raboses</b></a>'
        )
        if remainder:
            result += f" · {html.escape(remainder)}"
        return result
    if value.startswith("CEIP Molivent"):
        remainder = value[len("CEIP Molivent"):].lstrip(" .")
        target = molivent_link or MOLIVENT_MAP_URL
        result = f'<a href="{target}"><b>CEIP Molivent</b></a>'
        if remainder:
            result += f" · {html.escape(remainder)}"
        return result
    return html.escape(value)


def _registration_signature(group: Mapping[str, object]):
    return (
        tuple(
            (entry["start"], entry["end"])
            for entry in group["registrations"]
        ),
        group["registration_until_full"],
    )


def _registration_line(
    group: Mapping[str, object], local_day: date
) -> Optional[str]:
    intervals = [
        (date.fromisoformat(item["start"]), date.fromisoformat(item["end"]))
        for item in group["registrations"]
    ]
    current = next(
        (interval for interval in intervals if interval[0] <= local_day <= interval[1]),
        None,
    )
    if current is not None:
        text = f"📝 <b>Запись:</b> до {_format_date_ru(current[1].isoformat())}"
    else:
        future = [interval for interval in intervals if interval[0] > local_day]
        if not future:
            return None
        start, end = min(future, key=lambda interval: interval[0])
        text = (
            "📝 <b>Следующая запись:</b> "
            f"{_format_date_ru(start.isoformat())} — "
            f"{_format_date_ru(end.isoformat())}"
        )
    if group["registration_until_full"]:
        text += " · до заполнения мест"
    return text


def _registration_is_open(
    group: Mapping[str, object], local_day: date
) -> bool:
    return any(
        date.fromisoformat(item["start"])
        <= local_day
        <= date.fromisoformat(item["end"])
        for item in group["registrations"]
    )


def _group_label(key: str, group: Mapping[str, object]) -> str:
    if key in {"women_gymnastics", "deporte_plus"}:
        return "Группа"
    suffix = {1: "1-я", 2: "2-я", 3: "3-я", 4: "4-я"}.get(
        group["group_order"],
        f'{group["group_order"]}-я',
    )
    return f"{suffix} группа"


def build_sport_activity(
    key: str,
    catalog: Mapping[str, object],
    local_day: date,
    activities_link: Optional[str] = None,
    palau_link: Optional[str] = None,
    les_raboses_link: Optional[str] = None,
    molivent_link: Optional[str] = None,
) -> str:
    """Build one source-backed municipal activity card."""

    if key not in SPORT_ACTIVITY_META:
        raise ValueError(f"unknown sport activity key: {key}")
    emoji, title = SPORT_ACTIVITY_META[key]
    groups = select_sport_groups(catalog, key, local_day)
    lines = [f"{emoji} <b>{title}</b>"]
    if not groups:
        lines.extend(
            [
                "",
                "Сейчас актуальные муниципальные группы не опубликованы.",
                "",
                f'<a href="{SPORTTIA_CENTER_URL}"><b>Проверить запись</b></a>',
            ]
        )
        return _with_back_link(
            with_footer("\n".join(lines)),
            "К занятиям и секциям",
            activities_link,
        )

    first = groups[0]
    lines.extend(
        [
            "",
            "🗓 <b>Сезон:</b> "
            f"{_format_date_ru(first['season_start'])} — "
            f"{_format_date_ru(first['season_end'])}",
        ]
    )

    venues = {group["venue"] for group in groups}
    common_venue = next(iter(venues)) if len(venues) == 1 else None
    if common_venue is not None:
        lines.append(
            "📍 "
            + _venue_markup(
                common_venue,
                palau_link,
                les_raboses_link,
                molivent_link,
            )
        )

    registrations = {_registration_signature(group) for group in groups}
    common_registration = len(registrations) == 1
    if common_registration:
        registration = _registration_line(first, local_day)
        if registration is not None:
            lines.append(registration)

    lines.append("")
    for group in groups:
        label = _group_label(key, group)
        group_line = f"• <b>{html.escape(label)}</b>"
        audience = group.get("audience")
        if audience:
            group_line += f" · {html.escape(audience)}"
        lines.append(group_line)
        if key == "inclusive_multisport":
            if group["independent"]:
                lines.append("  👤 Самостоятельное участие")
            elif group["requires_companion"]:
                lines.append("  👥 С сопровождающим взрослым")
        lines.append(f"  {html.escape(group['schedule'])}")
        if common_venue is None:
            lines.append(
                "  📍 "
                + _venue_markup(
                    group["venue"],
                    palau_link,
                    les_raboses_link,
                    molivent_link,
                )
            )
        if not common_registration:
            registration = _registration_line(group, local_day)
            if registration is not None:
                lines.append(f"  {registration}")
        if group["racket_sports"]:
            lines.append("  🎾 Ракеточные виды спорта")
        activity_url = html.escape(group["activity_url"], quote=True)
        if _registration_is_open(group, local_day):
            lines.append(
                f'  📝 <a href="{activity_url}">Записаться</a>'
            )
        else:
            lines.append(
                f'  🔎 <a href="{activity_url}">Страница группы</a>'
            )

    if key == "deporte_plus":
        lines.extend(
            [
                "",
                "🏉 flag rugby · полоса препятствий · лёгкая атлетика",
            ]
        )

    notes = []
    if any(group["group_may_change"] for group in groups):
        notes.append("ℹ️ Группы могут корректироваться организаторами.")
    if any(group["medical_certificate"] for group in groups):
        notes.extend(
            [
                "📄 После записи нужна спортивная медсправка.",
                f'📎 <a href="{SPORT_MEDICAL_CERTIFICATE_URL}">Скачать бланк</a>',
                "✉️ <b>Отправить справку:</b>",
                f"<code>{SPORTS_CONTACT_EMAIL}</code>",
            ]
        )
    if any(group["women_membership"] for group in groups):
        notes.append(
            "👩 Также требуется подтверждение членского взноса "
            "Asociación Mujeres de Guardamar."
        )
    if notes:
        lines.append("")
        lines.extend(notes)

    return _with_back_link(
        with_footer("\n".join(lines)),
        "К занятиям и секциям",
        activities_link,
    )


def _music_place_line(school_link: Optional[str]) -> str:
    return "  📍 " + _direct_link(
        "Escuela de Música",
        school_link or SCHOOL_MAP_URL,
    )


def _append_music_schedule(
    lines: list,
    catalog: Mapping[str, object],
) -> None:
    url = catalog.get("schedule_url")
    season = catalog.get("season")
    if not isinstance(url, str) or not url:
        return
    label = "Расписание групп"
    if isinstance(season, str) and season:
        label += f" {html.escape(season)}"
    lines.append(
        f'  📅 <a href="{html.escape(url, quote=True)}">{label}</a>'
    )


def build_music_activity(
    key: str,
    catalog: Mapping[str, object],
    local_day: date,
    activities_link: Optional[str] = None,
    school_link: Optional[str] = None,
) -> str:
    """Build one compact music card; school contacts stay on the place card."""

    if key not in MUSIC_ACTIVITY_META:
        raise ValueError(f"unknown music activity key: {key}")
    emoji, title = MUSIC_ACTIVITY_META[key]
    lines = [f"{emoji} <b>{title}</b>", ""]

    if key == "music_basics":
        lines.extend([
            "• <b>Jardín Musical</b> · 3–6 лет",
            "  1 час в неделю · занятия Пн–Чт",
        ])
        if music_registration_is_open(
            catalog, "jardin_registration", local_day
        ):
            registration = catalog.get("jardin_registration")
            if isinstance(registration, Mapping):
                url = registration.get("url")
                if isinstance(url, str) and url:
                    lines.append(
                        f'  📝 <a href="{html.escape(url, quote=True)}">Записаться</a>'
                    )
        lines.append(_music_place_line(school_link))
        lines.extend([
            "",
            "• <b>Lenguaje Musical</b> · с 7 лет",
            "  2 часа в неделю",
        ])
        _append_music_schedule(lines, catalog)
        lines.append(_music_place_line(school_link))
        lines.extend([
            "",
            "• <b>Lenguaje Musical para Adultos</b> · 18+",
        ])
        _append_music_schedule(lines, catalog)
        lines.append(_music_place_line(school_link))
    elif key == "music_vocal":
        lines.append("• <b>Técnica Vocal / Coro</b>")
        _append_music_schedule(lines, catalog)
        lines.append(_music_place_line(school_link))
    else:
        lines.extend([
            "• <b>Духовые инструменты</b>",
            "  кларнет · саксофон · флейта · гобой · фагот",
            "  труба · тромбон · валторна · эуфониум · туба",
            _music_place_line(school_link),
            "",
            "• <b>Другие инструменты</b>",
            "  ударные · виолончель · дульсайна · гитара · Piano Complementario",
            _music_place_line(school_link),
        ])

    return _with_back_link(
        with_footer("\n".join(lines)),
        "К занятиям и секциям",
        activities_link,
    )


def build_chess_activity(
    snapshot: Mapping[str, object],
    activities_link: Optional[str] = None,
) -> str:
    """Build the current source-backed chess-school card."""

    source_url = html.escape(str(snapshot["source_url"]), quote=True)
    start_time = html.escape(str(snapshot["start_time"]))
    end_time = html.escape(str(snapshot["end_time"]))
    level_from = str(snapshot["level_from"])
    level_to = str(snapshot["level_to"])
    if (level_from, level_to) == ("INICIACIÓN", "AVANZADO"):
        level_line = "Школа шахмат — от начинающего до продвинутого уровня."
    else:
        level_line = (
            "Школа шахмат · уровни: "
            f"{html.escape(level_from)}–{html.escape(level_to)}."
        )
    message = with_footer(
        "♟️ <b>Шахматы</b>\n\n"
        f"{level_line}\n\n"
        f"🗓 <b>Вторник и четверг · {start_time}–{end_time}</b>\n"
        "Конкретное время зависит от уровня группы.\n\n"
        f'🔎 <a href="{source_url}"><b>Информация о занятиях</b></a>'
    )
    return _with_back_link(
        message,
        "К занятиям и секциям",
        activities_link,
    )


def build_literary_activity(
    snapshot: Mapping[str, object],
    activities_link: Optional[str] = None,
) -> str:
    """Build the current Tertulia Literaria card."""

    source_url = html.escape(str(snapshot["source_url"]), quote=True)
    start_time = html.escape(str(snapshot["start_time"]))
    end_time = html.escape(str(snapshot["end_time"]))
    if snapshot.get("venue") != "library_auditorium":
        raise ValueError("unknown literary-group venue")
    venue_line = "📍 Актовый зал муниципальной библиотеки"
    message = with_footer(
        "✍️ <b>Литературное творчество</b>\n\n"
        "<b>Tertulia Literaria de Guardamar</b>\n"
        "Еженедельная литературная группа.\n\n"
        f"🗓 <b>Каждый вторник · {start_time}–{end_time}</b>\n"
        f"{venue_line}\n\n"
        f'🔎 <a href="{source_url}"><b>Подробнее</b></a>'
    )
    return _with_back_link(
        message,
        "К занятиям и секциям",
        activities_link,
    )


def _short_date_ru(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {_RU_MONTHS[parsed.month]}"


def build_dinamizacion_activity(
    snapshot: Mapping[str, object],
    local_day: date,
    activities_link: Optional[str] = None,
) -> str:
    """Build the current Dinamización Social aggregate card."""

    season = html.escape(str(snapshot["season"]))
    lines = [
        "🤝 <b>Муниципальные занятия и мастерские</b>",
        "",
        f"Программа Dinamización Social {season}.",
        "",
    ]
    for group in snapshot["groups"]:
        key = group["key"]
        title = DINAMIZACION_GROUP_TITLES.get(key, str(key))
        lines.append(f"• <b>{html.escape(title)}</b>")
        for schedule in group["schedules"]:
            lines.append(f"  {html.escape(schedule)}")
        start_date = group.get("start_date")
        end_date = group.get("end_date")
        if isinstance(start_date, str) and isinstance(end_date, str):
            lines.append(
                f"  {_short_date_ru(start_date)} — {_short_date_ru(end_date)}"
            )
        elif isinstance(start_date, str):
            lines.append(f"  С {_short_date_ru(start_date)}")
        lines.append("")
    if lines[-1] == "":
        lines.pop()

    registration_start = date.fromisoformat(snapshot["registration_start"])
    registration_end = date.fromisoformat(snapshot["registration_end"])
    lines.append("")
    if local_day < registration_start:
        lines.append(
            "📝 <b>Запись:</b> "
            f"{_short_date_ru(snapshot['registration_start'])} — "
            f"{_short_date_ru(snapshot['registration_end'])}"
        )
    elif local_day <= registration_end:
        lines.append(
            "📝 <b>Запись:</b> до "
            f"{_short_date_ru(snapshot['registration_end'])}"
        )
    else:
        lines.extend([
            "📝 Основной период записи завершился "
            f"{_short_date_ru(snapshot['registration_end'])}.",
            "После него запись может продолжаться, пока остаются места.",
        ])

    if snapshot.get("resident_priority") is True:
        lines.extend(["", "🏠 Приоритет — жителям Guardamar."])

    form_url = html.escape(str(snapshot["form_url"]), quote=True)
    lines.extend([
        "",
        f'📝 <a href="{form_url}"><b>Форма записи</b></a>',
    ])
    return _with_back_link(
        with_footer("\n".join(lines)),
        "К занятиям и секциям",
        activities_link,
    )


def build_football(
    activities_link: Optional[str] = None,
    les_raboses_link: Optional[str] = None,
) -> str:
    """Build the durable static Guardamar Soccer C.D. activity card."""

    return _with_back_link(
        with_footer(
            "⚽ <b>Футбол</b>\n\n"
            "Детско-юношеская школа Guardamar Soccer C.D.\n\n"
            f"📍 {_venue_markup('Complejo Deportivo Les Raboses', les_raboses_link=les_raboses_link)}\n\n"
            "📱 <b>Телефон:</b> <code>698953390</code>\n"
            "✉️ <b>Email:</b>\n"
            f"<code>{FOOTBALL_EMAIL}</code>\n"
            f'📝 <a href="{FOOTBALL_FORM_URL}"><b>Онлайн-форма клуба</b></a>\n\n'
            "ℹ️ Группу по возрасту, расписание тренировок и условия участия "
            "уточняйте у клуба."
        ),
        "К занятиям и секциям",
        activities_link,
    )


def build_swimming(
    indoor_link: Optional[str] = None,
    outdoor_link: Optional[str] = None,
    activities_link: Optional[str] = None,
) -> str:
    """Build the safe swimming card without inferring current availability."""

    return _with_back_link(
        with_footer(
            "🏊 <b>Плавание</b>\n\n"
            "Актуальные группы и запись зависят от сезона.\n\n"
            f"🏊 {_direct_link('Крытый бассейн Manel Estiarte', indoor_link)}\n"
            "16 сентября - 15 июня.\n\n"
            f"☀️ {_direct_link('Открытый муниципальный бассейн', outdoor_link)}\n"
            "16 июня - 15 сентября.\n\n"
            f"📝 <a href=\"{AQUALIDER_BOOKING_URL}\"><b>Проверить группы и запись</b></a>"
        ),
        "К занятиям и секциям",
        activities_link,
    )


def build_fishing(root_link: Optional[str] = None) -> str:
    """Build the compact stable marine-fishing reference card."""

    return _with_back_link(
        with_footer(
            "🎣 <b>Рыбалка</b>\n\n"
            "🗓 <b>Купальный сезон:</b> 1 июня–30 сентября, а также "
            "Semana Santa — с пятницы перед Вербным воскресеньем по "
            "понедельник после Пасхального понедельника включительно.\n\n"
            "🏖 <b>Морская рыбалка с берега</b>\n"
            "В зонах купания <b>Centre, La Roqueta, Babilònia, El Moncaio</b> "
            "в купальный сезон рыбалка запрещена <b>круглосуточно</b>.\n"
            "На <b>Els Tossals, Dels Vivers, El Camp, Les Ortigues</b> "
            "в купальный сезон рыбалка запрещена с <b>09:00 до 21:00</b>.\n"
            "Даже в разрешённое время рыбалка допускается только при отсутствии "
            "пользователей на пляже; если появляются купающиеся, снасти нужно убрать.\n"
            "👥 В любом случае — более <b>100 м</b> от пользователей пляжа.\n"
            "🚤 В бализованных каналах спуска на воду и подъёма судов рыбачить "
            "запрещено.\n\n"
            "🤿 <b>Подводная морская рыбалка</b>\n"
            "В купальный сезон <b>в зонах купания запрещена</b>.\n"
            "Вне этих зон и дат — только при отсутствии купающихся. Ночью — от "
            "заката до восхода — запрещена; заметный сигнальный буй обязателен.\n\n"
            "⚓ В портовых водах рыбалка запрещена, если для конкретного "
            "порта не установлено исключение.\n\n"
            "📄 Нужна соответствующая лицензия. "
            f'<a href="{FISHING_GVA_LICENSE_URL}"><b>Условия и оформление — '
            "Generalitat Valenciana</b></a>.\n"
            f'📱 <a href="{FISHING_PESCAREC_URL}"><b>PescaREC — размеры, '
            "ограничения и декларация улова</b></a>\n"
            f'🚦 <a href="{FISHING_RESTRICTIONS_URL}"><b>Актуальные '
            "разрешения и запреты на вылов</b></a>"
        ),
        "Полезное о Гуардамаре",
        root_link,
    )


def build_root(
    camera_link: Optional[str] = None,
    transport_link: Optional[str] = None,
    places_link: Optional[str] = None,
    activities_link: Optional[str] = None,
    wifi_link: Optional[str] = None,
    fishing_link: Optional[str] = None,
) -> str:
    """Build the compact message intended to remain pinned."""

    return (
        "📌 <b>Полезное о Гуардамаре</b>\n\n"
        f"📹 {_direct_link('Онлайн-камеры', camera_link)}\n\n"
        f"🚌 {_direct_link('Транспорт в Гуардамаре', transport_link)}\n\n"
        f"📍 {_direct_link('Места', places_link)}\n\n"
        f"📶 {_direct_link('Бесплатный Wi-Fi', wifi_link)}\n\n"
        f"🎣 {_direct_link('Рыбалка', fishing_link)}\n\n"
        f"🎓 {_direct_link('Занятия и секции', activities_link)}"
    )


def preview_messages() -> Sequence[str]:
    """Return the exact text sequence for a private operator preview."""

    return (
        *(build_leaf_message(key) for key in LEAF_MESSAGES),
        build_cameras(),
        build_transport_index(),
        build_places(),
        build_polideportivo(),
        build_pool_indoor(),
        build_pool_outdoor(),
        build_palau_sant_jaume(),
        build_les_raboses(),
        build_molivent(),
        build_music_school(),
        build_youth_centre(),
        build_wifi(),
        build_fishing(),
        build_activities(),
        build_swimming(),
        build_football(),
        build_root(),
    )


class PinnedGuideState:
    """Small atomic state for recoverable linked-message publication."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_payload(self, chat_id: str) -> dict:
        if not self.path.exists():
            return {
                "version": PINNED_CONTENT_VERSION,
                "chat_id": chat_id,
                "messages": {},
                "lines": {},
                "obsolete_messages": [],
                "uncertain_messages": [],
            }
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            previous = self.path.with_name(
                f"{self.path.stem}.previous.json"
            )
            try:
                raw = json.loads(previous.read_text(encoding="utf-8"))
            except (
                OSError, UnicodeDecodeError, json.JSONDecodeError
            ):
                raise StateError("pinned guide state is invalid") from exc
        if (
            not isinstance(raw, dict)
            or raw.get("version") not in {1, PINNED_CONTENT_VERSION}
            or raw.get("chat_id") != chat_id
            or not isinstance(raw.get("messages"), dict)
        ):
            raise StateError("pinned guide state is invalid")
        messages = raw["messages"]
        if not all(
            isinstance(key, str)
            and isinstance(value, int)
            and value > 0
            for key, value in messages.items()
        ):
            raise StateError("pinned guide state is invalid")
        lines = raw.get("lines", {})
        if not isinstance(lines, dict) or not all(
            key in {"line_1", "line_2"} and isinstance(value, dict)
            for key, value in lines.items()
        ):
            raise StateError("pinned guide state is invalid")
        obsolete = raw.get("obsolete_messages", [])
        if not isinstance(obsolete, list) or not all(
            isinstance(value, int) and value > 0 for value in obsolete
        ):
            raise StateError("pinned guide state is invalid")
        uncertain = raw.get("uncertain_messages", [])
        if not isinstance(uncertain, list) or not all(
            isinstance(value, str) for value in uncertain
        ):
            raise StateError("pinned guide state is invalid")
        return {
            "version": PINNED_CONTENT_VERSION,
            "chat_id": chat_id,
            "messages": dict(messages),
            "lines": {key: dict(value) for key, value in lines.items()},
            "obsolete_messages": list(obsolete),
            "uncertain_messages": list(uncertain),
        }

    def read(self, chat_id: str) -> Dict[str, int]:
        return dict(self.read_payload(chat_id)["messages"])

    def _atomic_write(self, path: Path, payload: dict) -> None:
        descriptor, temporary = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}."
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            directory = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def write_payload(self, chat_id: str, payload: dict) -> None:
        if payload.get("chat_id") != chat_id:
            raise StateError("pinned guide state is invalid")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalized = {
            "version": PINNED_CONTENT_VERSION,
            "chat_id": chat_id,
            "messages": dict(payload.get("messages", {})),
            "lines": {
                key: dict(value)
                for key, value in payload.get("lines", {}).items()
            },
            "obsolete_messages": list(
                payload.get("obsolete_messages", [])
            ),
            "uncertain_messages": list(
                payload.get("uncertain_messages", [])
            ),
        }
        previous = self.path.with_name(f"{self.path.stem}.previous.json")
        if self.path.exists():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                existing = None
            if isinstance(existing, dict):
                self._atomic_write(previous, existing)
        self._atomic_write(self.path, normalized)

    def write(self, chat_id: str, messages: Mapping[str, int]) -> None:
        try:
            payload = self.read_payload(chat_id)
        except StateError:
            if self.path.exists():
                raise
            payload = {
                "version": PINNED_CONTENT_VERSION,
                "chat_id": chat_id,
                "messages": {},
                "lines": {},
                "obsolete_messages": [],
                "uncertain_messages": [],
            }
        payload["messages"] = dict(messages)
        self.write_payload(chat_id, payload)

    def mark_uncertain(self, chat_id: str, key: str) -> None:
        payload = self.read_payload(chat_id)
        if key not in payload["uncertain_messages"]:
            payload["uncertain_messages"].append(key)
        self.write_payload(chat_id, payload)

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        """Prevent two guide publications from creating duplicate messages."""

        lock_path = self.path.with_name(f".{self.path.name}.lock")
        lock_file = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = lock_path.open("a", encoding="utf-8")
            fcntl.flock(
                lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError(
                "another pinned guide publication is already active"
            ) from exc
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            raise StateError("pinned guide state could not be locked") from exc
        try:
            yield
        finally:
            assert lock_file is not None
            lock_file.close()


async def _upsert(
    key: str,
    text: str,
    messages: Dict[str, int],
    state: PinnedGuideState,
    chat_id: str,
    send: Send,
    edit: Edit,
) -> int:
    message_id = messages.get(key)
    if message_id is not None:
        try:
            await edit(message_id, text)
            return message_id
        except TelegramError as exc:
            if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
                return message_id
            if exc.diagnostic_code != "MESSAGE-NOT-FOUND":
                raise
    try:
        message_id = await send(text)
    except TelegramError as exc:
        if is_ambiguous_send_failure(exc):
            await asyncio.to_thread(state.mark_uncertain, chat_id, key)
        raise
    messages[key] = message_id
    await asyncio.to_thread(state.write, chat_id, messages)
    return message_id


def _known_link(
    chat_id: str,
    messages: Mapping[str, int],
    key: str,
) -> Optional[str]:
    message_id = messages.get(key)
    if message_id is None:
        return None
    return telegram_message_link(chat_id, message_id)


def _render_messages(
    chat_id: str,
    messages: Mapping[str, int],
    wifi_snapshot: Optional[Mapping[str, object]] = None,
) -> Dict[str, str]:
    """Render the best complete link graph possible from known identifiers."""

    transport_link = _known_link(chat_id, messages, "transport")
    root_link = _known_link(chat_id, messages, "root")
    places_link = _known_link(chat_id, messages, "places")
    polideportivo_link = _known_link(chat_id, messages, "polideportivo")
    palau_link = _known_link(chat_id, messages, "palau_sant_jaume")
    les_raboses_link = _known_link(chat_id, messages, "les_raboses")
    molivent_link = _known_link(chat_id, messages, "molivent")
    music_school_link = _known_link(chat_id, messages, "music_school")
    youth_centre_link = _known_link(chat_id, messages, "youth_centre")
    wifi_link = _known_link(chat_id, messages, "wifi")
    fishing_link = _known_link(chat_id, messages, "fishing")
    activities_link = _known_link(chat_id, messages, "activities")
    football_link = _known_link(chat_id, messages, "football")
    sport_links = {}
    for key in SPORTTIA_ACTIVITY_KEYS:
        link = _known_link(chat_id, messages, key)
        if link is not None:
            sport_links[key] = link
    music_links = {}
    for key in MUSIC_ACTIVITY_KEYS:
        link = _known_link(chat_id, messages, key)
        if link is not None:
            music_links[key] = link
    recurring_links = {}
    for key in RECURRING_ACTIVITY_KEYS:
        link = _known_link(chat_id, messages, key)
        if link is not None:
            recurring_links[key] = link
    leaf_links = None
    if all(key in messages for key in LEAF_MESSAGES):
        leaf_links = {
            key: telegram_message_link(chat_id, messages[key])
            for key in LEAF_MESSAGES
        }
    swimming_link = _known_link(chat_id, messages, "swimming")
    indoor_link = _known_link(chat_id, messages, "pool_indoor")
    outdoor_link = _known_link(chat_id, messages, "pool_outdoor")
    return {
        **{
            key: build_leaf_message(key, transport_link)
            for key in LEAF_MESSAGES
        },
        "cameras": build_cameras(root_link),
        "transport": build_transport_index(leaf_links, root_link),
        "places": build_places(
            polideportivo_link,
            root_link,
            youth_centre_link,
            les_raboses_link,
            molivent_link,
            music_school_link,
        ),
        "polideportivo": build_polideportivo(
            indoor_link,
            outdoor_link,
            places_link,
            palau_link=palau_link,
        ),
        "pool_indoor": build_pool_indoor(swimming_link, polideportivo_link),
        "pool_outdoor": build_pool_outdoor(swimming_link, polideportivo_link),
        "palau_sant_jaume": build_palau_sant_jaume(
            sport_links, polideportivo_link
        ),
        "les_raboses": build_les_raboses(
            sport_links.get("deporte_plus"),
            football_link,
            places_link,
        ),
        "molivent": build_molivent(
            sport_links.get("psychomotricity"),
            places_link,
        ),
        "music_school": build_music_school(music_links, places_link),
        "youth_centre": build_youth_centre(places_link),
        "wifi": build_wifi(root_link, wifi_snapshot),
        "fishing": build_fishing(root_link),
        "activities": build_activities(
            swimming_link,
            root_link,
            sport_links,
            football_link,
            music_links,
            recurring_links,
        ),
        "swimming": build_swimming(
            indoor_link, outdoor_link, activities_link
        ),
        "football": build_football(activities_link, les_raboses_link),
        "root": build_root(
            _known_link(chat_id, messages, "cameras"),
            transport_link,
            places_link,
            activities_link,
            wifi_link,
            fishing_link,
        ),
    }


async def _reconcile_messages(
    chat_id: str,
    messages: Dict[str, int],
    state: PinnedGuideState,
    send: Send,
    edit: Edit,
    skip_keys: Sequence[str] = (),
    wifi_snapshot: Optional[Mapping[str, object]] = None,
) -> None:
    """Converge IDs and links after partial runs or deleted messages."""

    skipped = frozenset(skip_keys)
    keys = tuple(key for key in PINNED_MESSAGE_KEYS if key not in skipped)
    for _ in range(MAX_RECONCILIATION_PASSES):
        before = dict(messages)
        rendered = _render_messages(chat_id, before, wifi_snapshot)
        for key in keys:
            await _upsert(
                key,
                rendered[key],
                messages,
                state,
                chat_id,
                send,
                edit,
            )
        if messages == before:
            return
    raise StateError(
        "pinned guide messages changed during every recovery pass"
    )


async def publish_pinned_guide(
    chat_id: str,
    state: PinnedGuideState,
    send: Send,
    edit: Edit,
    pin: Pin,
    skip_keys: Sequence[str] = (),
    sporttia_catalog: Optional[Mapping[str, object]] = None,
    music_school_catalog: Optional[Mapping[str, object]] = None,
    chess_school_snapshot: Optional[Mapping[str, object]] = None,
    literary_group_snapshot: Optional[Mapping[str, object]] = None,
    dinamizacion_snapshot: Optional[Mapping[str, object]] = None,
    wifi_snapshot: Optional[Mapping[str, object]] = None,
    local_day: Optional[date] = None,
) -> Dict[str, int]:
    """Create or update all linked messages, then pin the compact root."""

    telegram_message_link(chat_id, 1)
    if sporttia_catalog is not None and local_day is None:
        raise ValueError("local_day is required with Sporttia catalogue")
    if music_school_catalog is not None and local_day is None:
        raise ValueError("local_day is required with music-school catalogue")
    if dinamizacion_snapshot is not None and local_day is None:
        raise ValueError("local_day is required with Dinamización snapshot")
    payload = await asyncio.to_thread(state.read_payload, chat_id)
    if payload["uncertain_messages"]:
        raise StateError(
            "a previous pinned guide delivery has an uncertain result"
        )
    messages = payload["messages"]
    managed_elsewhere = tuple(
        key for key, value in payload["lines"].items()
        if value.get("media") is True and key in messages
    ) + tuple(key for key in skip_keys if key in messages)
    await _reconcile_messages(
        chat_id, messages, state, send, edit, managed_elsewhere, wifi_snapshot
    )
    if sporttia_catalog is not None:
        assert local_day is not None
        activities_link = _known_link(chat_id, messages, "activities")
        palau_link = _known_link(chat_id, messages, "palau_sant_jaume")
        les_raboses_link = _known_link(chat_id, messages, "les_raboses")
        molivent_link = _known_link(chat_id, messages, "molivent")
        for key in SPORTTIA_ACTIVITY_KEYS:
            groups = select_sport_groups(sporttia_catalog, key, local_day)
            if key not in messages and not groups:
                continue
            await _upsert(
                key,
                build_sport_activity(
                    key,
                    sporttia_catalog,
                    local_day,
                    activities_link,
                    palau_link,
                    les_raboses_link,
                    molivent_link,
                ),
                messages,
                state,
                chat_id,
                send,
                edit,
            )
        await _reconcile_messages(
            chat_id, messages, state, send, edit, managed_elsewhere, wifi_snapshot
        )
    if music_school_catalog is not None:
        assert local_day is not None
        activities_link = _known_link(chat_id, messages, "activities")
        school_link = _known_link(chat_id, messages, "music_school")
        for key in MUSIC_ACTIVITY_KEYS:
            await _upsert(
                key,
                build_music_activity(
                    key,
                    music_school_catalog,
                    local_day,
                    activities_link,
                    school_link,
                ),
                messages,
                state,
                chat_id,
                send,
                edit,
            )
        await _reconcile_messages(
            chat_id, messages, state, send, edit, managed_elsewhere, wifi_snapshot
        )

    activities_link = _known_link(chat_id, messages, "activities")
    recurring_payloads = []
    if chess_school_snapshot is not None:
        recurring_payloads.append((
            "chess",
            build_chess_activity(chess_school_snapshot, activities_link),
        ))
    if literary_group_snapshot is not None:
        recurring_payloads.append((
            "literary_group",
            build_literary_activity(literary_group_snapshot, activities_link),
        ))
    if dinamizacion_snapshot is not None:
        assert local_day is not None
        recurring_payloads.append((
            "dinamizacion",
            build_dinamizacion_activity(
                dinamizacion_snapshot,
                local_day,
                activities_link,
            ),
        ))
    for key, message in recurring_payloads:
        await _upsert(
            key,
            message,
            messages,
            state,
            chat_id,
            send,
            edit,
        )
    if recurring_payloads:
        await _reconcile_messages(
            chat_id, messages, state, send, edit, managed_elsewhere, wifi_snapshot
        )
    try:
        await pin(messages["root"])
    except TelegramError as exc:
        if exc.diagnostic_code != "MESSAGE-NOT-FOUND":
            raise
        messages.pop("root", None)
        await asyncio.to_thread(state.write, chat_id, messages)
        await _reconcile_messages(
            chat_id, messages, state, send, edit, managed_elsewhere, wifi_snapshot
        )
        await pin(messages["root"])
    if music_school_catalog is not None:
        assert local_day is not None
        music_links = {
            key: telegram_message_link(chat_id, messages[key])
            for key in MUSIC_ACTIVITY_KEYS
            if key in messages
        }
        previous_school_id = messages.get("music_school")
        await _upsert(
            "music_school",
            build_music_school(
                music_links,
                _known_link(chat_id, messages, "places"),
                music_school_catalog,
                local_day,
            ),
            messages,
            state,
            chat_id,
            send,
            edit,
        )
        if messages.get("music_school") != previous_school_id:
            school_link = _known_link(chat_id, messages, "music_school")
            activities_link = _known_link(chat_id, messages, "activities")
            for key in MUSIC_ACTIVITY_KEYS:
                await _upsert(
                    key,
                    build_music_activity(
                        key,
                        music_school_catalog,
                        local_day,
                        activities_link,
                        school_link,
                    ),
                    messages,
                    state,
                    chat_id,
                    send,
                    edit,
                )
            await _reconcile_messages(
                chat_id,
                messages,
                state,
                send,
                edit,
                (*managed_elsewhere, "music_school"),
                wifi_snapshot,
            )
            music_links = {
                key: telegram_message_link(chat_id, messages[key])
                for key in MUSIC_ACTIVITY_KEYS
                if key in messages
            }
            await _upsert(
                "music_school",
                build_music_school(
                    music_links,
                    _known_link(chat_id, messages, "places"),
                    music_school_catalog,
                    local_day,
                ),
                messages,
                state,
                chat_id,
                send,
                edit,
            )
    return messages
