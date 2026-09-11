from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hfxpulse.adapters.hrfe import parse_hrfe_rss
from hfxpulse.unit_decode import build_response_summary, decode_response, decode_unit, decoded_unit_text


class UnitDecoderTests(unittest.TestCase):
    def test_decodes_lower_water_response(self):
        response = "DC02 E02 E15 FB1 JRCC PCE Q13 STN02"
        decoded = {row["code"]: row for row in decode_response(response)}

        self.assertEqual("District Chief 2", decoded["DC02"]["label"])
        self.assertEqual("Engine 2", decoded["E02"]["label"])
        self.assertEqual("Engine 15", decoded["E15"]["label"])
        self.assertEqual("Fire Boat 1 (Kjipuktuk)", decoded["FB1"]["label"])
        self.assertEqual("Joint Rescue Coordination Centre Halifax", decoded["JRCC"]["label"])
        self.assertEqual("Platoon Captain East", decoded["PCE"]["label"])
        self.assertEqual("inferred", decoded["PCE"]["confidence"])
        self.assertEqual("Quint 13", decoded["Q13"]["label"])
        self.assertEqual("Station 2 assignment", decoded["STN02"]["label"])

        summary = build_response_summary("SALT WATER INCIDENT", response)
        self.assertIn("Marine rescue response", summary)
        self.assertIn("Engines 2 and 15", summary)
        self.assertIn("Fire Boat 1 (Kjipuktuk)", summary)
        self.assertIn("District Chief 2", summary)
        self.assertIn("Platoon Captain East (inferred)", summary)
        self.assertIn("Joint Rescue Coordination Centre Halifax", summary)

    def test_decodes_common_hrfe_unit_families(self):
        expected = {
            "A03": "Aerial 3",
            "Q13": "Quint 13",
            "TCT12": "Tactical Unit 12",
            "PC1E": "Platoon Captain 1 East",
            "PCV1E": "Platoon Captain Volunteer 1 East",
            "R20": "Rescue 20",
            "T58": "Tanker 58",
            "EA04": "Engine 4 Alpha",
        }
        for code, label in expected.items():
            with self.subTest(code=code):
                self.assertEqual(label, decode_unit(code)["label"])

    def test_unknown_code_is_preserved(self):
        unit = decode_unit("ZZ99")
        self.assertEqual("ZZ99", unit["code"])
        self.assertEqual("unknown", unit["confidence"])
        self.assertIn("ZZ99", decoded_unit_text("ZZ99"))

    def test_hrfe_rss_adds_decoded_metadata_and_summary(self):
        data = (ROOT / "tests" / "fixtures" / "hrfe_rss.xml").read_bytes()
        rows = parse_hrfe_rss(data)
        self.assertEqual(2, len(rows))
        collision = rows[0]
        self.assertEqual("RESCUE", collision.category)
        self.assertEqual("E05 STN58 T58", collision.metadata["response"])
        self.assertEqual("Engine 5", collision.metadata["decoded_units"][0]["label"])
        self.assertIn("Rescue response", collision.summary)
        self.assertIn("Engine 5", collision.summary)


if __name__ == "__main__":
    unittest.main()
