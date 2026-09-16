import unittest

from telegrambot.pinned import YOUTH_CENTRE_MAP_URL, build_youth_centre


class YouthCentreMapLinkTests(unittest.TestCase):
    def test_uses_verified_google_maps_link(self):
        expected = "https://maps.app.goo.gl/HhfDRr6tpbbKekjM7"
        self.assertEqual(YOUTH_CENTRE_MAP_URL, expected)
        self.assertIn(expected, build_youth_centre())


if __name__ == "__main__":
    unittest.main()
