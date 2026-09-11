from __future__ import annotations

import unittest

from hfxpulse.models import Incident
from hfxpulse.news_context import attach_news_context, extractive_brief


class NewsContextQualityTests(unittest.TestCase):
    def test_headline_only_feed_item_is_not_a_summary(self):
        title = "Man, woman charged with firearm offences in Halifax, police say - CTV News"
        self.assertEqual("", extractive_brief(title, title))

    def test_informative_source_beats_headline_only_source(self):
        headline_only = Incident(
            id="news-headline",
            source="CTV News Atlantic",
            source_url="https://example.test/ctv",
            title="Man, woman charged with firearm offences in Halifax, police say - CTV News",
            summary="Man, woman charged with firearm offences in Halifax, police say - CTV News",
            category="POLICE",
            reported_at="2026-09-11T15:00:00Z",
            source_kind="news",
            confidence="reported",
        )
        detailed = Incident(
            id="news-detailed",
            source="CityNews Halifax",
            source_url="https://example.test/citynews",
            title="Man, woman facing gun charges after search of home near Dockyard",
            summary="Police laid more than a dozen charges after officers searched a home on Adams Avenue in Halifax. Several roads were closed during the operation.",
            category="POLICE",
            reported_at="2026-09-11T15:05:00Z",
            source_kind="news",
            confidence="reported",
        )
        headline_only.source_class = "news"
        detailed.source_class = "news"
        event = Incident(
            id="evt-news",
            source="2 sources",
            source_url=detailed.source_url,
            title=detailed.title,
            summary="News report.",
            category="POLICE",
            reported_at=detailed.reported_at,
            source_kind="news",
            confidence="corroborated",
            related_ids=[headline_only.id, detailed.id],
        )

        attach_news_context([event], [headline_only, detailed])
        self.assertIn("Adams Avenue", event.summary)
        self.assertEqual("CityNews Halifax", event.metadata["news_summary_source"])
        self.assertEqual(2, event.metadata["news_source_count"])


if __name__ == "__main__":
    unittest.main()
