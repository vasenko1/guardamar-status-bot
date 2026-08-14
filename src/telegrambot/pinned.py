"""Static linked city guide and one-shot Telegram publication."""

import asyncio
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
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

from .branding import with_footer
from .state import StateError
from .telegram import TelegramError

PINNED_CONTENT_VERSION = 1
DEFAULT_PINNED_STATE_PATH = "state/pinned_guide.json"

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


LEAF_MESSAGES: Dict[str, str] = {
    "line_1": with_footer(
        """🚌 <b>Городской автобус · Линия 1</b>
Puerto Deportivo ↔ Plaza Constitución ↔ Av. del Mediterráneo ↔ Campomar

🗓 <b>Июль и август:</b> каждый день
🗓 <b>С сентября по июнь:</b> с понедельника по субботу; по воскресеньям действует отдельное расписание

Рейсы со звёздочкой проходят через Los Secanos и кладбище. Остановка La Redona, 56 используется утром по рыночным дням.

🔎 <a href="https://www.guardamardelsegura.es/wp-content/uploads/2026/04/L01_v6-Guardamar.pdf">Проверьте расписание</a>"""
    ),
    "line_2": with_footer(
        """🚌 <b>Городской автобус · Линия 2</b>
Polideportivo ↔ Estación de Autobuses ↔ El Raso ↔ El Edén ↔ Pinomar

🗓 <b>Июль и август:</b> каждый день
🗓 <b>С сентября по июнь:</b> с понедельника по субботу; по воскресеньям действует отдельное расписание

Остановка La Redona, 56 используется только по средам.

🔎 <a href="https://www.guardamardelsegura.es/wp-content/uploads/2026/04/L02_v3-Guardamar.pdf">Проверьте расписание</a>"""
    ),
    "airport": with_footer(
        """✈️ <b>Гуардамар ↔ аэропорт Alicante-Elche</b>
Прямой автобус · Bus Sigüenza

🗓 <b>Каждый день</b>

Зимой рейсов меньше, летом добавляются дополнительные.

📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">Estación de Autobuses</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=38.288404274%2C-0.552487159">автобусная зона терминала</a>

🔎 <a href="https://www.bus-siguenza.com/index.php?page=urbano">Проверьте расписание</a>"""
    ),
    "hospital": with_footer(
        """🏥 <b>Гуардамар ↔ Hospital de Torrevieja</b>
Прямой автобус · с понедельника по пятницу

Один рейс утром в больницу и один обратно после обеда.

<b>В больницу</b>
07:30 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0877707496%2C-0.6560185196">Guardamar</a>
07:33 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0583071959%2C-0.6569832033">La Rosa</a>
07:36 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a>
07:40 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0241372606%2C-0.6570898059">La Mata</a>
07:55 · <a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a>

<b>Обратно</b>
13:00 · <a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a>
13:15 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0262439991%2C-0.655954">La Mata</a>
13:18 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a>
13:22 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0560738544%2C-0.6568971718">La Rosa</a>
13:25 · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0877707496%2C-0.6560185196">Guardamar</a>

⏱ Около 25 минут
📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">Estación de Autobuses</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Hospital+Universitario+de+Torrevieja">Hospital de Torrevieja</a>

🔎 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Проверьте расписание</a>"""
    ),
    "alicante": with_footer(
        """🚌 <b>Гуардамар ↔ Alicante</b>
Прямой автобус · Costa Azul / Avanza

По пути автобус останавливается в La Marina, Santa Pola и El Altet.

📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Carrer+Molivent%2C+Guardamar+del+Segura">Estación de Autobuses, Guardamar</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses+de+Alicante">Estación de Autobuses, Alicante</a>

🔎 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Проверьте расписание</a>"""
    ),
    "elche": with_footer(
        """🚌 <b>Гуардамар ↔ Elche</b>
Прямой автобус · Costa Azul / Avanza

Маршрут проходит через San Fulgencio, Dolores, Catral и Crevillente.

📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Carrer+Molivent%2C+Guardamar+del+Segura">Estación de Autobuses, Guardamar</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Av.+Vicente+Quiles%2C+Elche">остановка Av. Vicente Quiles, Elche</a>

🔎 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Проверьте расписание</a>"""
    ),
    "south": with_footer(
        """🚌 <b>Гуардамар ↔ Torrevieja ↔ Pilar de la Horadada</b>
Прямой автобус · Costa Azul / Avanza

По пути: La Rosa, Pinomar, La Mata, Playa Flamenca, Zenia Boulevard, Campoamor и Mil Palmeras.

📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Carrer+Molivent%2C+Guardamar+del+Segura">Guardamar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+del+Mar+40%2C+Torrevieja">Torrevieja</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Emilio+Tarraga+18%2C+Pilar+de+la+Horadada">Pilar de la Horadada</a>

🔎 <a href="https://regular.autobusing.com/info?empresa=costa-azul&amp;locale=es">Проверьте расписание</a>"""
    ),
    "inland": with_footer(
        """🚌 <b>Гуардамар ↔ Orihuela</b>
Прямой автобус · Bus Sigüenza

По пути: Daya Vieja, Rojales, Formentera del Segura, Las Heredades, Daya Nueva, Almoradí, Hospital Vega Baja, Benejúzar, Jacarilla и Bigastro.

📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">Guardamar</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Orihuela">Orihuela</a>

🔎 <a href="https://www.bus-siguenza.com/index.php?page=urbano">Проверьте расписание</a>"""
    ),
    "university": with_footer(
        """🎓 <b>Гуардамар ↔ Universidad de Alicante</b>
Прямой автобус · Costa Azul / Avanza

🗓 <b>В учебный период</b>

Для поездки необходимо быть членом ADEUGT.

<b>В университет</b>
📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Pintor+Sorolla+2%2C+Guardamar+del+Segura">Calle Pintor Sorolla, 2</a>
📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">Estación de Autobuses</a>

<b>Обратно</b>
📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Estaci%C3%B3n+de+Autobuses%2C+Guardamar+del+Segura">Estación de Autobuses</a>
📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=Calle+Pintor+Sorolla+1%2C+Guardamar+del+Segura">Calle Pintor Sorolla, 1</a>

🔎 <a href="https://web.ua.es/es/oia/transporte-universitario/vega-baja.html">Расписание и условия ADEUGT</a>"""
    ),
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


def build_transport_index(
    links: Optional[Mapping[str, str]] = None,
) -> str:
    """Build the transport navigator with live links or preview labels."""

    return with_footer(
        f"""🧭 <b>Транспорт из Гуардамара</b>

Только прямые маршруты, без пересадок. Нажмите на нужное направление, чтобы открыть расписание с остановками.

🏙 <b>По городу</b>

• {_linked('Линия 1', 'line_1', links)} · Puerto Deportivo ↔ центр ↔ Campomar
• {_linked('Линия 2', 'line_2', links)} · Polideportivo ↔ El Raso ↔ El Edén ↔ Pinomar

✈️ <b>Аэропорт</b>

• {_linked('Alicante-Elche', 'airport', links)} · Bus Sigüenza

🏥 <b>Больница</b>

• {_linked('Hospital de Torrevieja', 'hospital', links)}

🚌 <b>Другие направления</b>

• {_linked('Alicante', 'alicante', links)} · через La Marina, Santa Pola и El Altet
• {_linked('Elche', 'elche', links)} · через San Fulgencio, Dolores, Catral и Crevillente
• {_linked('Torrevieja и Pilar de la Horadada', 'south', links)}
• {_linked('Rojales, Formentera del Segura, Almoradí и Orihuela', 'inland', links)}

🎓 <b>Учёба</b>

• {_linked('Universidad de Alicante', 'university', links)} · в учебный период, для членов ADEUGT"""
    )


def build_root(
    camera_link: Optional[str] = None,
    transport_link: Optional[str] = None,
) -> str:
    """Build the compact message intended to remain pinned."""

    if camera_link is None or transport_link is None:
        cameras = "<b>Камеры Гуардамара</b>"
        transport = "<b>Транспорт из Гуардамара</b>"
    else:
        cameras = f'<a href="{camera_link}"><b>Камеры Гуардамара</b></a>'
        transport = (
            f'<a href="{transport_link}"><b>Транспорт из Гуардамара</b></a>'
        )
    return with_footer(
        "📌 <b>Полезное о Гуардамаре</b>\n\n"
        f"📹 {cameras}\n"
        f"🚌 {transport}"
    )


def preview_messages() -> Sequence[str]:
    """Return the exact text sequence for a private operator preview."""

    return (
        *LEAF_MESSAGES.values(),
        CAMERAS,
        build_transport_index(),
        build_root(),
    )


class PinnedGuideState:
    """Small atomic state for recoverable linked-message publication."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self, chat_id: str) -> Dict[str, int]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("pinned guide state is invalid") from exc
        if (
            not isinstance(raw, dict)
            or raw.get("version") != PINNED_CONTENT_VERSION
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
        return dict(messages)

    def write(self, chat_id: str, messages: Mapping[str, int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PINNED_CONTENT_VERSION,
            "chat_id": chat_id,
            "messages": dict(messages),
        }
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}."
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

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
            if exc.server_status != 400:
                raise
    message_id = await send(text)
    messages[key] = message_id
    await asyncio.to_thread(state.write, chat_id, messages)
    return message_id


async def publish_pinned_guide(
    chat_id: str,
    state: PinnedGuideState,
    send: Send,
    edit: Edit,
    pin: Pin,
) -> Dict[str, int]:
    """Create or update all linked messages, then pin the compact root."""

    telegram_message_link(chat_id, 1)
    messages = await asyncio.to_thread(state.read, chat_id)
    for key, text in LEAF_MESSAGES.items():
        await _upsert(key, text, messages, state, chat_id, send, edit)
    camera_id = await _upsert(
        "cameras", CAMERAS, messages, state, chat_id, send, edit
    )
    leaf_links = {
        key: telegram_message_link(chat_id, messages[key])
        for key in LEAF_MESSAGES
    }
    transport_id = await _upsert(
        "transport",
        build_transport_index(leaf_links),
        messages,
        state,
        chat_id,
        send,
        edit,
    )
    root_id = await _upsert(
        "root",
        build_root(
            telegram_message_link(chat_id, camera_id),
            telegram_message_link(chat_id, transport_id),
        ),
        messages,
        state,
        chat_id,
        send,
        edit,
    )
    await pin(root_id)
    return messages
