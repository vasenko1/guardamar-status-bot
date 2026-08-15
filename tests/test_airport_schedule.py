import json
import ssl
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from telegrambot.airport_schedule import (
    AirportSchedule,
    AirportScheduleError,
    AirportScheduleState,
    Fare,
    _DownloadedPdf,
    _SearchResult,
    _allowed_intermediate_url,
    _intermediate_url,
    _missing_issuer,
    _open_bounded,
    _refresh_fare,
    build_airport_message,
    parse_fare_pdf,
    parse_search_response,
    sync_airport_schedule,
)
from telegrambot.branding import FOOTER
from telegrambot.pinned import LEAF_MESSAGES, PinnedGuideState
from telegrambot.state import StateError
from telegrambot.telegram import TelegramError


FARE_URL = (
    "https://www.bus-siguenza.com/wbus/tarifas/"
    "2026_CE-714%20BENFERRI-ORIHUELA-GUARDAMAR-ALACANT_firmado%20%281%29.pdf"
)
FARE_HREF = (
    "wbus/tarifas/"
    "2026_CE-714 BENFERRI-ORIHUELA-GUARDAMAR-ALACANT_firmado (1).pdf"
)


def _panel(title, times, coordinates):
    rows = "".join(
        f'<button type="button">{value}</button>'
        f'<a href="https://www.google.com/maps/search/'
        f'?api=1&amp;query={coordinates}">stop</a>'
        for value in times
    )
    return (
        '<div class="panel panel-purple">'
        f'<h3 class="panel-title"><b>{title}</b></h3>'
        f"<table><tr><td>{rows}</td></tr></table></div>"
    )


def _search_html(to_airport=None, from_airport=None):
    to_airport = to_airport or ("07:50", "12:05", "15:05")
    from_airport = from_airport or (
        "08:45", "13:00", "16:30", "20:30"
    )
    return (
        _panel(
            "GUARDAMAR DEL SEGURA <i></i> "
            "AEROPUERTO DE ALICANTE - ELCHE",
            to_airport,
            "38.087834,-0.655759",
        )
        + "<!-- <button>23:59</button> -->"
        + _panel(
            "AEROPUERTO DE ALICANTE - ELCHE <i></i> "
            "GUARDAMAR DEL SEGURA",
            from_airport,
            "38.282222222222,-0.55805555555556",
        )
        + f'<a href="{FARE_HREF}">PRECIOS</a>'
    ).encode()


def _fare():
    return Fare(
        cents=295,
        effective_date=date(2026, 2, 1),
        source_url=FARE_URL,
        etag='"tag"',
        last_modified="Mon, 09 Feb 2026 09:19:08 GMT",
        pdf_sha256="a" * 64,
    )


def _schedule(service_date=date(2026, 8, 14), fare=True):
    return AirportSchedule(
        service_date=service_date,
        to_airport=("07:50", "12:05", "15:05"),
        from_airport=("08:45", "13:00", "16:30", "20:30"),
        guardamar_coordinates="38.087834,-0.655759",
        airport_coordinates="38.282222222222,-0.55805555555556",
        fare=_fare() if fare else None,
    )


def _messages():
    keys = [*LEAF_MESSAGES, "cameras", "transport", "root"]
    return {key: number for number, key in enumerate(keys, start=1)}


