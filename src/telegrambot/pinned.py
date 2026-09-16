"""Static linked city guide and one-shot Telegram publication."""

import asyncio
import fcntl
import html
import json
import os
import tempfile
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
from .sporttia import (
    SPORTTIA_ACTIVITY_KEYS,
    SPORTTIA_CENTER_URL,
    select_sport_groups,
)
from .state import StateError
from .telegram import TelegramError

PINNED_CONTENT_VERSION = 2
DEFAULT_PINNED_STATE_PATH = "state/pinned_guide.json"
MAX_RECONCILIATION_PASSES = 3
AQUALIDER_BOOKING_URL = "https://aqualidernatacion.simplybook.it/v2/"
AIRPORT_STOP_MAP_URL = "https://maps.app.goo.gl/V3REb7P6CmdJtgom7"
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


WIFI = with_footer(
    """📶 <b>Бесплатный Wi-Fi в Гуардамаре</b>

В городе есть <b>7 муниципальных точек</b> бесплатного Wi-Fi.

🔓 <b>WiFi4EU · пароль не нужен</b>
При первом подключении откроется страница входа — достаточно подтвердить подключение. Документ и местная регистрация не нужны.

🎵 <a href="https://www.google.com/maps/search/?api=1&amp;query=Escola+de+M%C3%BAsica%2C+C%2F+Mercat+2%2C+Guardamar+del+Segura"><b>Escola de Música</b></a>
📍 C/ Mercat, 2
📡 <code>WiFi4EU</code>

🎭 <a href="https://www.google.com/maps/search/?api=1&amp;query=Casa+de+Cultura%2C+C%2F+Col%C3%B3n+60%2C+Guardamar+del+Segura"><b>Casa de Cultura</b></a>
📍 C/ Colón, 60
📡 <code>WiFi4EU</code>

🌴 <a href="https://www.google.com/maps/search/?api=1&amp;query=Avenida+Los+Pinos%2C+Guardamar+del+Segura"><b>Avda. Los Pinos</b></a>
📡 <code>WiFi4EU</code>

🔑 <b>Сети с паролем</b>

🏛 <a href="https://www.google.com/maps/search/?api=1&amp;query=Plaza+de+la+Constituci%C3%B3n%2C+Guardamar+del+Segura"><b>Plaza de la Constitución</b></a>
📡 <code>vegafibra_gratis</code>
🔑 <code>vegafibra</code>

🌊 <a href="https://www.google.com/maps/search/?api=1&amp;query=Paseo+Mar%C3%ADtimo%2C+Avenida+de+Europa%2C+Guardamar+del+Segura"><b>Paseo Marítimo · Avda. de Europa</b></a>
📡 <code>vegafibra_gratis</code>
🔑 <code>vegafibra</code>

📚 <a href="https://www.google.com/maps/search/?api=1&amp;query=C%2F+Mayor+69%2C+Guardamar+del+Segura"><b>Sala de Estudios 24/365</b></a>
📍 C/ Mayor, 69
📡 <code>wifi_1EO9C</code>
🔑 <code>vegafibra</code>

📖 <a href="https://www.google.com/maps/search/?api=1&amp;query=Biblioteca+P%C3%BAblica%2C+C%2F+San+Jaime+5%2C+Guardamar+del+Segura"><b>Biblioteca Pública</b></a>
📍 C/ San Jaime, 5
• <code>wifibiblioteca</code> → 🔑 <code>biblimar</code>
• <code>biblioteca infantil</code> → 🔑 <code>menjallibres</code>
• <code>vicenteramos</code> → 🔑 <code>menjallibres</code>"""
)


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
<a href="https://www.google.com/maps/search/?api=1&amp;query=38.087834%2C-0.655759">автовокзал Гуардамара</a> ↔ <a href="{AIRPORT_STOP_MAP_URL}">остановка у терминала аэропорта</a>

🕒 <a href="https://www.bus-siguenza.com/index.php?page=urbano">Найти расписание на нужную дату</a>"""
    ),
    "hospital": with_footer(
        """🏥 <b>Гуардамар ↔ Hospital de Torrevieja</b>
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
<a href="https://www.google.com/maps/search/?api=1&amp;query=38.0877707496%2C-0.6560185196">Guardamar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0583071959%2C-0.6569832033">La Rosa</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0241372606%2C-0.6570898059">La Mata</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a>

