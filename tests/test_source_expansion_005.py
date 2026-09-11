from __future__ import annotations

import unittest
from datetime import datetime

from hfxpulse.adapters.marine_weather import parse_html as parse_marine
from hfxpulse.adapters.smu_alert import parse_html as parse_smu
from hfxpulse.adapters.water_alerts import parse_html as parse_water_alerts
from hfxpulse.util import HALIFAX_TZ


class WaterActiveAlertTests(unittest.TestCase):
    def test_active_alerts_exclude_past_alert_section(self):
        html = """
        <main>
          <div class='active-alert'>
            <a href='/alert/boil-water-test'>Precautionary Boil Water Advisory in Effect</a>
            <p>Published: 3:31 AM | December 7, 2025 Updated: 10:50 AM | December 9, 2025</p>
          </div>
          <h2>View Past Alerts</h2>
          <div><a href='/alert/old-alert'>Old Water Alert</a><p>Published: 9:00 AM | January 1, 2024</p></div>
        </main>
        """
        rows = parse_water_alerts(html)
        self.assertEqual(1, len(rows))
        self.assertEqual("boil_water_advisory", rows[0].subtype)
        self.assertTrue(rows[0].metadata["currently_active"])
        self.assertIn("2025-12-09", rows[0].reported_at)


class MarineWarningTests(unittest.TestCase):
    def test_current_halifax_harbour_warning(self):
        html = """
        <main>
          <section>
            <h3>Strong wind warning in effect</h3>
            <h4>Halifax Harbour and Approaches</h4>
            <p>Issued 3:30 PM ADT 21 July 2026</p>
            <p>'Strong' winds of 20 to 33 knots are occurring or expected.</p>
          </section>
        </main>
        """
        rows = parse_marine(html, datetime(2026, 7, 21, 16, 0, tzinfo=HALIFAX_TZ))
        self.assertEqual(1, len(rows))
        self.assertEqual("MARINE", rows[0].category)
        self.assertEqual("marine_weather_warning", rows[0].subtype)
        self.assertEqual("Halifax Harbour and Approaches", rows[0].location_text)
        self.assertTrue(rows[0].metadata["currently_active"])

    def test_no_warning_means_no_event(self):
        html = "<main><h2>Warnings</h2><p>No warnings in effect.</p></main>"
        self.assertEqual([], parse_marine(html, datetime(2026, 7, 21, 16, 0, tzinfo=HALIFAX_TZ)))


class SaintMarysAlertTests(unittest.TestCase):
    def test_normal_status_is_not_an_event(self):
        html = "<main><h1>Alert information</h1><h2>Saint Mary's is operating as usual</h2></main>"
        self.assertEqual([], parse_smu(html, datetime(2026, 9, 11, 15, 0, tzinfo=HALIFAX_TZ)))

    def test_closure_status_becomes_current_context(self):
        html = """
        <main>
          <h1>Alert information</h1>
          <h2>Campus closure due to emergency</h2>
          <p>Saint Mary's Halifax campus is closed until further notice. Please avoid campus.</p>
        </main>
        """
        rows = parse_smu(html, datetime(2026, 9, 11, 15, 0, tzinfo=HALIFAX_TZ))
        self.assertEqual(1, len(rows))
        self.assertEqual("Saint Mary's University alerts", rows[0].source)
        self.assertEqual("Saint Mary's University, Halifax", rows[0].location_text)
        self.assertTrue(rows[0].metadata["source_timestamp_missing"])


if __name__ == "__main__":
    unittest.main()
