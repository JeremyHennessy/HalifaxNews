from __future__ import annotations

import unittest

from hfxpulse.models import Incident
from hfxpulse.normalization import cluster_events, event_type, normalize_observations


class NormalizationTests(unittest.TestCase):
    def _incident(self, **overrides):
        base = dict(
            id="x",
            source="Test",
            source_url="https://example.test",
            title="Test incident",
            summary="",
            category="POLICE",
            reported_at="2026-09-11T15:00:00Z",
            location_text="BARRINGTON ST, HALIFAX",
        )
        base.update(overrides)
        return Incident(**base)

    def test_event_listing_does_not_match_ert_inside_certified(self):
        row = self._incident(
            id="event-1",
            source="Downtown Halifax events",
            source_kind="event",
            confidence="listing",
            category="EVENT",
            title="Saturday nights are CERTIFIED at The Dome!!",
            location_text="Downtown Halifax",
        )
        self.assertEqual("public_event", event_type(row))

    def test_two_event_listings_are_not_clustered_together(self):
        a = self._incident(
            id="event-a",
            source="Downtown Halifax events",
            source_kind="event",
            confidence="listing",
            category="EVENT",
            title="Concert at venue A",
            location_text="Downtown Halifax",
        )
        b = self._incident(
            id="event-b",
            source="Downtown Halifax events",
            source_kind="event",
            confidence="listing",
            category="EVENT",
            title="Nightclub promotion at venue B",
            location_text="Downtown Halifax",
        )
        normalize_observations([a, b])
        events = cluster_events([a, b])
        self.assertEqual(2, len(events))

    def test_same_hrfe_call_clusters_across_sources(self):
        a = self._incident(
            id="hrfe-primary",
            source="Halifax Regional Fire & Emergency",
            source_kind="official",
            category="RESCUE",
            subtype="SALT WATER INCIDENT",
            title="Salt Water Incident",
            metadata={"call_number": "HF26000013629", "response": "DC02 E02 E15 FB1 JRCC PCE Q13 STN02"},
        )
        b = self._incident(
            id="hrfe-mirror",
            source="HRFE incident mirror · Bluesky",
            source_kind="secondary",
            confidence="secondary",
            category="RESCUE",
            subtype="SALT WATER INCIDENT",
            title="Salt Water Incident",
            metadata={"call_number": "HF26000013629", "response": "DC02 E02 E15 FB1 JRCC PCE Q13 STN02"},
        )
        normalize_observations([a, b])
        events = cluster_events([a, b])
        self.assertEqual(1, len(events))
        self.assertEqual(2, events[0].source_count)
        self.assertEqual(2, events[0].evidence_count)
        self.assertEqual("corroborated", events[0].confidence)
        self.assertIn("decoded_response", events[0].metadata)
        self.assertIn("Marine rescue response", events[0].metadata.get("response_summary", ""))

    def test_gtfs_alert_does_not_become_police_operation(self):
        row = self._incident(
            id="transit-1",
            source="Halifax Transit GTFS-Realtime",
            source_kind="official",
            category="TRANSIT",
            subtype="gtfs_realtime_alert",
            title="Route 24 trip cancelled",
        )
        self.assertEqual("transit_disruption", event_type(row))


if __name__ == "__main__":
    unittest.main()
