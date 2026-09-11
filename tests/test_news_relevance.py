from __future__ import annotations

import unittest

from hfxpulse.adapters.newsfeeds import parse_feed, relevant_news_text


class NewsRelevanceTests(unittest.TestCase):
    def test_halifax_opinion_without_incident_signal_is_rejected(self):
        text = (
            "Osama bin Laden won. A Halifax columnist reflects on foreign policy, political rhetoric, "
            "and the consequences of war."
        )
        self.assertFalse(relevant_news_text(text))

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


if __name__ == "__main__":
    unittest.main()
