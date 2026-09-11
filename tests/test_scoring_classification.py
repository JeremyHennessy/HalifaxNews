from __future__ import annotations

import unittest
from datetime import datetime, timezone

from hfxpulse.models import Incident
from hfxpulse.scoring import score_incidents


class ClassificationRegressionTests(unittest.TestCase):
    def test_certified_club_promotion_cannot_trigger_ert_tactical_match(self):
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        row = Incident(
            id='event-certified',
            source='Downtown Halifax events',
            source_url='https://example.test/event',
            title='Saturday nights are CERTIFIED at The Dome!!',
            summary='Saturday nights are CERTIFIED at The Dome!!',
            category='EVENT',
            reported_at=now,
            source_kind='event',
            confidence='listing',
            subtype='downtown_event',
            location_text='Downtown Halifax',
        )
        score_incidents([row])
        self.assertLessEqual(row.seriousness_score, 8)
        self.assertLessEqual(row.priority_score, 19)
        self.assertEqual('low', row.priority_band)
        self.assertNotIn('tactical response', row.attention_reasons)

    def test_gtfs_alert_word_does_not_match_ert(self):
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        row = Incident(
            id='transit-alert',
            source='Halifax Transit GTFS-Realtime',
            source_url='https://example.test/transit',
            title='Route 24 service alert',
            summary='Route 24 trip is cancelled',
            category='TRANSIT',
            reported_at=now,
            source_kind='official',
            confidence='official',
            subtype='gtfs_realtime_alert',
        )
        score_incidents([row])
        self.assertLess(row.seriousness_score, 78)
        self.assertNotIn('tactical response', row.attention_reasons)

    def test_standalone_ert_still_scores_as_tactical_response(self):
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        row = Incident(
            id='police-ert',
            source='Police',
            source_url='https://example.test/police',
            title='ERT deployed to barricaded person call',
            summary='Emergency Response Team is on scene',
            category='POLICE',
            reported_at=now,
            source_kind='official',
            confidence='official',
        )
        score_incidents([row])
        self.assertGreaterEqual(row.seriousness_score, 78)
        self.assertIn('tactical response', row.attention_reasons)


if __name__ == '__main__':
    unittest.main()
