import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from telegrambot.convega import (
    ConvegaSourceError,
    REGISTRATION_FULL_ACCESS_NOTE,
    convega_translation_items,
    fetch_convega_snapshot,
    fetch_today_convega_events,
    parse_convega_payloads,
    refresh_convega_catalog,
    valid_convega_snapshot,
)


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 2, 12, 47, tzinfo=TZ)
POST_ID = 42197
POST_LINK = (
    "https://convega.com/"
    "convega-organiza-dos-rutas-guiadas-por-el-gr-92-"
    "mejor-sendero-homologado-2025-de-la-comunitat-valenciana/"
)
LANDING_LINK = "https://convega.com/rutasguiadas-senderodelmediterraneo/"


def category():
    return [{
        "id": POST_ID,
        "date": "2026-09-21T15:42:42",
        "modified": "2026-09-21T15:42:43",
        "slug": (
            "convega-organiza-dos-rutas-guiadas-por-el-gr-92-"
            "mejor-sendero-homologado-2025-de-la-comunitat-valenciana"
        ),
        "link": POST_LINK,
        "title": {
            "rendered": (
                "Convega organiza dos rutas guiadas por el GR-92, "
                "Mejor Sendero Homologado 2025 de la Comunitat Valenciana"
            )
        },
    }]


def announcement():
    return {
        **category()[0],
        "content": {
            "rendered": """
                <p>La primera salida tendrá lugar el domingo 4 de octubre y
                recorrerá la etapa 21 del Sendero del Mediterráneo GR-92,
                entre Guardamar del Segura y Torrevieja.</p>
                <p>La iniciativa continuará el 8 de noviembre con una segunda
                salida por la etapa 22 del GR-92, a través del litoral de
                Torrevieja, Orihuela Costa y Pilar de la Horadada.</p>
            """
        },
    }


def landing(inner):
    return [{
        "id": 41588,
        "date": "2026-09-16T09:35:54",
        "modified": "2026-09-23T08:42:33",
        "slug": "rutasguiadas-senderodelmediterraneo",
        "link": LANDING_LINK,
        "title": {"rendered": "Rutas guiadas Sendero del Mediterráneo"},
        "content": {
            "rendered": (
                "<h1>Ruta por la Etapa 21 del Sendero del Mediterráneo</h1>"
                "<p>04/10/2026</p>"
                + inner
            )
        },
    }]


def snapshot_with(inner):
    return parse_convega_payloads(
        category(),
        {POST_ID: announcement()},
        landing(inner),
        NOW,
    )


class ConvegaParsingTests(unittest.TestCase):
    def test_current_production_shape_keeps_stage21_full_and_stage22_nonlocal(self):
        snapshot = snapshot_with("<h3>¡¡PLAZAS AGOTADAS!!</h3>")

        self.assertTrue(valid_convega_snapshot(snapshot))
        self.assertEqual(len(snapshot["records"]), 2)
        by_stage = {item["stage"]: item for item in snapshot["records"]}

        self.assertTrue(by_stage[21]["guardamar_relevant"])
        self.assertEqual(by_stage[21]["event_start_date"], "2026-10-04")
        self.assertEqual(by_stage[21]["observed_status"], "full")
        self.assertTrue(by_stage[21]["until_full"])
        self.assertEqual(
            by_stage[21]["record_id"],
            "convega:post-42197:stage-21",
        )
        self.assertEqual(
            by_stage[21]["route"],
            "Guardamar del Segura → Torrevieja",
        )

        self.assertFalse(by_stage[22]["guardamar_relevant"])
        self.assertEqual(by_stage[22]["event_start_date"], "2026-11-08")
        self.assertEqual(by_stage[22]["observed_status"], "unknown")
        self.assertIsNone(by_stage[22]["landing_url"])

    def test_embedded_registration_form_can_prove_open_without_plugin_name(self):
        snapshot = snapshot_with(
            "<p>Inscripción</p>"
            "<form><input type='text' name='name'>"
            "<input type='email' name='email'>"
            "<input type='submit' value='Enviar'></form>"
        )
        stage21 = next(item for item in snapshot["records"] if item["stage"] == 21)

        self.assertEqual(stage21["observed_status"], "open")
        self.assertEqual(stage21["registration_url"], LANDING_LINK)

    def test_terminal_marker_wins_over_stale_form(self):
        snapshot = snapshot_with(
            "<h3>PLAZAS AGOTADAS</h3>"
            "<p>Inscripción</p><form><button type='submit'>Enviar</button></form>"
        )
        stage21 = next(item for item in snapshot["records"] if item["stage"] == 21)

        self.assertEqual(stage21["observed_status"], "full")
        self.assertIsNone(stage21["registration_url"])

    def test_generic_information_link_does_not_prove_open(self):
        snapshot = snapshot_with(
            "<a href='https://convega.com/rutasguiadas-senderodelmediterraneo/'>"
            "MÁS INFORMACIÓN</a>"
        )
        stage21 = next(item for item in snapshot["records"] if item["stage"] == 21)

        self.assertEqual(stage21["observed_status"], "unknown")
        self.assertIsNone(stage21["registration_url"])

    def test_search_form_does_not_prove_open(self):
        snapshot = snapshot_with(
            "<p>Inscripción</p>"
            "<form><input type='search' name='s'>"
            "<button type='submit'>Buscar</button></form>"
        )
        stage21 = next(item for item in snapshot["records"] if item["stage"] == 21)

        self.assertEqual(stage21["observed_status"], "unknown")

    def test_relative_explicit_registration_cta_is_normalized_to_https_landing_host(self):
        snapshot = snapshot_with(
            "<a href='/inscripcion-ruta/'>Inscripción</a>"
        )
        stage21 = next(item for item in snapshot["records"] if item["stage"] == 21)

        self.assertEqual(stage21["observed_status"], "open")
        self.assertEqual(
            stage21["registration_url"],
            "https://convega.com/inscripcion-ruta/",
        )

    def test_explicit_https_registration_cta_can_prove_open(self):
        snapshot = snapshot_with(
            "<a href='https://convega.empleactiva.com/emprendedores/registro'>"
            "Ir a inscripción</a>"
        )
        stage21 = next(item for item in snapshot["records"] if item["stage"] == 21)

        self.assertEqual(stage21["observed_status"], "open")
        self.assertEqual(
            stage21["registration_url"],
            "https://convega.empleactiva.com/emprendedores/registro",
        )

    def test_plain_http_registration_cta_is_rejected(self):
        snapshot = snapshot_with(
            "<a href='http://convega.com/registro'>Inscripción</a>"
        )
        stage21 = next(item for item in snapshot["records"] if item["stage"] == 21)

        self.assertEqual(stage21["observed_status"], "unknown")
        self.assertIsNone(stage21["registration_url"])

    def test_ambiguous_landing_identity_does_not_apply_status(self):
        value = landing(
            "<h3>PLAZAS AGOTADAS</h3>"
            "<p>Etapa 22 · 08/11/2026</p>"
        )
        snapshot = parse_convega_payloads(
            category(),
            {POST_ID: announcement()},
            value,
            NOW,
        )

        self.assertTrue(all(
            item["observed_status"] == "unknown"
            for item in snapshot["records"]
        ))

    def test_invalid_occurrence_identity_fails_closed(self):
        broken = announcement()
        broken["content"] = {"rendered": "<p>Ruta guiada sin fecha ni etapa</p>"}
        with self.assertRaises(ConvegaSourceError):
            parse_convega_payloads(
                category(),
                {POST_ID: broken},
                landing(""),
                NOW,
            )


