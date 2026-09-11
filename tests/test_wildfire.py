from __future__ import annotations

import unittest
from datetime import datetime, timezone

from hfxpulse.adapters.wildfire import parse_payload


class WildfireSourceTests(unittest.TestCase):
    def test_nearby_active_fire_is_emitted(self):
        payload = {
            "features": [{"attributes": {
                "ObjectId": 10,
                "agency": "NS",
                "firename": "Test Lake",
                "lat": 44.80,
                "lon": -63.80,
                "startdate": "20260910",
                "hectares": 32.5,
                "stage_of_control": "BH",
                "response_type": "FUL",
            }}]
        }
        rows = parse_payload(payload, datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc))
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("EMERGENCY", row.category)
        self.assertEqual("being held", row.metadata["stage_of_control"])
        self.assertLess(row.metadata["distance_km"], 100)
        self.assertEqual(32.5, row.metadata["hectares"])
        self.assertIn("2026-09-10", row.reported_at)

    def test_distant_nova_scotia_fire_is_not_halifax_context(self):
        payload = {
            "features": [{"attributes": {
                "ObjectId": 11,
                "agency": "NS",
                "firename": "Far Cape Breton",
                "lat": 46.20,
                "lon": -60.30,
                "startdate": "20260910",
                "hectares": 500,
                "stage_of_control": "OC",
            }}]
        }
        self.assertEqual([], parse_payload(payload, datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)))

    def test_extinguished_fire_is_not_active_event(self):
        payload = {
            "features": [{"attributes": {
                "ObjectId": 12,
                "agency": "NS",
                "firename": "Old Fire",
                "lat": 44.75,
                "lon": -63.70,
                "startdate": "20260901",
                "hectares": 4,
                "stage_of_control": "OUT",
            }}]
        }
        self.assertEqual([], parse_payload(payload, datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)))

    def test_non_nova_scotia_coordinate_is_rejected(self):
        payload = {
            "features": [{"attributes": {
                "ObjectId": 13,
                "agency": "NB",
                "firename": "New Brunswick Fire",
                "lat": 46.10,
                "lon": -67.20,
                "startdate": "20260910",
                "stage_of_control": "OC",
            }}]
        }
        self.assertEqual([], parse_payload(payload, datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
