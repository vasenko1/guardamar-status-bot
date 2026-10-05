import asyncio
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from telegrambot.fishing_enrichment import (
    FEPYC_26MC26_URL,
    FishingEnrichmentError,
    extract_fpcv_pdf_text,
    parse_fepyc_authority_html,
    parse_fpcv_convocatoria_text,
    parse_fpcv_index_html,
    matching_authority,
    refresh_fepyc_authority,
    refresh_fpcv_details,
    valid_fepyc_authority_state,
    valid_fpcv_details_state,
)


MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 5, 5, 11, tzinfo=MADRID)
PDF_URL = (
    "https://federacionpescacv.com/wp-content/uploads/2026/09/"
    "bases-prov-mar-costa-captura-y-suelta-2026.pdf"
)


def _national_base():
    return {
        "sport": "fishing",
        "title": "Mar Costa Dúos",
        "start": "2026-11-23",
        "end": "2026-11-29",
        "place": "Guardamar · Playa",
        "organizer": "FED. ESPAÑOLA PESCA Y C.",
        "level": "NACIONAL",
        "source_url": (
            "https://federacionpescacv.com/"
            "competiciones-de-nuestros-clubes/"
        ),
    }


def _provincial_base():
    return {
        "sport": "fishing",
        "title": "Mar Costa",
        "start": "2026-10-17",
        "end": "2026-10-17",
        "place": "Guardamar · Zona B - Centro, La Roqueta Y Moncayo",
        "organizer": "DELEGACIÓ PROV. ALACANT",
        "level": "PROVINCIAL",
        "source_url": (
            "https://federacionpescacv.com/"
            "competiciones-de-nuestros-clubes/"
        ),
    }


def _fepyc_html():
    return """
    <html><body>
    <div>Id: 26MC26</div>
    <div>XVI Campeonato de España Mar-costa Dúos</div>
    <div>Especialidad: Lanzado Mar Costa</div>
    <div>Categoría: Dúos</div>
    <div>Fecha: Del 26 al 29 de Noviembre de 2026</div>
    <div>Tipo Competición: Nacional</div>
    <div>Lugar: Guardamar del Segura (Alicante)</div>
    </body></html>
    """.encode("utf-8")


def _index_html(venue="Playas la Roqueta y Centro – Guardamar (Alicante)"):
    venue_bytes = venue.encode("utf-8") if isinstance(venue, str) else venue
    return (
        b"<html><body><table>"
        b"<tr><th>FECHA</th><th>AMBITO</th><th>MODALIDAD</th>"
        b"<th>ESCENARIO</th><th>PROVINCIA</th>"
        b"<th>CONVOCATORIA</th><th>RESULTADOS</th></tr>"
        b"<tr><td>17/10/2026</td><td>Provincial Alicante</td>"
        b"<td>Mar-Costa Captura y suelta</td><td>"
        + venue_bytes
        + b"</td><td>Alicante</td><td><a href=\""
        + PDF_URL.encode("ascii")
        + b"\">CONVOCATORIA</a></td><td></td></tr>"
        b"</table></body></html>"
    )


def _pdf_bytes():
    return b"%PDF-1.7\nreviewed-fixture"


def _pdf_text():
    return """
    CAMPEONATO PROVINCIAL DE ALICANTE
    MAR-COSTA CLASIFICATORIO PARA EL COMUNIDAD VALENCIANA 2027
    Lugar, fecha: 17 de Octubre de 2026
    Se celebrará en la Playas la Roqueta y Centro – Guardamar (Alicante)
    Las inscripciones se realizarán por los Clubes hasta el 13 de Octubre a las 12 h.
    Cada participante deberá abonar 20 € por su inscripción.
    BASES
    Mangas. - 2 mangas de 3 horas.
    PROGRAMA
    16:00 h. Concentración, pago del cebo e instrucciones de última hora
    18:00 h. Comienzo de la primera Manga.
    21:00 h. Fin de la primera manga.
    22:30 h. Inicio de la segunda Manga.
    01:30 h. Fin de la segunda Manga. Clasificación Final Provisional.
    El horario podrá modificarse levemente según la ocupación de bañistas en el escenario.
    """


