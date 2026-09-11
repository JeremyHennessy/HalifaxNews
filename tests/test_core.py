from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hfxpulse.adapters.hrfe import parse_hrfe_text
from hfxpulse.adapters.ns511 import parse_text_report
from hfxpulse.adapters.weather import parse_atom
from hfxpulse.correlation import correlate
from hfxpulse.models import Incident
from hfxpulse.util import apparatus_count, normalized_place


class HRFEParserTests(unittest.TestCase):
    def test_parses_public_labels(self):
        text = (ROOT / "tests" / "fixtures" / "hrfe.txt").read_text(encoding="utf-8")
        rows = parse_hrfe_text(text)
        self.assertEqual(2, len(rows))
        alarm = rows[0]
        self.assertEqual("hrfe-hf26000011831", alarm.id)
        self.assertEqual("FIRE", alarm.category)
        self.assertEqual("BARRINGTON ST, HALIFAX", alarm.location_text)
        self.assertEqual("A03 E02 E03 STN02", alarm.metadata["response"])
        self.assertEqual(3, apparatus_count(alarm.metadata["response"]))
        self.assertGreater(alarm.siren_score, 0)

    def test_collision_maps_to_rescue(self):
        text = (ROOT / "tests" / "fixtures" / "hrfe.txt").read_text(encoding="utf-8")
        row = parse_hrfe_text(text)[1]
        self.assertEqual("RESCUE", row.category)
        self.assertIn("COLLISION", row.subtype)


class CorrelationTests(unittest.TestCase):
    def test_two_official_sources_upgrade_to_corroborated(self):
        a = Incident(
            id="a", source="fire", source_url="x", title="Alarm", summary="", category="FIRE",
            reported_at="2026-09-11T11:00:00Z", location_text="BARRINGTON ST, HALIFAX"
        )
        b = Incident(
            id="b", source="police", source_url="y", title="Closure", summary="", category="POLICE",
            reported_at="2026-09-11T11:15:00Z", location_text="Barrington Street"
        )
        correlate([a,b])
        self.assertEqual("corroborated", a.confidence)
        self.assertEqual("corroborated", b.confidence)
        self.assertIn("b", a.related_ids)

    def test_community_does_not_create_corroborated_official(self):
        a = Incident(
            id="a", source="fire", source_url="x", title="Alarm", summary="", category="FIRE",
            reported_at="2026-09-11T11:00:00Z", location_text="BARRINGTON ST, HALIFAX"
        )
        b = Incident(
            id="b", source="reddit", source_url="y", title="sirens", summary="", category="COMMUNITY",
            reported_at="2026-09-11T11:10:00Z", location_text="Barrington", source_kind="community", confidence="unverified"
        )
        correlate([a,b])
        self.assertEqual("official", a.confidence)
        self.assertEqual("unverified", b.confidence)


class OtherParserTests(unittest.TestCase):
    def test_511_text_report_filters_to_hrm(self):
        html = (ROOT / "tests" / "fixtures" / "511.html").read_text(encoding="utf-8")
        rows = parse_text_report(html)
        self.assertEqual(1, len(rows))
        self.assertEqual("TRAFFIC", rows[0].category)
        self.assertIn("Macdonald Bridge", rows[0].title)

    def test_environment_canada_atom(self):
        data = (ROOT / "tests" / "fixtures" / "weather.xml").read_bytes()
        rows = parse_atom(data)
        self.assertEqual(1, len(rows))
        self.assertEqual("WEATHER", rows[0].category)
        self.assertEqual("Rainfall warning in effect", rows[0].title)


class UtilityTests(unittest.TestCase):
    def test_normalized_place(self):
        self.assertEqual("BARRINGTON", normalized_place("Barrington St, Halifax"))


if __name__ == "__main__":
    unittest.main()
