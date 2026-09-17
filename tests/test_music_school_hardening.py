import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from telegrambot.music_school import (
    _normalize_posts,
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


def _registration_post():
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


class MusicSchoolHardeningTests(unittest.TestCase):
    def test_unrelated_future_season_does_not_replace_programme_season(self):
        unrelated = _post(
            99,
            "2026-09-12",
            "Concierto temporada 2027-2028",
            "<p>La banda presenta su temporada 2027-2028.</p>",
        )
        catalog = _normalize_posts([_registration_post(), unrelated], NOW)
        self.assertEqual(catalog["season"], "2026/27")

    def test_snapshot_urls_reject_userinfo_and_nonstandard_ports(self):
        catalog = _normalize_posts([_registration_post()], NOW)

        bad_schedule = dict(catalog)
        bad_schedule["schedule_url"] = "https://user@amguardamar.es/horarios/"
        self.assertFalse(valid_music_school_snapshot(bad_schedule))

        bad_schedule = dict(catalog)
        bad_schedule["schedule_url"] = "https://amguardamar.es:444/horarios/"
        self.assertFalse(valid_music_school_snapshot(bad_schedule))

        bad_registration = dict(catalog)
        bad_registration["jardin_registration"] = dict(
            catalog["jardin_registration"]
        )
        bad_registration["jardin_registration"]["url"] = (
            "https://user@cutt.ly/AMG_Matricula_JM_2627"
        )
        self.assertFalse(valid_music_school_snapshot(bad_registration))


if __name__ == "__main__":
    unittest.main()