class FishingEnrichmentTests(unittest.TestCase):
    def test_parse_fepyc_authority_proves_exact_national_dates(self):
        record = parse_fepyc_authority_html(
            _fepyc_html(),
            observed_at=NOW,
            spec={
                "source_id": "26MC26",
                "url": FEPYC_26MC26_URL,
                "match_title": "Mar Costa Dúos",
                "competition_name": "XVI Campeonato de España Mar-costa Dúos",
            },
        )

        self.assertEqual(record["source_id"], "26MC26")
        self.assertEqual(
            record["competition_name"],
            "XVI Campeonato de España Mar-costa Dúos",
        )
        self.assertEqual(record["start"], "2026-11-26")
        self.assertEqual(record["end"], "2026-11-29")
        self.assertEqual(record["competition_type"], "Nacional")
        self.assertTrue(
            valid_fepyc_authority_state({"version": 1, "records": [record]})
        )

    def test_parse_fepyc_authority_fails_closed_on_wrong_place(self):
        payload = _fepyc_html().replace(
            b"Guardamar del Segura (Alicante)",
            b"Torrevieja (Alicante)",
        )
        with self.assertRaises(FishingEnrichmentError):
            parse_fepyc_authority_html(
                payload,
                observed_at=NOW,
                spec={
                    "source_id": "26MC26",
                    "url": FEPYC_26MC26_URL,
                    "match_title": "Mar Costa Dúos",
                    "competition_name": "XVI Campeonato de España Mar-costa Dúos",
                },
            )

    def test_index_selects_one_relevant_guardamar_convocatoria(self):
        rows = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["base_title"], "Mar Costa")
        self.assertEqual(row["index_date"], "2026-10-17")
        self.assertFalse(row["cancelled"])
        self.assertEqual(row["pdf_url"], PDF_URL)
        self.assertEqual(len(row["document_identity"]), 64)

    def test_index_ignores_non_date_service_row(self):
        payload = _index_html().replace(
            b"<tr><td>17/10/2026</td>",
            (
                b"<tr><td>error</td><td></td><td></td><td></td>"
                b"<td></td><td></td><td></td></tr>"
                b"<tr><td>17/10/2026</td>"
            ),
        )
        rows = parse_fpcv_index_html(
            payload,
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["index_date"], "2026-10-17")

    def test_index_rejects_guardamar_row_with_wrong_province(self):
        payload = _index_html().replace(
            b"<td>Alicante</td><td><a href=",
            b"<td>Valencia</td><td><a href=",
        )
        rows = parse_fpcv_index_html(
            payload,
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )

        self.assertEqual(rows, ())

    def test_index_marks_matching_cancelled_row_without_pdf_semantics(self):
        rows = parse_fpcv_index_html(
            _index_html("CANCELADO"),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["cancelled"])

    def test_pdf_text_normalizes_competition_schedule_and_access_facts(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]
        record = parse_fpcv_convocatoria_text(
            _pdf_text(),
            descriptor=descriptor,
            content_sha256="c" * 64,
            observed_at=NOW,
        )

        self.assertEqual(
            record["competition_context"],
            (
                "Провинциальный чемпионат Аликанте · "
                "отбор на Comunidad Valenciana 2027"
            ),
        )
        self.assertEqual(
            record["details"],
            [
                (
                    "Провинциальный чемпионат Аликанте · "
                    "отбор на Comunidad Valenciana 2027"
                ),
                "2 тура по 3 часа",
                "Сбор участников: 16:00",
                "1-й тур: 18:00–21:00",
                "2-й тур: 22:30–01:30",
            ],
        )
        self.assertEqual(record["starts_at"], "2026-10-17T18:00:00+02:00")
        self.assertEqual(record["ends_at"], "2026-10-18T01:30:00+02:00")
        self.assertEqual(
            record["registration_deadline"],
            "2026-10-13T12:00:00+02:00",
        )
        self.assertEqual(record["registration_method"], "clubs")
        self.assertEqual(record["registration_fee_cents"], 2000)
        self.assertTrue(
            valid_fpcv_details_state({"version": 1, "records": [record]})
        )

    def test_pdf_parser_rejects_index_date_disagreement(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]
        descriptor = dict(descriptor)
        descriptor["index_date"] = "2026-10-18"

        with self.assertRaisesRegex(
            FishingEnrichmentError,
            "disagrees",
        ):
            parse_fpcv_convocatoria_text(
                _pdf_text(),
                descriptor=descriptor,
                content_sha256="d" * 64,
                observed_at=NOW,
            )

    def test_extract_pdf_text_enforces_magic_and_output_bound(self):
        with self.assertRaises(FishingEnrichmentError):
            extract_fpcv_pdf_text(b"not-pdf")

        completed = Mock(
            returncode=0,
            stdout=b"valid extracted text",
            stderr=b"",
        )
        with patch(
            "telegrambot.fishing_enrichment.subprocess.run",
            return_value=completed,
        ) as called:
            text = extract_fpcv_pdf_text(b"%PDF-1.7\nsmall")
        self.assertEqual(text, "valid extracted text")
        self.assertEqual(called.call_args.kwargs["timeout"], 10.0)

    def test_authority_join_requires_source_range_overlap(self):
        record = parse_fepyc_authority_html(
            _fepyc_html(),
            observed_at=NOW,
            spec={
                "source_id": "26MC26",
                "url": FEPYC_26MC26_URL,
                "match_title": "Mar Costa Dúos",
                "competition_name": "XVI Campeonato de España Mar-costa Dúos",
            },
        )
        state = {"version": 1, "records": [record]}

        self.assertIsNotNone(matching_authority(_national_base(), state, NOW))

        unrelated = dict(_national_base())
        unrelated["start"] = "2026-12-10"
        unrelated["end"] = "2026-12-12"
        self.assertIsNone(matching_authority(unrelated, state, NOW))

    def test_authority_join_rejects_stale_or_future_observation(self):
        record = parse_fepyc_authority_html(
            _fepyc_html(),
            observed_at=NOW,
            spec={
                "source_id": "26MC26",
                "url": FEPYC_26MC26_URL,
                "match_title": "Mar Costa Dúos",
                "competition_name": "XVI Campeonato de España Mar-costa Dúos",
            },
        )
        state = {"version": 1, "records": [record]}

        self.assertIsNone(
            matching_authority(
                _national_base(),
                state,
                NOW + timedelta(hours=37),
            )
        )
        self.assertIsNone(
            matching_authority(
                _national_base(),
                state,
                NOW - timedelta(seconds=1),
            )
        )

    def test_refresh_fepyc_preserves_last_good_on_network_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "authority.json"
            with patch(
                "telegrambot.fishing_enrichment._fetch_fepyc_record",
                new=AsyncMock(
                    return_value=parse_fepyc_authority_html(
                        _fepyc_html(),
                        observed_at=NOW,
                        spec={
                            "source_id": "26MC26",
                            "url": FEPYC_26MC26_URL,
                            "match_title": "Mar Costa Dúos",
                            "competition_name": "XVI Campeonato de España Mar-costa Dúos",
                        },
                    )
                ),
            ):
                first = asyncio.run(
                    refresh_fepyc_authority(
                        NOW,
                        (_national_base(),),
                        state,
                    )
                )

            with patch(
                "telegrambot.fishing_enrichment._fetch_fepyc_record",
                new=AsyncMock(
                    side_effect=FishingEnrichmentError(
                        "down",
                        code="NETWORK",
                    )
                ),
            ):
                second = asyncio.run(
                    refresh_fepyc_authority(
                        NOW + timedelta(days=1),
                        (_national_base(),),
                        state,
                    )
                )

            self.assertEqual(second, first)
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["records"][0]["observed_at"], NOW.isoformat())

    def test_no_base_events_skip_fpcv_index_network(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "details.json"
            fetch_index = AsyncMock(
                side_effect=AssertionError("index must not be fetched")
            )
            with patch(
                "telegrambot.fishing_enrichment._fetch_fpcv_index",
                new=fetch_index,
            ):
                records = asyncio.run(
                    refresh_fpcv_details(NOW, (), state)
                )

            self.assertEqual(records, ())
            fetch_index.assert_not_awaited()
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8")),
                {"version": 1, "records": []},
            )

    def test_unchanged_pdf_bytes_are_refetched_but_not_reextracted(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "details.json"
            fetch_pdf = AsyncMock(return_value=_pdf_bytes())
            extract = Mock(return_value=_pdf_text())

            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(descriptor,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=fetch_pdf,
                ),
                patch(
                    "telegrambot.fishing_enrichment.extract_fpcv_pdf_text",
                    new=extract,
                ),
            ):
                first = asyncio.run(
                    refresh_fpcv_details(
                        NOW,
                        (_provincial_base(),),
                        state,
                    )
                )
                second = asyncio.run(
                    refresh_fpcv_details(
                        NOW + timedelta(days=1),
                        (_provincial_base(),),
                        state,
                    )
                )

            self.assertEqual(fetch_pdf.await_count, 2)
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(first[0]["content_sha256"], second[0]["content_sha256"])
            self.assertEqual(first[0]["document_identity"], second[0]["document_identity"])
            self.assertEqual(
                second[0]["observed_at"],
                (NOW + timedelta(days=1)).isoformat(),
            )

    def test_same_url_changed_pdf_bytes_are_reparsed(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "details.json"
            fetch_pdf = AsyncMock(
                side_effect=[
                    b"%PDF-1.7\nversion-one",
                    b"%PDF-1.7\nversion-two",
                ]
            )
            extract = Mock(side_effect=[_pdf_text(), _pdf_text()])

            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(descriptor,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=fetch_pdf,
                ),
                patch(
                    "telegrambot.fishing_enrichment.extract_fpcv_pdf_text",
                    new=extract,
                ),
            ):
                first = asyncio.run(
                    refresh_fpcv_details(NOW, (_provincial_base(),), state)
                )
                second = asyncio.run(
                    refresh_fpcv_details(
                        NOW + timedelta(days=1),
                        (_provincial_base(),),
                        state,
                    )
                )

            self.assertEqual(fetch_pdf.await_count, 2)
            self.assertEqual(extract.call_count, 2)
            self.assertNotEqual(
                first[0]["content_sha256"],
                second[0]["content_sha256"],
            )

    def test_same_document_fetch_failure_preserves_last_good_detail(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "details.json"
            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(descriptor,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=AsyncMock(return_value=_pdf_bytes()),
                ),
                patch(
                    "telegrambot.fishing_enrichment.extract_fpcv_pdf_text",
                    new=Mock(return_value=_pdf_text()),
                ),
            ):
                first = asyncio.run(
                    refresh_fpcv_details(
                        NOW,
                        (_provincial_base(),),
                        state,
                    )
                )

            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(descriptor,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=AsyncMock(
                        side_effect=FishingEnrichmentError(
                            "network down",
                            code="NETWORK",
                        )
                    ),
                ),
            ):
                second = asyncio.run(
                    refresh_fpcv_details(
                        NOW + timedelta(hours=12),
                        (_provincial_base(),),
                        state,
                    )
                )

            self.assertEqual(second, first)
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8"))["records"][0],
                first[0],
            )

    def test_changed_document_fetch_failure_withholds_old_detail(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]
        changed = dict(descriptor)
        changed["document_identity"] = "f" * 64

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "details.json"
            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(descriptor,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=AsyncMock(return_value=_pdf_bytes()),
                ),
                patch(
                    "telegrambot.fishing_enrichment.extract_fpcv_pdf_text",
                    new=Mock(return_value=_pdf_text()),
                ),
            ):
                asyncio.run(
                    refresh_fpcv_details(
                        NOW,
                        (_provincial_base(),),
                        state,
                    )
                )

            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(changed,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=AsyncMock(
                        side_effect=FishingEnrichmentError(
                            "network down",
                            code="NETWORK",
                        )
                    ),
                ),
            ):
                second = asyncio.run(
                    refresh_fpcv_details(
                        NOW + timedelta(hours=12),
                        (_provincial_base(),),
                        state,
                    )
                )

            self.assertEqual(second, ())
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8")),
                {"version": 1, "records": []},
            )

    def test_changed_pdf_bytes_with_parse_failure_withhold_old_detail(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "details.json"
            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(descriptor,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=AsyncMock(return_value=b"%PDF-1.7\nversion-one"),
                ),
                patch(
                    "telegrambot.fishing_enrichment.extract_fpcv_pdf_text",
                    new=Mock(return_value=_pdf_text()),
                ),
            ):
                asyncio.run(
                    refresh_fpcv_details(
                        NOW,
                        (_provincial_base(),),
                        state,
                    )
                )

            with (
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_index",
                    new=AsyncMock(return_value=(descriptor,)),
                ),
                patch(
                    "telegrambot.fishing_enrichment._fetch_fpcv_pdf_bytes",
                    new=AsyncMock(return_value=b"%PDF-1.7\nversion-two"),
                ),
                patch(
                    "telegrambot.fishing_enrichment.extract_fpcv_pdf_text",
                    new=Mock(
                        side_effect=FishingEnrichmentError(
                            "schema changed",
                            code="PDF-SCHEMA",
                        )
                    ),
                ),
            ):
                second = asyncio.run(
                    refresh_fpcv_details(
                        NOW + timedelta(hours=12),
                        (_provincial_base(),),
                        state,
                    )
                )

            self.assertEqual(second, ())
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8")),
                {"version": 1, "records": []},
            )

    def test_pdf_programme_must_match_declared_heat_duration(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]
        inconsistent = _pdf_text().replace(
            "21:00 h. Fin de la primera manga.",
            "20:30 h. Fin de la primera manga.",
        )

        with self.assertRaisesRegex(
            FishingEnrichmentError,
            "programme disagrees",
        ):
            parse_fpcv_convocatoria_text(
                inconsistent,
                descriptor=descriptor,
                content_sha256="e" * 64,
                observed_at=NOW,
            )

    def test_pdf_reviewed_heat_count_change_fails_closed(self):
        descriptor = parse_fpcv_index_html(
            _index_html(),
            local_day=NOW.date(),
            base_events=(_provincial_base(),),
        )[0]
        changed = _pdf_text().replace(
            "2 mangas de 3 horas",
            "3 mangas de 3 horas",
        )

        with self.assertRaisesRegex(
            FishingEnrichmentError,
            "reviewed heat contract changed",
        ):
            parse_fpcv_convocatoria_text(
                changed,
                descriptor=descriptor,
                content_sha256="f" * 64,
                observed_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
