from __future__ import annotations

import unittest
from datetime import datetime

from hfxpulse.adapters.port_cruise import parse_html
from hfxpulse.util import HALIFAX_TZ


class PortCruiseParserTests(unittest.TestCase):
    def test_parses_same_day_mm_dd_schedule_row(self):
        html = '''
        <table><tbody>
          <tr><th>Date</th><th>Vessel</th><th>Cruise Line</th><th>Passengers</th><th>Scheduled Arrival</th><th>Estimated Departure</th><th>Pier</th></tr>
          <tr><td>09-11</td><td>TEST VESSEL</td><td>TEST LINE</td><td>2,500</td><td>08:00</td><td>18:00</td><td>22</td></tr>
          <tr><td>09-12</td><td>TOMORROW VESSEL</td><td>TEST LINE</td><td>1,000</td><td>09:00</td><td>17:00</td><td>20</td></tr>
        </tbody></table>
        '''
        now = datetime(2026, 9, 11, 12, 0, tzinfo=HALIFAX_TZ)
        rows = parse_html(html, now=now)
        self.assertEqual(1, len(rows))
        self.assertIn("TEST VESSEL", rows[0].title)
        self.assertEqual("MARINE", rows[0].category)
        self.assertEqual("listing", rows[0].confidence)
        self.assertEqual("2,500", rows[0].metadata.get("passengers"))


if __name__ == "__main__":
    unittest.main()
