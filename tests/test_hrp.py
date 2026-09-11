from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hfxpulse.adapters.hrp import parse_hrp_html


class HRPParserTests(unittest.TestCase):
    def test_parses_current_release_cards_with_time(self):
        html = (ROOT / "tests" / "fixtures" / "hrp.html").read_text(encoding="utf-8")
        rows = parse_hrp_html(html)
        self.assertEqual(2, len(rows))

        first = rows[0]
        self.assertEqual("Halifax Regional Police", first.source)
        self.assertEqual("POLICE", first.category)
        self.assertEqual("Police lay firearm charges", first.title)
        self.assertEqual("2026-09-11T13:59:00Z", first.reported_at)
        self.assertEqual(2, first.severity)
        self.assertIn("firearm offences", first.summary)
        self.assertTrue(first.source_url.endswith("/police-lay-firearm-charges-4"))

        second = rows[1]
        self.assertEqual("Update: Police Operation on Adams Avenue", second.title)
        self.assertEqual("2026-09-11T11:25:00Z", second.reported_at)
        self.assertTrue(second.source_url.endswith("/update-police-operation-adams-avenue"))


if __name__ == "__main__":
    unittest.main()
