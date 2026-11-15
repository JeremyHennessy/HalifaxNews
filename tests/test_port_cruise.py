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

class PortCoverageTests(unittest.TestCase):
    header='<table><tr><th>Date</th><th>Vessel</th><th>Cruise Line</th><th>Passengers</th></tr>'
    def test_denial_and_unrelated_table_are_errors(self):
        for html in ['<h1>Access denied</h1>','<table><tr><td>other</td></tr></table>',self.header+'</table>'+self.header+'</table>']:
            with self.assertRaises(ValueError): parse_html(html)
    def test_empty_identified_schedule_is_zero(self):
        self.assertEqual(parse_html(self.header+'</table>'),[])
    def test_yearless_invalid_and_truncated_rows_fail_closed(self):
        for cells in ['<td>11-15</td><td>Ship</td><td>Line</td><td>300</td>','<td>bad 2026</td><td>Ship</td><td>Line</td><td>300</td>','<td>November 15, 2026</td><td>Ship</td>']:
            with self.assertRaises(ValueError): parse_html(self.header+'<tr>'+cells+'</tr></table>')
    def test_only_passenger_column_used(self):
        html=self.header+'<tr><td>November 15, 2026</td><td>2026</td><td>3000</td><td>Unknown</td></tr></table>'
        rows=parse_html(html,datetime(2026,11,15,12,tzinfo=HALIFAX_TZ))
        self.assertEqual(rows[0].metadata,{})

    def test_partial_year_or_month_cannot_inherit_today(self):
        for date in ['2026', 'November 2026', '2026-11', 'November 15']:
            html=self.header+f'<tr><td>{date}</td><td>Ship</td><td>Line</td><td>300</td></tr></table>'
            with self.assertRaises(ValueError): parse_html(html,datetime(2026,11,15,12,tzinfo=HALIFAX_TZ))
