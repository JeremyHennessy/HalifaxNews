from __future__ import annotations

import unittest

from hfxpulse.models import Incident
from hfxpulse.news_context import attach_news_context, extractive_brief


class NewsContextTests(unittest.TestCase):
    def test_extracts_clean_brief_from_feed_excerpt(self):
        title = "Police close Barrington Street after downtown incident"
        summary = (
            "Police close Barrington Street after downtown incident: Halifax Regional Police say the street "
            "is closed between Duke and Sackville while officers investigate. Drivers are asked to use another route. "
            "Read more at the source."
        )
        brief = extractive_brief(summary, title, max_chars=260)
        self.assertIn("Halifax Regional Police", brief)
        self.assertIn("Duke and Sackville", brief)
        self.assertNotIn("Read more", brief)
        self.assertFalse(brief.lower().startswith(title.lower()))

    def test_news_only_event_uses_feed_grounded_summary(self):
        news = Incident(
            id="news-1",
            source="CityNews Halifax",
            source_url="https://example.test/news-1",
            title="Fire crews respond downtown",
            summary="Fire crews were called to a building on Hollis Street shortly after noon. No injuries were reported in the initial update.",
            category="FIRE",
            subtype="news_report",
            reported_at="2026-09-11T15:00:00Z",
            source_kind="news",
            confidence="reported",
        )
        news.source_class = "news"
        event = Incident(
            id="evt-1",
            source="CityNews Halifax",
            source_url=news.source_url,
            title=news.title,
            summary="News report.",
            category="FIRE",
            reported_at=news.reported_at,
            source_kind="news",
            confidence="reported",
            related_ids=[news.id],
        )
        attach_news_context([event], [news])
        self.assertIn("Hollis Street", event.summary)
        self.assertEqual("extractive_feed_text", event.metadata["news_summary_basis"])
        self.assertEqual(1, event.metadata["news_source_count"])
        self.assertEqual("CityNews Halifax", event.metadata["news_sources"][0]["source"])

    def test_response_summary_is_not_overwritten_by_news(self):
        dispatch = Incident(
            id="fire-1",
            source="Halifax Regional Fire & Emergency",
            source_url="https://example.test/fire",
            title="Salt Water Incident",
            summary="Marine rescue response.",
            category="RESCUE",
            reported_at="2026-09-11T14:00:00Z",
            source_kind="official",
            confidence="official",
        )
        news = Incident(
            id="news-2",
            source="CBC Nova Scotia",
            source_url="https://example.test/news-2",
            title="Search underway in Halifax Harbour",
            summary="Emergency crews and the Coast Guard were searching the harbour near the waterfront Thursday afternoon.",
            category="RESCUE",
            reported_at="2026-09-11T14:10:00Z",
            source_kind="news",
            confidence="reported",
        )
        dispatch.source_class = "first_party"
        news.source_class = "news"
        event = Incident(
            id="evt-2",
            source="2 sources",
            source_url=dispatch.source_url,
            title=dispatch.title,
            summary="Marine rescue response.",
            category="RESCUE",
            reported_at=news.reported_at,
            source_kind="official",
            confidence="corroborated",
            related_ids=[dispatch.id, news.id],
            metadata={"response_summary": "Marine rescue response involving Fire Boat 1 and JRCC Halifax."},
        )
        attach_news_context([event], [dispatch, news])
        self.assertEqual("Marine rescue response.", event.summary)
        self.assertIn("Coast Guard", event.metadata["news_summary"])


if __name__ == "__main__":
    unittest.main()
