import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from telegrambot.music_school import (
    API_HOST,
    MusicSchoolSourceError,
    _allowed_url,
    _normalize_posts,
    _request_url,
    merge_music_school_catalog,
    registration_is_open,
    valid_music_school_snapshot,
)


TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=TZ)


def _post(identifier, day, title, content, link=None):
    return {
        "id": identifier,
        "date": f"{day}T10:00:00",
        "modified": f"{day}T11:00:00",
        "link": link or f"https://amguardamar.es/{day.replace('-', '/')}/post-{identifier}/",
        "title": {"rendered": title},
        "content": {"rendered": content},
    }


def _general_registration():
    return _post(
        1,
        "2026-09-01",
        "Últimos días de matrícula para el curso 2026-2027",
        """
        <p>Del 1 al 7 de septiembre de 2026 estará abierto el periodo extraordinario.</p>
        <a href="https://cutt.ly/AMG_Matricula_EM_2627">Escuela</a>
        <a href="https://cutt.ly/AMG_Matricula_JM_2627">Jardín</a>
        """,
    )


def _jardin_extension():
    return _post(
        2,
        "2026-09-08",
        "El Jardín Musical amplía excepcionalmente su matrícula hasta el 17 de septiembre",
        """
        <p>Jardín Musical · curso 2026-2027.</p>
        <p>Matrícula abierta hasta el 17 de septiembre.</p>
        <a href="https://cutt.ly/AMG_Matricula_JM_2627">Matrícula</a>
        """,
    )


def _schedule():
    return _post(
        3,
        "2026-07-15",
        "Horarios y grupos de las asignaturas conjuntas para el curso 2026-2027",
        """
        <p>Lenguaje Musical</p>
        <p>Conjunto Instrumental</p>
        <p>Banda Escuela</p>
        <p>Coro/Técnica Vocal</p>
        <a href="https://drive.google.com/file/d/private-list/view">documento</a>
        """,
        link=(
            "https://amguardamar.es/2026/07/15/"
            "horarios-asignaturas-conjuntas-curso-2026-2027/"
        ),
    )


class MusicSchoolSourceTests(unittest.TestCase):
    def test_request_is_one_bounded_recent_posts_page(self):
        url = _request_url()
        self.assertTrue(_allowed_url(url))
        self.assertIn("per_page=12", url)
        self.assertIn("orderby=modified", url)
        self.assertFalse(_allowed_url("https://example.com/wp-json/wp/v2/posts"))
        self.assertFalse(_allowed_url(f"https://{API_HOST}/wp-json/wp/v2/pages"))

    def test_normalizes_current_season_registration_and_safe_schedule_post(self):
        catalog = _normalize_posts(
            [_jardin_extension(), _general_registration(), _schedule()], NOW
        )

        self.assertEqual(catalog["season"], "2026/27")
        self.assertEqual(
            catalog["jardin_registration"],
            {
                "start": "2026-09-01",
                "end": "2026-09-17",
                "url": "https://cutt.ly/AMG_Matricula_JM_2627",
            },
        )
        self.assertEqual(
            catalog["school_registration"],
            {
                "start": "2026-09-01",
                "end": "2026-09-07",
                "url": "https://cutt.ly/AMG_Matricula_EM_2627",
            },
        )
        self.assertEqual(
            catalog["schedule_url"],
            "https://amguardamar.es/2026/07/15/horarios-asignaturas-conjuntas-curso-2026-2027/",
        )
        self.assertNotIn("drive.google.com", catalog["schedule_url"])
        self.assertTrue(valid_music_school_snapshot(catalog))

    def test_extension_without_general_post_starts_on_publication_day(self):
        catalog = _normalize_posts([_jardin_extension()], NOW)
        self.assertEqual(catalog["jardin_registration"]["start"], "2026-09-08")
        self.assertEqual(catalog["jardin_registration"]["end"], "2026-09-17")

    def test_latest_season_wins(self):
        old = _post(
            10,
            "2025-09-01",
            "Matrícula curso 2025-2026",
            '<p>Del 1 al 8 de septiembre de 2025.</p>'
            '<a href="https://cutt.ly/AMG_Matricula_EM_2526">Escuela</a>',
        )
        current = _normalize_posts([old, _general_registration()], NOW)
        self.assertEqual(current["season"], "2026/27")

    def test_no_season_fails_closed(self):
        irrelevant = _post(
            99,
            "2026-09-12",
            "Concierto",
            "<p>Actuación este sábado.</p>",
        )
        with self.assertRaises(MusicSchoolSourceError) as raised:
            _normalize_posts([irrelevant], NOW)
        self.assertEqual(raised.exception.diagnostic_code, "NO-SEASON")

    def test_same_season_merge_preserves_fields_that_leave_recent_window(self):
        previous = _normalize_posts(
            [_general_registration(), _schedule()], NOW
        )
        current = dict(previous)
        current["observed_at"] = datetime(2026, 9, 18, 12, 0, tzinfo=TZ).isoformat()
        current["schedule_url"] = None
        current["school_registration"] = None

        merged = merge_music_school_catalog(previous, current)
        self.assertEqual(merged["schedule_url"], previous["schedule_url"])
        self.assertEqual(
            merged["school_registration"], previous["school_registration"]
        )

    def test_new_season_does_not_inherit_old_links(self):
        previous = _normalize_posts(
            [_general_registration(), _schedule()], NOW
        )
        current = {
            "observed_at": datetime(2027, 6, 10, 12, 0, tzinfo=TZ).isoformat(),
            "season": "2027/28",
            "schedule_url": None,
            "jardin_registration": None,
            "school_registration": None,
        }
        merged = merge_music_school_catalog(previous, current)
        self.assertIsNone(merged["schedule_url"])
        self.assertIsNone(merged["school_registration"])

    def test_registration_open_uses_explicit_dates_only(self):
        catalog = _normalize_posts(
            [_jardin_extension(), _general_registration(), _schedule()], NOW
        )
        self.assertTrue(
            registration_is_open(catalog, "jardin_registration", date(2026, 9, 17))
        )
        self.assertFalse(
            registration_is_open(catalog, "jardin_registration", date(2026, 9, 18))
        )
        self.assertFalse(
            registration_is_open(catalog, "school_registration", date(2026, 9, 17))
        )

    def test_validator_rejects_drive_schedule_and_naive_observation(self):
        catalog = _normalize_posts(
            [_general_registration(), _schedule()], NOW
        )
        broken = dict(catalog)
        broken["schedule_url"] = "https://drive.google.com/file/d/x/view"
        self.assertFalse(valid_music_school_snapshot(broken))
        broken = dict(catalog)
        broken["observed_at"] = "2026-09-17T12:00:00"
        self.assertFalse(valid_music_school_snapshot(broken))


if __name__ == "__main__":
    unittest.main()
