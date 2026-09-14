from __future__ import annotations

import unittest
from datetime import datetime

from hfxpulse.adapters.port_cruise import parse_html
from hfxpulse.util import HALIFAX_TZ


class PortCruiseParserTests(unittest.TestCase):
    def test_same_day_cruise_calls_are_emitted(self):
        html = """
        <table>
          <thead><tr><th>Date</th><th>Vessel</th><th>Cruise Line</th><th>Passengers</th><th>Scheduled Arrival</th><th>Estimated Departure</th><th>Pier</th></tr></thead>
          <tbody>
            <tr><td>September 14, 2026</td><td>Norwegian Escape</td><td>Norwegian Cruise Line</td><td>4,248</td><td>07:00</td><td>14:00</td><td>22</td></tr>
            <tr><td>September 15, 2026</td><td>AIDAdiva</td><td>AIDA</td><td>2,030</td><td>Overnight</td><td>15:00</td><td>20</td></tr>
          </tbody>
        </table>
        """
        now = datetime(2026, 9, 14, 12, 0, tzinfo=HALIFAX_TZ)
        rows = parse_html(html, now)
        self.assertEqual(1, len(rows))
        self.assertIn("Norwegian Escape", rows[0].title)
        self.assertEqual("4,248", rows[0].metadata["passengers"])
        self.assertEqual("listing", rows[0].confidence)


if __name__ == "__main__":
    unittest.main()