<b>Обратно</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0262439991%2C-0.655954">La Mata</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0560738544%2C-0.6568971718">La Rosa</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0877707496%2C-0.6560185196">Guardamar</a>

ℹ️ <a href="https://www.gva.es/es/web/arees/infraestructures-i-transports/-/asset_publisher/21dbI2RUgqwC/content/nuevas-concesiones-de-atuob%25C3%259As-en-la-comarca-de-la-vega-baja/20081096?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_21dbI2RUgqwC_assetEntryId=412097993">Подробнее о линии</a>"""
    ),
    "alicante": with_footer(
        """🚌 <b>Гуардамар ↔ Alicante</b>
Доехать можно без пересадок на автобусе Avanza.

По дороге автобус заезжает в La Marina, Santa Pola и El Altet.

📍 <b>Откуда и куда</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Carrer+Molivent%2C+Guardamar+del+Segura">автовокзал Гуардамара</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses+de+Alicante">автовокзал в Alicante</a>

🕒 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Найти расписание на нужную дату</a>"""
    ),
    "elche": with_footer(
        """🚌 <b>Гуардамар ↔ Elche</b>
Доехать можно без пересадок на автобусе Avanza.

По дороге автобус заезжает в San Fulgencio, Dolores, Catral и Crevillente.

📍 <b>Откуда и куда</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Carrer+Molivent%2C+Guardamar+del+Segura">автовокзал Гуардамара</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Av.+Vicente+Quiles%2C+Elche">остановка на проспекте Vicente Quiles в Elche</a>

🕒 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Найти расписание на нужную дату</a>"""
    ),
    "south": with_footer(
        """🚌 <b>Гуардамар ↔ Torrevieja ↔ Pilar de la Horadada</b>
До Torrevieja и Pilar de la Horadada можно доехать без пересадок на автобусе Avanza.

По дороге автобус проходит через La Rosa, Pinomar, La Mata, Playa Flamenca, Zenia Boulevard, Campoamor и Mil Palmeras.

📍 <b>Основные остановки</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Carrer+Molivent%2C+Guardamar+del+Segura">Гуардамар</a> → <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+del+Mar+40%2C+Torrevieja">Torrevieja</a> → <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Emilio+Tarraga+18%2C+Pilar+de+la+Horadada">Pilar de la Horadada</a>

🕒 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Найти расписание на нужную дату</a>
🛍 <a href="https://regular.autobusing.com/info/horarios?empresa=costa-azul&amp;venta%5Borigen_nombre%5D=GUARDAMAR&amp;venta%5Bdestino_nombre%5D=C.C.%20BOULEVAR%20ZENIA">Посмотреть рейсы до Zenia Boulevard</a>"""
    ),
    "inland": with_footer(
        """🚌 <b>Гуардамар ↔ Orihuela</b>
Доехать можно без пересадок на автобусе Bus Sigüenza.

По дороге автобус заезжает в Daya Vieja, Rojales, Formentera del Segura, Las Heredades, Daya Nueva, Almoradí, Hospital Vega Baja, Benejúzar, Jacarilla и Bigastro.

📍 <b>Откуда и куда</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">автовокзал Гуардамара</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Orihuela">автовокзал в Orihuela</a>

🕒 <a href="https://www.bus-siguenza.com/index.php?page=urbano">Найти расписание на нужную дату</a>"""
    ),
    "university": with_footer(
        """🎓 <b>Гуардамар ↔ Universidad de Alicante</b>
В учебный период до университета ходит прямой автобус Avanza.

Для поездки нужно быть членом ADEUGT.

📍 <b>Где садиться</b>

<b>В университет</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Pintor+Sorolla+2%2C+Guardamar+del+Segura">улица Pintor Sorolla, 2</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">автовокзал Гуардамара</a>

<b>Обратно</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">автовокзал Гуардамара</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Pintor+Sorolla+1%2C+Guardamar+del+Segura">улица Pintor Sorolla, 1</a>

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
    "youth_centre",
    "wifi",
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
    "youth_centre": "places",
    "wifi": "root",
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
• {_linked('ТЦ Zenia Boulevard', 'south', links)}
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


def build_wifi(root_link: Optional[str] = None) -> str:
    """Build the verified municipal Wi-Fi card."""

    return _with_back_link(
        WIFI,
        "Полезное о Гуардамаре",
        root_link,
    )


