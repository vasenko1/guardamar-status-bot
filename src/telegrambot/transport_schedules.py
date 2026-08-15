"""Bounded one-shot synchronization of the two official urban timetables."""

import asyncio
import hashlib
import html
import http.client
import json
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Dict, Mapping, Optional

from .branding import FOOTER, with_footer
from .pinned import PinnedGuideState, build_transport_index, telegram_message_link
from .telegram import TelegramError

INDEX_URL = (
    "https://www.guardamardelsegura.es/wp-json/wp/v2/posts"
    "?slug=horarios-de-autobuses&_fields=id,modified,content"
)
ALLOWED_HOSTS = frozenset({"www.guardamardelsegura.es"})
PDF_LIMIT_BYTES = 5_000_000
INDEX_LIMIT_BYTES = 128_000
REQUEST_TIMEOUT_SECONDS = 20
RENDER_TIMEOUT_SECONDS = 45
MAX_PHOTO_BYTES = 10_000_000
MAX_DIMENSION_SUM = 9_500
USER_AGENT = "GuardamarMorningDigest/0.13"


class TransportScheduleError(RuntimeError):
    """Safe bounded failure in timetable synchronization."""


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise TransportScheduleError(
                "transport source redirected outside allowlist"
            )
        return super().redirect_request(
            request, fp, code, msg, headers, newurl
        )


@dataclass(frozen=True)
class DownloadedPdf:
    payload: bytes
    url: str
    etag: Optional[str]
    last_modified: Optional[str]


@dataclass(frozen=True)
class LineDefinition:
    key: str
    label: str
    route: str
    reviewed_summary: str
    default_url: str
    filename_marker: str
    reviewed_sha256: str
    reviewed_note: str


LINES: Dict[str, LineDefinition] = {
    "line_1": LineDefinition(
        key="line_1",
        label="Линия 1",
        route=(
            "Puerto Deportivo ↔ Plaza Constitución ↔ "
            "Av. del Mediterráneo ↔ Campomar"
        ),
        reviewed_summary=(
            "Маршрут соединяет Puerto Deportivo (порт), центр Гуардамара, "
            "автовокзал, пляжную зону, Hotel Playas de Guardamar и "
            "Campomar. Автобус ходит в обоих направлениях."
        ),
        default_url=(
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/04/L01_v6-Guardamar.pdf"
        ),
        filename_marker="l01_",
        reviewed_sha256=(
            "8ca65b756b78575060290f8ccd8917fd87e09bb48c7d3d9120ae2505432f8e33"
        ),
        reviewed_note=(
            "⭐ Рейсы, отмеченные звёздочкой, дополнительно заезжают "
            "в Los Secanos.\n\n"
            "🛍 В дни работы рынка, обычно по средам утром, автобус "
            "останавливается рядом с рынком: La Redona, 56."
        ),
    ),
    "line_2": LineDefinition(
        key="line_2",
        label="Линия 2",
        route=(
            "Polideportivo ↔ Estación de Autobuses ↔ El Raso ↔ "
            "El Edén ↔ Pinomar"
        ),
        reviewed_summary=(
            "Маршрут соединяет Polideportivo (спортивный комплекс) и "
            "автовокзал с районами Pórtico Mediterráneo, El Raso, "
            "Campico, El Edén, Los Estaños, La Rosa и Pinomar. Автобус "
            "ходит в обоих направлениях."
        ),
        default_url=(
            "https://www.guardamardelsegura.es/wp-content/uploads/"
            "2026/04/L02_v3-Guardamar.pdf"
        ),
        filename_marker="l02_",
        reviewed_sha256=(
            "088c21040b10a18e87ecfd353b1474d9ef1cc07d925a33fd4ac6d4f583ea9425"
        ),
        reviewed_note=(
            "🛍 По средам автобус также останавливается рядом с рынком: "
            "La Redona, 56."
        ),
    ),
}

SendPhoto = Callable[[Path, str], Awaitable[tuple[int, str]]]
EditMedia = Callable[[int, Path, str], Awaitable[str]]
EditCaption = Callable[[int, str], Awaitable[None]]
EditText = Callable[[int, str], Awaitable[None]]
Delete = Callable[[int], Awaitable[None]]


def _allowed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