class AirportSourceTests(unittest.TestCase):
    def test_tls_repair_accepts_only_official_https_intermediate(self):
        self.assertTrue(
            _allowed_intermediate_url("https://e7.i.lencr.org/")
        )
        for url in (
            "http://e7.i.lencr.org/",
            "https://e7.i.lencr.org/extra",
            "https://e7.i.lencr.org/?next=evil",
            "https://e7.i.lencr.org.evil.example/",
            "https://user@e7.i.lencr.org/",
        ):
            self.assertFalse(_allowed_intermediate_url(url))

    def test_tls_aia_is_upgraded_to_strict_https(self):
        completed = subprocess.CompletedProcess(
            [], 0,
            stdout=(
                b"Authority Information Access:\n"
                b" CA Issuers - URI:http://e7.i.lencr.org/\n"
            ),
        )
        with patch(
            "telegrambot.airport_schedule.subprocess.run",
            return_value=completed,
        ):
            url = _intermediate_url(b"leaf")

        self.assertEqual(url, "https://e7.i.lencr.org/")

    def test_only_missing_issuer_error_can_trigger_tls_repair(self):
        missing = ssl.SSLCertVerificationError(
            1, "unable to get local issuer certificate"
        )
        expired = ssl.SSLCertVerificationError(
            1, "certificate has expired"
        )

        self.assertTrue(_missing_issuer(urllib.error.URLError(missing)))
        self.assertFalse(_missing_issuer(urllib.error.URLError(expired)))

    def test_source_request_retries_once_with_repaired_context(self):
        missing = ssl.SSLCertVerificationError(
            1, "unable to get local issuer certificate"
        )
        first_opener = MagicMock()
        first_opener.open.side_effect = urllib.error.URLError(missing)
        response = MagicMock()
        response.geturl.return_value = (
            "https://www.bus-siguenza.com/wbus/procesa.php"
        )
        response.read.return_value = b"accepted"
        response.status = 200
        response.headers = MagicMock()
        response.__enter__.return_value = response
        second_opener = MagicMock()
        second_opener.open.return_value = response
        repaired = MagicMock(spec=ssl.SSLContext)

        with (
            patch(
                "telegrambot.airport_schedule._BUS_TLS_CONTEXT", None
            ),
            patch(
                "telegrambot.airport_schedule._repaired_tls_context",
                return_value=repaired,
            ) as repair,
            patch(
                "telegrambot.airport_schedule.urllib.request.build_opener",
                side_effect=(first_opener, second_opener),
            ),
        ):
            payload, _, _, status = _open_bounded(
                urllib.request.Request(
                    "https://www.bus-siguenza.com/wbus/procesa.php"
                ),
                100,
            )

        self.assertEqual(payload, b"accepted")
        self.assertEqual(status, 200)
        repair.assert_called_once_with()

    def test_parses_both_directions_stops_and_fare_link(self):
        result = parse_search_response(
            _search_html(), date(2026, 8, 14)
        )

        self.assertEqual(
            result.schedule.to_airport,
            ("07:50", "12:05", "15:05"),
        )
        self.assertEqual(
            result.schedule.from_airport,
            ("08:45", "13:00", "16:30", "20:30"),
        )
        self.assertEqual(
            result.schedule.guardamar_coordinates,
            "38.087834,-0.655759",
        )
        self.assertEqual(
            result.schedule.airport_coordinates,
            "38.282222222222,-0.55805555555556",
        )
        self.assertEqual(result.fare_url, FARE_URL)

    def test_accepts_the_observed_non_summer_extra_return(self):
        result = parse_search_response(
            _search_html(from_airport=(
                "08:45", "10:00", "13:00", "16:30", "20:30"
            )),
            date(2026, 9, 1),
        )

        self.assertIn("10:00", result.schedule.from_airport)

    def test_rejects_ambiguous_stop_coordinates(self):
        page = _search_html().replace(
            b"38.087834,-0.655759",
            b"38.087834,-0.655759", 1,
        ).replace(
            b"38.087834,-0.655759",
            b"38.090000,-0.650000", 1,
        )

        with self.assertRaises(AirportScheduleError):
            parse_search_response(page, date(2026, 8, 14))

    def test_rejects_unsorted_or_incomplete_directions(self):
        with self.assertRaises(AirportScheduleError):
            parse_search_response(
                _search_html(to_airport=("12:05", "07:50")),
                date(2026, 8, 14),
            )
        one_direction = _panel(
            "GUARDAMAR DEL SEGURA AEROPUERTO DE ALICANTE - ELCHE",
            ("07:50",),
            "38.087834,-0.655759",
        ).encode()
        with self.assertRaises(AirportScheduleError):
            parse_search_response(one_direction, date(2026, 8, 14))

    def test_missing_or_ambiguous_fare_does_not_hide_schedule(self):
        no_fare = _search_html().replace(
            f'<a href="{FARE_HREF}">PRECIOS</a>'.encode(), b""
        )
        extra_fare = _search_html() + (
            '<a href="wbus/tarifas/second.pdf">SECOND</a>'
        ).encode()

        self.assertIsNone(
            parse_search_response(no_fare, date(2026, 8, 14)).fare_url
        )
        self.assertIsNone(
            parse_search_response(extra_fare, date(2026, 8, 14)).fare_url
        )

    def test_untrusted_fare_link_does_not_hide_schedule(self):
        page = _search_html().replace(
            FARE_HREF.encode(),
            b"https://www.bus-siguenza.com:444/wbus/tarifas/fare.pdf",
        )

        result = parse_search_response(page, date(2026, 8, 14))

        self.assertEqual(result.schedule.to_airport[0], "07:50")
        self.assertIsNone(result.fare_url)

    def test_extracts_guardamar_standard_fare_from_signed_line_three(self):
        info = b"Pages: 3\nEncrypted: no\n"
        text = """
Dirección General de Transportes y Logística
CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT
FECHA ENTRADA EN VIGOR: 1 FEBRERO DE 2026
LÍNEA 3: ALMORADÍ - GUARDAMAR - AEROPUERTO
TARIFA BASE GENERAL
ALMORADÍ
6 1,60 € FORMENTERA DEL SEGURA
8 1,60 € 2 1,60 € ROJALES
15 1,60 € 9 1,60 € 7 1,60 € GUARDAMAR DEL SEGURA
21 1,95 € 15 1,60 € 13 1,60 € 6 1,60 € URBANIZACIÓN LA MARINA
24 2,20 € 18 1,65 € 16 1,60 € 9 1,60 € 3 1,60 € LA MARINA
47 4,35 € 41 3,80 € 39 3,60 € 32 2,95 € 26 2,40 € 23 2,15 € AEROPUERTO       - 21 1,95 € ABANILLA
TARIFA MAYORES DE 65 AÑOS
FIRMADO ELECTRÓNICAMENTE POR EL JEFE DEL SERVICIO DE TRANSPORTE PÚBLICO
""".encode()
        downloaded = _DownloadedPdf(
            b"%PDF-fare", FARE_URL, '"tag"', "modified"
        )
        completed = (
            subprocess.CompletedProcess([], 0, stdout=info),
            subprocess.CompletedProcess([], 0, stdout=text),
        )

        with patch(
            "telegrambot.airport_schedule.subprocess.run",
            side_effect=completed,
        ):
            fare = parse_fare_pdf(
                downloaded.payload, downloaded.url, downloaded
            )

        self.assertEqual(fare.cents, 295)
        self.assertEqual(fare.effective_date, date(2026, 2, 1))
        self.assertEqual(
            fare.pdf_sha256,
            "5811921d92dc6c87c740f282598c082a3743588e98147e4ca41956a34328d89f",
        )

    def test_fare_parser_fails_closed_on_changed_topology(self):
        info = b"Pages: 3\nEncrypted: no\n"
        text = (
            "Dirección General de Transportes y Logística\n"
            "CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT\n"
            "FECHA ENTRADA EN VIGOR: 1 FEBRERO DE 2026\n"
            "LÍNEA 3: ALMORADÍ - GUARDAMAR - AEROPUERTO\n"
            "TARIFA BASE GENERAL\nAEROPUERTO\n"
            "TARIFA MAYORES DE 65 AÑOS\n"
            "FIRMADO ELECTRÓNICAMENTE POR EL JEFE DEL SERVICIO DE TRANSPORTE PÚBLICO"
        ).encode()
        with patch(
            "telegrambot.airport_schedule.subprocess.run",
            side_effect=(
                subprocess.CompletedProcess([], 0, stdout=info),
                subprocess.CompletedProcess([], 0, stdout=text),
            ),
        ):
            with self.assertRaises(AirportScheduleError):
                parse_fare_pdf(
                    b"%PDF-fare",
                    FARE_URL,
                    _DownloadedPdf(b"%PDF-fare", FARE_URL, None, None),
                )

    def test_fare_parser_rejects_changed_stop_order(self):
        info = b"Pages: 3\nEncrypted: no\n"
        text = """
Dirección General de Transportes y Logística
CE-714 BENIFERRI-ORIHUELA-GUARDAMAR/ALACANT
FECHA ENTRADA EN VIGOR: 1 FEBRERO DE 2026
LÍNEA 3: ALMORADÍ - GUARDAMAR - AEROPUERTO
TARIFA BASE GENERAL
ALMORADÍ
ROJALES
FORMENTERA DEL SEGURA
GUARDAMAR DEL SEGURA
URBANIZACIÓN LA MARINA
LA MARINA
47 4,35 € 41 3,80 € 39 3,60 € 32 2,95 € 26 2,40 € 23 2,15 € AEROPUERTO
TARIFA MAYORES DE 65 AÑOS
FIRMADO ELECTRÓNICAMENTE POR EL JEFE DEL SERVICIO DE TRANSPORTE PÚBLICO
""".encode()
        with patch(
            "telegrambot.airport_schedule.subprocess.run",
            side_effect=(
                subprocess.CompletedProcess([], 0, stdout=info),
                subprocess.CompletedProcess([], 0, stdout=text),
            ),
        ):
            with self.assertRaises(AirportScheduleError):
                parse_fare_pdf(
                    b"%PDF-fare",
                    FARE_URL,
                    _DownloadedPdf(b"%PDF-fare", FARE_URL, None, None),
                )

    def test_unchanged_fare_uses_conditional_result_without_parsing(self):
        with (
            patch(
                "telegrambot.airport_schedule.download_fare_pdf",
                return_value=None,
            ) as download,
            patch(
                "telegrambot.airport_schedule.parse_fare_pdf"
            ) as parse,
        ):
            fare = _refresh_fare(FARE_URL, _fare())

        self.assertEqual(fare, _fare())
        download.assert_called_once_with(
            FARE_URL, '"tag"', "Mon, 09 Feb 2026 09:19:08 GMT"
        )
        parse.assert_not_called()

    def test_changed_unstable_fare_is_omitted(self):
        changed = _DownloadedPdf(b"%PDF-new", FARE_URL, "new", "new")
        confirmation = _DownloadedPdf(
            b"%PDF-different", FARE_URL, "new", "new"
        )
        with patch(
            "telegrambot.airport_schedule.download_fare_pdf",
            side_effect=(changed, confirmation),
        ):
            fare = _refresh_fare(FARE_URL, _fare())

        self.assertIsNone(fare)

    def test_same_fare_url_survives_one_network_failure(self):
        with patch(
            "telegrambot.airport_schedule.download_fare_pdf",
            side_effect=AirportScheduleError("offline"),
        ):
            fare = _refresh_fare(FARE_URL, _fare())

        self.assertEqual(fare, _fare())


