from __future__ import annotations

import re
import unittest

from outreach_app.gtm_service.services.html_utils import meta_content, parse_html_document
from outreach_app.gtm_service.services.scraper import ProspectingScraper


class HTMLUtilsTest(unittest.TestCase):
    def test_parse_html_document_extracts_expected_fields(self) -> None:
        html = """
        <html>
          <head>
            <title>Example Co</title>
            <meta name="description" content="Useful description">
            <meta property="og:title" content="OG Example Co">
            <script>ignored()</script>
          </head>
          <body>
            <a href="/contact">Contact</a>
            <a href="https://external.example/team">Team</a>
            <p>Hello <b>world</b>.</p>
          </body>
        </html>
        """

        document = parse_html_document(html, base_url="https://example.com")

        self.assertEqual(document.title, "Example Co")
        self.assertEqual(document.links, ["https://example.com/contact", "https://external.example/team"])
        self.assertIn("Hello world.", document.text)
        self.assertNotIn("ignored", document.text)
        self.assertEqual(
            meta_content(document, selectors=[{"property": "og:title"}]),
            "OG Example Co",
        )
        self.assertEqual(
            meta_content(document, selectors=[{"name": re.compile(r"description", re.IGNORECASE)}]),
            "Useful description",
        )

    def test_candidate_contact_urls_uses_resolved_links(self) -> None:
        html = """
        <html>
          <body>
            <a href="/contact">Contact</a>
            <a href="mailto:hello@example.com">Email</a>
            <a href="/products">Products</a>
            <a href="https://external.example/team">Team</a>
          </body>
        </html>
        """

        urls = ProspectingScraper._candidate_contact_urls(None, html=html, base_url="https://example.com")

        self.assertEqual(urls, ["https://example.com/contact", "https://external.example/team"])


if __name__ == "__main__":
    unittest.main()
