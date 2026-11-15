import json
import tempfile
import unittest
from pathlib import Path
from hfxpulse.collector import collection_receipt, _previous_snapshot_clock

class CollectionReceiptTests(unittest.TestCase):
    def test_measured_gap_not_cadence(self):
        r = collection_receipt('2026-11-15T04:00:00Z','2026-11-15T04:00:12Z',12.1234,'2026-11-15T01:00:00Z')
        self.assertEqual(r['gap_since_previous_snapshot_seconds'],10800)
        self.assertEqual(r['elapsed_seconds'],12.123)
        self.assertIn('not_scheduler',r['scope'])
    def test_unknown_and_future_clock(self):
        r=collection_receipt('2026-11-15T04:00:00Z','2026-11-15T04:00:12Z',12,None)
        self.assertIsNone(r['gap_since_previous_snapshot_seconds'])
        r=collection_receipt('2026-11-15T04:00:00Z','2026-11-15T04:00:12Z',12,'2026-11-16T01:00:00Z')
        self.assertIsNone(r['gap_since_previous_snapshot_seconds'])
        self.assertEqual(r['previous_clock_status'],'future')
    def test_previous_untrusted_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.json'
            self.assertIsNone(_previous_snapshot_clock(p))
            for raw in ['broken','[]','null','{"generated_at":null}','{"generated_at":"tomorrow"}','{"generated_at":"2026-11-15T04:00:00"}']:
                p.write_text(raw)
                self.assertIsNone(_previous_snapshot_clock(p))
            p.write_text(json.dumps({'generated_at':'2026-11-15T04:00:00Z'}))
            self.assertEqual(_previous_snapshot_clock(p),'2026-11-15T04:00:00Z')