class AirportMessageTests(unittest.TestCase):
    def test_message_is_current_compact_mapped_and_priced(self):
        message = build_airport_message(
            _schedule(), date(2026, 8, 14), "https://t.me/c/123/20"
        )

        self.assertIn("Сегодня, 14 августа", message)
        self.assertIn("07:50 · 12:05 · 15:05", message)
        self.assertIn("Обычный билет: 2,95 €", message)
        self.assertIn("38.087834%2C-0.655759", message)
        self.assertIn("38.282222222222%2C-0.55805555555556", message)
        self.assertIn("Найти расписание на другую дату", message)
        self.assertIn(
            "До аэропорта можно доехать без пересадок", message
        )
        self.assertIn("📍 <b>Откуда и куда</b>", message)
        self.assertIn("автовокзал Гуардамара", message)
        self.assertIn("остановка у терминала аэропорта", message)
        self.assertIn("https://t.me/c/123/20", message)
        self.assertEqual(message.count(FOOTER), 1)
        self.assertNotIn("—", message)
        self.assertLessEqual(len(message), 4096)

    def test_cached_schedule_never_claims_it_is_today(self):
        message = build_airport_message(
            _schedule(date(2026, 8, 13)),
            date(2026, 8, 14),
            "https://t.me/c/123/20",
        )

        self.assertIn("Расписание на 13 августа", message)
        self.assertNotIn("Сегодня", message)

    def test_future_fare_is_not_shown_before_effective_date(self):
        future_fare = Fare(
            cents=310,
            effective_date=date(2026, 9, 1),
            source_url=FARE_URL,
            etag=None,
            last_modified=None,
            pdf_sha256="b" * 64,
        )
        base = _schedule(fare=False)
        schedule = AirportSchedule(
            base.service_date,
            base.to_airport,
            base.from_airport,
            base.guardamar_coordinates,
            base.airport_coordinates,
            future_fare,
        )

        message = build_airport_message(
            schedule, date(2026, 8, 14), "https://t.me/c/123/20"
        )

        self.assertNotIn("Обычный билет", message)

    def test_cached_earlier_schedule_does_not_show_later_fare(self):
        future_fare = Fare(
            cents=310,
            effective_date=date(2026, 9, 1),
            source_url=FARE_URL,
            etag=None,
            last_modified=None,
            pdf_sha256="b" * 64,
        )
        base = _schedule(date(2026, 8, 31), fare=False)
        schedule = AirportSchedule(
            base.service_date,
            base.to_airport,
            base.from_airport,
            base.guardamar_coordinates,
            base.airport_coordinates,
            future_fare,
        )

        message = build_airport_message(
            schedule, date(2026, 9, 1), "https://t.me/c/123/20"
        )

        self.assertNotIn("Обычный билет", message)