def build_activities(
    swimming_link: Optional[str] = None,
    root_link: Optional[str] = None,
    sport_links: Optional[Mapping[str, str]] = None,
    football_link: Optional[str] = None,
) -> str:
    """Build the recurring activities branch."""

    sport_links = sport_links or {}
    lines = [
        "🎓 <b>Занятия и секции</b>",
        "",
        "🏃 <b>Спорт и движение</b>",
        f"🏊 {_direct_link('Плавание', swimming_link)}",
    ]
    for key in SPORTTIA_ACTIVITY_KEYS:
        link = sport_links.get(key)
        if link is None:
            continue
        emoji, label = SPORT_ACTIVITY_META[key]
        lines.append(f"{emoji} {_direct_link(label, link)}")
    lines.append(f"⚽ {_direct_link('Футбол', football_link)}")
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


def build_root(
    camera_link: Optional[str] = None,
    transport_link: Optional[str] = None,
    places_link: Optional[str] = None,
    activities_link: Optional[str] = None,
    wifi_link: Optional[str] = None,
) -> str:
    """Build the compact message intended to remain pinned."""

    return (
        "📌 <b>Полезное о Гуардамаре</b>\n\n"
        f"📹 {_direct_link('Онлайн-камеры', camera_link)}\n\n"
        f"🚌 {_direct_link('Транспорт в Гуардамаре', transport_link)}\n\n"
        f"📍 {_direct_link('Места', places_link)}\n\n"
        f"📶 {_direct_link('Бесплатный Wi-Fi', wifi_link)}\n\n"
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
        build_youth_centre(),
        build_wifi(),
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
        if exc.retryable and exc.server_status != 429:
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
) -> Dict[str, str]:
    """Render the best complete link graph possible from known identifiers."""

    transport_link = _known_link(chat_id, messages, "transport")
    root_link = _known_link(chat_id, messages, "root")
    places_link = _known_link(chat_id, messages, "places")
    polideportivo_link = _known_link(chat_id, messages, "polideportivo")
    palau_link = _known_link(chat_id, messages, "palau_sant_jaume")
    les_raboses_link = _known_link(chat_id, messages, "les_raboses")
    molivent_link = _known_link(chat_id, messages, "molivent")
    youth_centre_link = _known_link(chat_id, messages, "youth_centre")
    wifi_link = _known_link(chat_id, messages, "wifi")
    activities_link = _known_link(chat_id, messages, "activities")
    football_link = _known_link(chat_id, messages, "football")
    sport_links = {}
    for key in SPORTTIA_ACTIVITY_KEYS:
        link = _known_link(chat_id, messages, key)
        if link is not None:
            sport_links[key] = link
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
        "youth_centre": build_youth_centre(places_link),
        "wifi": build_wifi(root_link),
        "activities": build_activities(
            swimming_link,
            root_link,
            sport_links,
            football_link,
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
        ),
    }


async def _reconcile_messages(
    chat_id: str,
    messages: Dict[str, int],
    state: PinnedGuideState,
    send: Send,
    edit: Edit,
    skip_keys: Sequence[str] = (),
) -> None:
    """Converge IDs and links after partial runs or deleted messages."""

    skipped = frozenset(skip_keys)
    keys = tuple(key for key in PINNED_MESSAGE_KEYS if key not in skipped)
    for _ in range(MAX_RECONCILIATION_PASSES):
        before = dict(messages)
        rendered = _render_messages(chat_id, before)
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
    local_day: Optional[date] = None,
) -> Dict[str, int]:
    """Create or update all linked messages, then pin the compact root."""

    telegram_message_link(chat_id, 1)
    if sporttia_catalog is not None and local_day is None:
        raise ValueError("local_day is required with Sporttia catalogue")
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
        chat_id, messages, state, send, edit, managed_elsewhere
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
            chat_id, messages, state, send, edit, managed_elsewhere
        )
    try:
        await pin(messages["root"])
    except TelegramError as exc:
        if exc.diagnostic_code != "MESSAGE-NOT-FOUND":
            raise
        messages.pop("root", None)
        await asyncio.to_thread(state.write, chat_id, messages)
        await _reconcile_messages(
            chat_id, messages, state, send, edit, managed_elsewhere
        )
        await pin(messages["root"])
    return messages
