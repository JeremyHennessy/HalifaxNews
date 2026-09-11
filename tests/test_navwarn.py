from __future__ import annotations

import unittest
from datetime import datetime, timezone

from hfxpulse.adapters.navwarn import parse_html


class NavwarnParserTests(unittest.TestCase):
    NOW = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)

    def test_recent_halifax_warning_is_emitted(self):
        html = """
        <table><tbody><tr>
          <td><a href="/public/rest/messages/en/message/NW-A-2026-123">NW-A-2026-12</a></td>
          <td>2026-09-11 14:30 UTC</td>
          <td>Marine works - Halifax Harbour and Approaches</td>
          <td>Diving operations near the Halifax waterfront. Navigation restricted in the work area.</td>
        </tr></tbody></table>
        """
        rows = parse_html(html, self.NOW)
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("MARINE", row.category)
        self.assertEqual("navigational_warning", row.subtype)
        self.assertEqual("NW-A-2026-12", row.metadata["navwarn_id"])
        self.assertEqual(2, row.severity)
        self.assertTrue(row.metadata["currently_active"])
        self.assertIn("Marine works", row.title)

    def test_old_halifax_warning_is_excluded(self):
        html = """
        <table><tr>
          <td>NW-A-2026-11</td>
          <td>2026-09-05 10:00 UTC</td>
          <td>Halifax Harbour - aid to navigation unlit</td>
        </tr></table>
        """
        self.assertEqual([], parse_html(html, self.NOW))

    def test_recent_non_halifax_warning_is_excluded(self):
        html = """
        <table><tr>
          <td>NW-A-2026-10</td>
          <td>2026-09-11 16:00 UTC</td>
          <td>Sydney Harbour - dredging operations</td>
        </tr></table>
        """
        self.assertEqual([], parse_html(html, self.NOW))

    def test_duplicate_navwarn_id_is_deduplicated(self):
        html = """
        <table><tbody>
          <tr>
            <td>NW-A-2026-09</td><td>2026-09-11 15:00 UTC</td>
            <td>Bedford Basin - marine works</td>
          </tr>
          <tr>
            <td>NW-A-2026-09</td><td>2026-09-11 15:00 UTC</td>
            <td>Bedford Basin - marine works</td>
          </tr>
        </tbody></table>
        """
        rows = parse_html(html, self.NOW)
        self.assertEqual(1, len(rows))
        self.assertEqual("NW-A-2026-09", rows[0].metadata["navwarn_id"])

    def test_high_risk_navigation_closure_scores_more_severe(self):
        html = """
        <table><tr>
          <td>NW-A-2026-08</td>
          <td>2026-09-11 17:00 UTC</td>
          <td>Halifax Harbour closed to navigation due to search and rescue operation</td>
        </tr></table>
        """
        rows = parse_html(html, self.NOW)
        self.assertEqual(1, len(rows))
        self.assertEqual(3, rows[0].severity)


if __name__ == "__main__":
    unittest.main()