class ConvegaProjectionTests(unittest.TestCase):
    def test_event_projection_is_guardamar_only_and_keeps_terminal_access(self):
        snapshot = snapshot_with("<h3>PLAZAS AGOTADAS</h3>")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "convega.json"
            translations = Path(directory) / "translations.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")

            events = asyncio.run(fetch_today_convega_events(
                datetime(2026, 10, 4, 7, 30, tzinfo=TZ),
                state,
                translations,
            ))
            stage22_day = asyncio.run(fetch_today_convega_events(
                datetime(2026, 11, 8, 7, 30, tzinfo=TZ),
                state,
                translations,
            ))
            items = asyncio.run(convega_translation_items(NOW, state))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Ruta guiada GR-92 · Etapa 21")
        self.assertEqual(events[0].access_note, REGISTRATION_FULL_ACCESS_NOTE)
        self.assertIsNone(events[0].registration_url)
        self.assertEqual(events[0].route, "Guardamar del Segura → Torrevieja")
        self.assertEqual(stage22_day, ())
        self.assertEqual(
            items,
            (("convega", "Ruta guiada GR-92 · Etapa 21"),),
        )

    def test_open_event_projection_keeps_validated_action(self):
        snapshot = snapshot_with(
            "<p>Inscripción</p>"
            "<form><input type='text' name='name'>"
            "<input type='email' name='email'>"
            "<button type='submit'>Enviar</button></form>"
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "convega.json"
            translations = Path(directory) / "translations.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            events = asyncio.run(fetch_today_convega_events(
                datetime(2026, 10, 4, 7, 30, tzinfo=TZ),
                state,
                translations,
            ))

        self.assertEqual(events[0].registration_url, LANDING_LINK)
        self.assertIsNone(events[0].access_note)


class ConvegaRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_fetch_uses_category_one_detail_and_landing(self):
        calls = []

        def fake_read(url, *, limit_bytes):
            calls.append(url)
            if "/posts?" in url:
                return category()
            if f"/posts/{POST_ID}?" in url:
                return announcement()
            if "/pages?" in url:
                return landing("<h3>PLAZAS AGOTADAS</h3>")
            raise AssertionError(url)

        with patch("telegrambot.convega._read_json", side_effect=fake_read):
            snapshot = await fetch_convega_snapshot(NOW)

        self.assertTrue(valid_convega_snapshot(snapshot))
        self.assertEqual(len(calls), 3)

    async def test_refresh_preserves_last_good_on_source_failure(self):
        previous = snapshot_with("<h3>PLAZAS AGOTADAS</h3>")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "convega.json"
            state.write_text(json.dumps(previous), encoding="utf-8")
            with patch(
                "telegrambot.convega.fetch_convega_snapshot",
                new=AsyncMock(
                    side_effect=ConvegaSourceError("down", code="NETWORK")
                ),
            ):
                records = await refresh_convega_catalog(NOW, state)
            saved = json.loads(state.read_text(encoding="utf-8"))

        self.assertEqual(saved, previous)
        self.assertEqual(tuple(previous["records"]), records)

    async def test_corrupt_local_state_recovers_from_valid_remote(self):
        current = snapshot_with("<h3>PLAZAS AGOTADAS</h3>")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "convega.json"
            state.write_text("{broken", encoding="utf-8")
            with patch(
                "telegrambot.convega.fetch_convega_snapshot",
                new=AsyncMock(return_value=current),
            ):
                records = await refresh_convega_catalog(NOW, state)
            saved = json.loads(state.read_text(encoding="utf-8"))

        self.assertEqual(len(records), 2)
        self.assertTrue(valid_convega_snapshot(saved))


if __name__ == "__main__":
    unittest.main()
