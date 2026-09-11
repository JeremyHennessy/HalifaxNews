from __future__ import annotations

import unittest

from hfxpulse.adapters.newsfeeds import parse_feed, relevant_news_item, relevant_news_text
from hfxpulse.collector import _revalidate_retained_rows
from hfxpulse.models import Incident


class NewsRelevanceTests(unittest.TestCase):
    def test_halifax_opinion_without_incident_signal_is_rejected(self):
        text = (
            "Osama bin Laden won. A Halifax columnist reflects on foreign policy, political rhetoric, "
            "and the consequences of war."
        )
        self.assertFalse(relevant_news_text(text))

    def test_incidental_incident_word_far_from_halifax_context_is_rejected(self):
        title = "Municipal leadership and public trust"
        desc = (
            "A Halifax columnist reflects on municipal politics and public life. "
            "Later in the essay, the author discusses police institutions in an international historical example."
        )
        self.assertFalse(relevant_news_item(title, desc))

    def test_non_halifax_incident_is_rejected(self):
        text = "Police investigate a collision and road closure in Yarmouth, Nova Scotia."
        self.assertFalse(relevant_news_text(text))

    def test_halifax_public_safety_story_is_accepted(self):
        text = "Halifax police close Barrington Street after a collision downtown."
        self.assertTrue(relevant_news_text(text))

    def test_local_politics_story_does_not_enter_feed(self):
        data = b"""<?xml version='1.0'?><rss><channel><item>
          <title>Municipal warden says he considers himself an average Joe</title>
          <link>https://example.test/politics</link>
          <pubDate>Fri, 11 Sep 2026 09:30:00 -0300</pubDate>
          <description>The Halifax publication spoke with the Municipality of the District of Yarmouth warden about public life and his work as a mechanic.</description>
        </item></channel></rss>"""
        self.assertEqual([], parse_feed(data, "Test News", "https://example.test/feed"))

    def test_real_halifax_closure_enters_feed(self):
        data = b"""<?xml version='1.0'?><rss><channel><item>
          <title>Police close Barrington Street after downtown collision</title>
          <link>https://example.test/incident</link>
          <pubDate>Fri, 11 Sep 2026 09:30:00 -0300</pubDate>
          <description>Halifax Regional Police say Barrington Street is closed between Duke and Sackville while officers investigate a collision.</description>
        </item></channel></rss>"""
        rows = parse_feed(data, "Test News", "https://example.test/feed")
        self.assertEqual(1, len(rows))
        self.assertEqual("POLICE", rows[0].category)

    def test_retained_news_is_revalidated_after_rules_change(self):
        bad = Incident(
            id="old-noise",
            source="Halifax Examiner",
            source_url="https://example.test/opinion",
            title="Municipal leadership and public trust",
            summary="A Halifax columnist reflects on public life and politics.",
            category="COMMUNITY",
            reported_at="2026-09-11T15:00:00Z",
            source_kind="news",
            confidence="reported",
        )
        good = Incident(
            id="real-news",
            source="CityNews Halifax",
            source_url="https://example.test/closure",
            title="Police close Barrington Street after downtown collision",
            summary="Halifax police say the street is closed while officers investigate a collision.",
            category="POLICE",
            reported_at="2026-09-11T15:00:00Z",
            source_kind="news",
            confidence="reported",
        )
        kept = _revalidate_retained_rows([bad, good])
        self.assertEqual(["real-news"], [row.id for row in kept])


if __name__ == "__main__":
    unittest.main()
