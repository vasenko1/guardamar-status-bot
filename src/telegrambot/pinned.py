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

from .branding import FOOTER, with_footer
from .state import StateError
from .telegram import TelegramError

PINNED_CONTENT_VERSION = 2
DEFAULT_PINNED_STATE_PATH = "state/pinned_guide.json"
MAX_RECONCILIATION_PASSES = 3

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

Сообщение с рейсами на текущую дату обновляется каждое утро.

📍 <a href="https://www.google.com/maps/search/?api=1&amp;query=38.087834%2C-0.655759">Estación de Autobuses</a> ↔ <a href="https://www.google.com/maps/search/?api=1&amp;query=38.282222222222%2C-0.55805555555556">остановка аэропорта</a>

🔎 <a href="https://www.bus-siguenza.com/index.php?page=urbano">Проверьте расписание</a>"""
    ),
    "hospital": with_footer(
        """🏥 <b>Гуардамар ↔ Hospital de Torrevieja</b>
Линия 6 · Costa Azul / Avanza

🗓 <b>С понедельника по пятницу, в рабочие дни</b>

<b>Гуардамар → Hospital de Torrevieja</b>
07:30 · 09:00 · 11:00 · 13:00 · 15:00 · 17:30

<b>Hospital de Torrevieja → Гуардамар</b>
08:00 · 09:30 · 11:30 · 13:30 · 15:30 · 18:00

🗓 <b>Суббота, воскресенье и праздники</b>

<b>Гуардамар → Hospital de Torrevieja</b>
07:30 · 09:00 · 13:00 · 16:30

<b>Hospital de Torrevieja → Гуардамар</b>
08:00 · 09:30 · 13:30 · 17:00

⏱ Около 30 минут

<b>В больницу</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=38.0877707496%2C-0.6560185196">Guardamar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0583071959%2C-0.6569832033">La Rosa</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0241372606%2C-0.6570898059">La Mata</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a>

<b>Обратно</b>
<a href="https://www.google.com/maps/search/?api=1&amp;query=37.9643925369%2C-0.7172232255">Hospital de Torrevieja</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0262439991%2C-0.655954">La Mata</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.034828419%2C-0.6600459049">Pinomar</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0560738544%2C-0.6568971718">La Rosa</a> · <a href="https://www.google.com/maps/search/?api=1&amp;query=38.0877707496%2C-0.6560185196">Guardamar</a>

🔎 <a href="https://www.gva.es/es/web/arees/infraestructures-i-transports/-/asset_publisher/21dbI2RUgqwC/content/nuevas-concesiones-de-atuob%25C3%259As-en-la-comarca-de-la-vega-baja/20081096?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_21dbI2RUgqwC_assetEntryId=412097993">Информация о линии</a>"""
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
        "К главному закрепу",
        root_link,
    )


def build_transport_index(
    links: Optional[Mapping[str, str]] = None,
    root_link: Optional[str] = None,
) -> str:
    """Build the transport navigator with live links or preview labels."""

    message = with_footer(
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
    return _with_back_link(
        message,
        "К главному закрепу",
        root_link,
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
        *(build_leaf_message(key) for key in LEAF_MESSAGES),
        build_cameras(),
        build_transport_index(),
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
    leaf_links = None
    if all(key in messages for key in LEAF_MESSAGES):
        leaf_links = {
            key: telegram_message_link(chat_id, messages[key])
            for key in LEAF_MESSAGES
        }
    return {
        **{
            key: build_leaf_message(key, transport_link)
            for key in LEAF_MESSAGES
        },
        "cameras": build_cameras(root_link),
        "transport": build_transport_index(leaf_links, root_link),
        "root": build_root(
            _known_link(chat_id, messages, "cameras"),
            transport_link,
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
    keys = tuple(
        key for key in (*LEAF_MESSAGES, "cameras", "transport", "root")
        if key not in skipped
    )
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
) -> Dict[str, int]:
    """Create or update all linked messages, then pin the compact root."""

    telegram_message_link(chat_id, 1)
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
