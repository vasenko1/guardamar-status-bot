import unittest
from unittest.mock import patch

import telegrambot.product_awards as awards
from telegrambot.product_awards import ReviewedImageSource


class ProductAwardImageRankingTests(unittest.TestCase):
    def test_lazy_priority_does_not_override_larger_explicit_src(self):
        source = ReviewedImageSource(
            name="Brand product",
            page_url="https://brand.example/product",
            page_hosts=frozenset({"brand.example"}),
            image_hosts=frozenset({"brand.example"}),
            page_markers=("Exact Product",),
            image_alt_markers=("Exact Product",),
        )
        html_source = (
            '<html><body><h1>Exact Product</h1>'
            '<img alt="Exact Product front" '
            'src="/exact.jpg?width=720" '
            'data-src="/exact.jpg?width=240"></body></html>'
        )
        with patch.object(awards, "_fetch_html", return_value=html_source):
            image = awards._resolve_reviewed_image_source(source)

        self.assertEqual(
            image.url,
            "https://brand.example/exact.jpg?width=720",
        )


if __name__ == "__main__":
    unittest.main()
