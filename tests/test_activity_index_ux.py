import unittest

from telegrambot.pinned import build_activities
from telegrambot.sporttia import SPORTTIA_ACTIVITY_KEYS


class ActivityIndexUxTests(unittest.TestCase):
    def _render(self):
        sport_links = {
            key: f"https://t.me/c/123/{100 + index}"
            for index, key in enumerate(SPORTTIA_ACTIVITY_KEYS)
        }
        music_links = {
            "music_basics": "https://t.me/c/123/201",
            "music_vocal": "https://t.me/c/123/202",
            "music_instruments": "https://t.me/c/123/203",
        }
        return build_activities(
            swimming_link="https://t.me/c/123/90",
            sport_links=sport_links,
            football_link="https://t.me/c/123/91",
            music_links=music_links,
        )

    def test_sport_order_is_curated_for_mobile_scan(self):
        text = self._render()
        labels = [
            "Футбол",
            "Плавание",
            "Художественная гимнастика",
            "Дзюдо",
            "Мультиспорт",
            "Психомоторика · 2–6 лет",
            "DEPORTE +",
            "Инклюзивный мультиспорт · 7+",
            "Гимнастика для старших",
            "Гимнастика Mujeres",
        ]
        positions = [text.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_index_uses_short_informative_labels_only(self):
        text = self._render()
        for expected in (
            "Психомоторика · 2–6 лет",
            "Инклюзивный мультиспорт · 7+",
            "Гимнастика для старших",
            "Гимнастика Mujeres",
            "Музыкальная грамота",
            "Вокал и хор",
            "Инструменты",
        ):
            self.assertIn(expected, text)
        for old in (
            "Гимнастика для старшего возраста",
            "Гимнастика Asociación Mujeres",
            "Музыкальное развитие и грамота",
            "Музыкальные инструменты",
        ):
            self.assertNotIn(old, text)

    def test_detail_card_titles_are_not_changed_by_index_labels(self):
        from telegrambot.pinned import MUSIC_ACTIVITY_META, SPORT_ACTIVITY_META

        self.assertEqual(
            SPORT_ACTIVITY_META["senior_gymnastics"][1],
            "Гимнастика для старшего возраста",
        )
        self.assertEqual(
            SPORT_ACTIVITY_META["women_gymnastics"][1],
            "Гимнастика Asociación Mujeres",
        )
        self.assertEqual(
            MUSIC_ACTIVITY_META["music_basics"][1],
            "Музыкальное развитие и грамота",
        )
        self.assertEqual(
            MUSIC_ACTIVITY_META["music_instruments"][1],
            "Музыкальные инструменты",
        )


if __name__ == "__main__":
    unittest.main()