def _open_bounded(request: urllib.request.Request, limit: int) -> tuple:
    if not _allowed_url(request.full_url):
        raise TransportScheduleError("transport URL is not allowed")
    opener = urllib.request.build_opener(_AllowedRedirectHandler())
    try:
        response = opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return b"", request.full_url, exc.headers, 304
        raise TransportScheduleError(
            f"transport source returned HTTP {exc.code}"
        ) from None
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise TransportScheduleError("transport source is unavailable") from exc
    with response:
        final_url = response.geturl()
        if not _allowed_url(final_url):
            raise TransportScheduleError("transport source redirected outside allowlist")
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise TransportScheduleError("transport source response is too large")
        return payload, final_url, response.headers, response.status


def discover_pdf_urls() -> Dict[str, str]:
    request = urllib.request.Request(
        INDEX_URL,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    payload, _, headers, status = _open_bounded(request, INDEX_LIMIT_BYTES)
    if status != 200 or headers.get_content_type() != "application/json":
        raise TransportScheduleError("transport index has an invalid response")
    try:
        decoded = json.loads(payload.decode("utf-8"))
        rendered = decoded[0]["content"]["rendered"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        raise TransportScheduleError("transport index is invalid") from None
    if not isinstance(rendered, str):
        raise TransportScheduleError("transport index has no content")
    links = re.findall(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', rendered, re.I)
    result: Dict[str, str] = {}
    for raw_url in links:
        url = html.unescape(raw_url)
        if not _allowed_url(url):
            continue
        filename = Path(urllib.parse.urlparse(url).path).name.casefold()
        for key, definition in LINES.items():
            if definition.filename_marker in filename:
                result[key] = url
    if set(result) != set(LINES):
        raise TransportScheduleError("transport index does not list both urban lines")
    return result


def download_pdf(
    url: str,
    etag: Optional[str],
    last_modified: Optional[str],
    *,
    force: bool = False,
) -> Optional[DownloadedPdf]:
    headers = {
        "Accept": "application/pdf",
        "User-Agent": USER_AGENT,
    }
    if not force and etag:
        headers["If-None-Match"] = etag
    if not force and last_modified:
        headers["If-Modified-Since"] = last_modified
    request = urllib.request.Request(url, headers=headers)
    payload, final_url, response_headers, status = _open_bounded(
        request, PDF_LIMIT_BYTES
    )
    if status == 304:
        return None
    if status != 200 or response_headers.get_content_type() != "application/pdf":
        raise TransportScheduleError("transport PDF has an invalid response")
    if not payload.startswith(b"%PDF-"):
        raise TransportScheduleError("transport PDF signature is invalid")
    return DownloadedPdf(
        payload=payload,
        url=final_url,
        etag=response_headers.get("ETag"),
        last_modified=response_headers.get("Last-Modified"),
    )


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=RENDER_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise TransportScheduleError(
            f"required renderer is missing: {command[0]}"
        ) from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise TransportScheduleError("transport PDF rendering failed") from exc


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise TransportScheduleError("renderer produced an invalid PNG")
    return struct.unpack(">II", data[16:24])


def render_pdf(payload: bytes, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(destination.parent)) as directory:
        temporary = Path(directory)
        source = temporary / "schedule.pdf"
        source.write_bytes(payload)
        info = _run(["pdfinfo", str(source)]).stdout.decode("utf-8", "replace")
        pages = re.search(r"(?mi)^Pages:\s*(\d+)\s*$", info)
        if pages is None or pages.group(1) != "1":
            raise TransportScheduleError("transport PDF must contain one page")
        prefix = temporary / "schedule"
        _run([
            "pdftoppm", "-f", "1", "-singlefile", "-r", "120",
            "-png", str(source), str(prefix),
        ])
        rendered = prefix.with_suffix(".png")
        width, height = _png_dimensions(rendered)
        if width + height > MAX_DIMENSION_SUM:
            _run([
                "pdftoppm", "-f", "1", "-singlefile", "-scale-to", "4500",
                "-png", str(source), str(prefix),
            ])
            width, height = _png_dimensions(rendered)
        size = rendered.stat().st_size
        if width + height > MAX_DIMENSION_SUM or size > MAX_PHOTO_BYTES:
            raise TransportScheduleError("rendered timetable exceeds Telegram limits")
        staged = destination.with_name(f".{destination.name}.new")
        shutil.copyfile(rendered, staged)
        with staged.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(staged, destination)
        directory_fd = os.open(str(destination.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def build_line_caption(
    definition: LineDefinition,
    now: datetime,
    transport_link: str,
    reviewed: bool,
) -> str:
    if reviewed and now.month in {7, 8}:
        period = "🗓 <b>В июле и августе:</b> автобус ходит ежедневно."
    elif reviewed:
        period = (
            "🗓 <b>С сентября по июнь:</b> с понедельника по субботу. "
            "По воскресеньям действует отдельное расписание."
        )
    else:
        period = "🗓 Актуальные дни и время отправления указаны на изображении."
    summary = definition.reviewed_summary if reviewed else definition.route
    note = f"\n\n{definition.reviewed_note}" if reviewed else ""
    message = with_footer(
        f"🚌 <b>Городской автобус · {definition.label}</b>\n"
        f"{summary}\n\n"
        f"{period}{note}\n\n"
        f'⬅️ <a href="{transport_link}"><b>К списку транспорта</b></a>'
    )
    if len(message) > 1024 or message.count(FOOTER) != 1 or "—" in message:
        raise TransportScheduleError("transport caption is not Telegram-safe")
    return message


def _replace_image(current: Path, candidate: Path) -> None:
    previous = current.with_name(current.name.replace("-current", "-previous"))
    if current.exists():
        os.replace(current, previous)
    os.replace(candidate, current)
    directory_fd = os.open(str(current.parent), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


async def sync_transport_schedules(
    now: datetime,
    chat_id: str,
    state: PinnedGuideState,
    send_photo: SendPhoto,
    edit_media: EditMedia,
    edit_caption: EditCaption,
    edit_text: EditText,
    delete: Delete,
) -> Mapping[str, int]:
    """Refresh sources and converge the two timetable photo messages."""

    payload = await asyncio.to_thread(state.read_payload, chat_id)
    messages = payload["messages"]
    if "transport" not in messages or "root" not in messages:
        raise TransportScheduleError("pinned guide must be published before media sync")
    transport_link = telegram_message_link(chat_id, messages["transport"])
    try:
        urls = await asyncio.to_thread(discover_pdf_urls)
    except TransportScheduleError as exc:
        logging.warning("Transport index unavailable; using accepted URLs: %s", exc)
        urls = {
            key: payload["lines"].get(key, {}).get(
                "source_url", definition.default_url
            )
            for key, definition in LINES.items()
        }

    image_directory = state.path.parent / "transport"
    image_directory.mkdir(parents=True, exist_ok=True)
    replacements: Dict[str, tuple[int, int]] = {}
    force = now.day == 1

    for key, definition in LINES.items():
        line_state = dict(payload["lines"].get(key, {}))
        if line_state.get("delivery_uncertain") is True:
            raise TransportScheduleError(
                f"{definition.label}: previous Telegram delivery is uncertain"
            )
        source_url = urls[key]
        downloaded: Optional[DownloadedPdf] = None
        try:
            downloaded = await asyncio.to_thread(
                download_pdf,
                source_url,
                line_state.get("etag"),
                line_state.get("last_modified"),
                force=force,
            )
        except TransportScheduleError as exc:
            logging.warning("%s source unavailable; keeping accepted media: %s", key, exc)

        current_image = image_directory / f"{key}-current.png"
        previous_image = image_directory / f"{key}-previous.png"
        if not current_image.exists() and previous_image.exists():
            shutil.copyfile(previous_image, current_image)
        candidate_image = image_directory / f".{key}-candidate.png"
        if downloaded is not None:
            try:
                pdf_sha = hashlib.sha256(downloaded.payload).hexdigest()
                if pdf_sha != line_state.get("pdf_sha256"):
                    confirmation = await asyncio.to_thread(
                        download_pdf, downloaded.url, None, None, force=True
                    )
                    if (
                        confirmation is None
                        or confirmation.payload != downloaded.payload
                    ):
                        raise TransportScheduleError(
                            f"{definition.label}: changed PDF was not stable "
                            "across downloads"
                        )
                if (
                    pdf_sha != line_state.get("pdf_sha256")
                    or not current_image.exists()
                ):
                    image_sha = await asyncio.to_thread(
                        render_pdf, downloaded.payload, candidate_image
                    )
                    line_state["image_sha256"] = image_sha
                line_state.update({
                    "source_url": downloaded.url,
                    "etag": downloaded.etag,
                    "last_modified": downloaded.last_modified,
                    "pdf_sha256": pdf_sha,
                    "reviewed": pdf_sha == definition.reviewed_sha256,
                })
            except TransportScheduleError as exc:
                logging.warning(
                    "%s changed PDF rejected; keeping accepted media: %s",
                    key,
                    exc,
                )
                try:
                    candidate_image.unlink()
                except FileNotFoundError:
                    pass

        selected_image = (
            candidate_image if candidate_image.exists() else current_image
        )
        if not selected_image.exists() or not line_state.get("source_url"):
            raise TransportScheduleError(
                f"{definition.label}: no accepted timetable image is available"
            )
        caption = build_line_caption(
            definition,
            now,
            transport_link,
            line_state.get("reviewed") is True,
        )
        message_id = messages.get(key)
        is_media = line_state.get("media") is True
        image_changed = (
            candidate_image.exists()
            or
            line_state.get("published_image_sha256")
            != line_state.get("image_sha256")
        )
        creating_message = False
        try:
            if message_id is not None and is_media:
                if image_changed:
                    try:
                        file_id = await edit_media(
                            message_id, selected_image, caption
                        )
                        line_state["file_id"] = file_id
                    except TelegramError as exc:
                        if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
                            pass
                        elif exc.diagnostic_code != "MESSAGE-NOT-FOUND":
                            raise
                        else:
                            creating_message = True
                            new_id, file_id = await send_photo(
                                selected_image, caption
                            )
                            creating_message = False
                            replacements[key] = (message_id, new_id)
                            messages[key] = new_id
                            line_state["file_id"] = file_id
                else:
                    try:
                        await edit_caption(message_id, caption)
                    except TelegramError as exc:
                        if exc.diagnostic_code == "MESSAGE-NOT-MODIFIED":
                            pass
                        elif exc.diagnostic_code == "MESSAGE-NOT-FOUND":
                            creating_message = True
                            new_id, file_id = await send_photo(
                                selected_image, caption
                            )
                            creating_message = False
                            replacements[key] = (message_id, new_id)
                            messages[key] = new_id
                            line_state["file_id"] = file_id
                        else:
                            raise
            else:
                creating_message = True
                new_id, file_id = await send_photo(selected_image, caption)
                creating_message = False
                if message_id is not None:
                    replacements[key] = (message_id, new_id)
                else:
                    replacements[key] = (0, new_id)
                messages[key] = new_id
                line_state["file_id"] = file_id
        except TelegramError as exc:
            if (
                exc.retryable
                and creating_message
                and exc.server_status != 429
            ):
                line_state["delivery_uncertain"] = True
                payload["lines"][key] = line_state
                await asyncio.to_thread(state.write_payload, chat_id, payload)
            else:
                try:
                    candidate_image.unlink()
                except FileNotFoundError:
                    pass
            raise
        if candidate_image.exists():
            _replace_image(current_image, candidate_image)
        line_state.update({
            "media": True,
            "published_image_sha256": line_state.get("image_sha256"),
            "caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
            "last_successful_check": now.isoformat(),
            "delivery_uncertain": False,
        })
        payload["lines"][key] = line_state
        payload["messages"] = messages
        replacement = replacements.get(key)
        if (
            replacement is not None
            and replacement[0] > 0
            and replacement[0] not in payload["obsolete_messages"]
        ):
            payload["obsolete_messages"].append(replacement[0])
        await asyncio.to_thread(state.write_payload, chat_id, payload)

    payload["messages"] = messages
    for old_id, _ in replacements.values():
        if old_id > 0 and old_id not in payload["obsolete_messages"]:
            payload["obsolete_messages"].append(old_id)
    await asyncio.to_thread(state.write_payload, chat_id, payload)

    links = {
        key: telegram_message_link(chat_id, messages[key])
        for key in messages
        if key in {
            "line_1", "line_2", "airport", "hospital", "alicante",
            "elche", "south", "inland", "university",
        }
    }
    if set(links) != {
        "line_1", "line_2", "airport", "hospital", "alicante",
        "elche", "south", "inland", "university",
    }:
        raise TransportScheduleError("transport guide is incomplete")
    index = build_transport_index(
        links, telegram_message_link(chat_id, messages["root"])
    )
    try:
        await edit_text(messages["transport"], index)
    except TelegramError as exc:
        if exc.diagnostic_code != "MESSAGE-NOT-MODIFIED":
            raise

    remaining_obsolete = []
    for old_id in payload["obsolete_messages"]:
        try:
            await delete(old_id)
        except TelegramError as exc:
            if exc.diagnostic_code == "MESSAGE-NOT-FOUND":
                continue
            else:
                logging.warning("Old timetable message could not be deleted")
                remaining_obsolete.append(old_id)
        except Exception:
            logging.warning("Old timetable message could not be deleted")
            remaining_obsolete.append(old_id)
    payload["obsolete_messages"] = remaining_obsolete
    await asyncio.to_thread(state.write_payload, chat_id, payload)
    return dict(messages)