class AirportStateTests(unittest.TestCase):
    def test_round_trip_and_previous_generation_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "airport.json"
            state = AirportScheduleState(path)
            first = _schedule(date(2026, 8, 13))
            second = _schedule(date(2026, 8, 14))
            state.write(first)
            state.write(second)
            path.write_text("broken", encoding="utf-8")

            recovered = state.read()

            self.assertEqual(recovered, first)
            self.assertEqual(
                json.loads(
                    (Path(directory) / "airport.previous.json").read_text()
                )["service_date"],
                "2026-08-13",
            )

    def test_invalid_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "airport.json"
            path.write_text(json.dumps({
                "version": 1,
                "service_date": "2026-08-14",
                "to_airport": ["25:99"],
                "from_airport": ["08:45"],
                "guardamar_coordinates": "38.08,-0.65",
                "airport_coordinates": "38.28,-0.55",
                "fare": None,
            }))

            with self.assertRaises(Exception):
                AirportScheduleState(path).read()

    def test_non_text_time_in_state_fails_as_state_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "airport.json"
            path.write_text(json.dumps({
                "version": 1,
                "service_date": "2026-08-14",
                "to_airport": [750],
                "from_airport": ["08:45"],
                "guardamar_coordinates": "38.08,-0.65",
                "airport_coordinates": "38.28,-0.55",
                "fare": None,
            }))

            with self.assertRaises(StateError):
                AirportScheduleState(path).read()


class AirportSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_schedule_updates_existing_message_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            pinned = PinnedGuideState(Path(directory) / "pinned.json")
            pinned.write("-100123", _messages())
            airport_state = AirportScheduleState(
                Path(directory) / "airport.json"
            )
            result = _SearchResult(_schedule(fare=False), FARE_URL)
            edit = AsyncMock()
            with (
                patch(
                    "telegrambot.airport_schedule.fetch_schedule",
                    return_value=result,
                ),
                patch(
                    "telegrambot.airport_schedule._refresh_fare",
                    return_value=_fare(),
                ),
            ):
                await sync_airport_schedule(
                    datetime(2026, 8, 14, 5, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                    "-100123",
                    pinned,
                    airport_state,
                    AsyncMock(),
                    edit,
                )

            self.assertIn("07:50 · 12:05 · 15:05", edit.await_args.args[1])
            self.assertEqual(airport_state.read().fare.cents, 295)

    async def test_source_outage_uses_cache_and_recovers_deleted_message(self):
        with tempfile.TemporaryDirectory() as directory:
            pinned = PinnedGuideState(Path(directory) / "pinned.json")
            messages = _messages()
            pinned.write("-100123", messages)
            airport_state = AirportScheduleState(
                Path(directory) / "airport.json"
            )
            airport_state.write(_schedule(date(2026, 8, 13)))
            missing = TelegramError(
                "missing", retryable=False,
                code="MESSAGE-NOT-FOUND", status=400,
            )
            send = AsyncMock(return_value=99)
            with patch(
                "telegrambot.airport_schedule.fetch_schedule",
                side_effect=AirportScheduleError("offline"),
            ):
                result = await sync_airport_schedule(
                    datetime(2026, 8, 14, 5, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                    "-100123",
                    pinned,
                    airport_state,
                    send,
                    AsyncMock(side_effect=missing),
                )

            self.assertEqual(result["airport"], 99)
            self.assertIn(
                "Расписание на 13 августа", send.await_args.args[0]
            )
            self.assertEqual(
                pinned.read("-100123")["airport"], 99
            )

    async def test_ambiguous_replacement_is_marked_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            pinned = PinnedGuideState(Path(directory) / "pinned.json")
            pinned.write("-100123", _messages())
            airport_state = AirportScheduleState(
                Path(directory) / "airport.json"
            )
            airport_state.write(_schedule())
            missing = TelegramError(
                "missing", retryable=False,
                code="MESSAGE-NOT-FOUND", status=400,
            )
            timeout = TelegramError(
                "timeout", retryable=True, code="TIMEOUT"
            )
            with (
                patch(
                    "telegrambot.airport_schedule.fetch_schedule",
                    side_effect=AirportScheduleError("offline"),
                ),
                self.assertRaises(TelegramError),
            ):
                await sync_airport_schedule(
                    datetime(2026, 8, 14, 5, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                    "-100123",
                    pinned,
                    airport_state,
                    AsyncMock(side_effect=timeout),
                    AsyncMock(side_effect=missing),
                )

            self.assertEqual(
                pinned.read_payload("-100123")["uncertain_messages"],
                ["airport"],
            )


if __name__ == "__main__":
    unittest.main()
