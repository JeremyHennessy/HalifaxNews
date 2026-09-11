from __future__ import annotations

import unittest
from datetime import datetime, timezone

from hfxpulse.adapters import nshealth_status, water_alerts
from hfxpulse.collector import _apply_snapshot_lifecycle
from hfxpulse.models import Incident, SourceHealth


class NovaScotiaHealthStatusTests(unittest.TestCase):
    NOW = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)

    def test_urban_hrm_disruption_is_emitted_and_provincial_noise_is_not(self):
        html = """
        <main>
          <h2>2 Service Statuses, Closures, and Cancellations</h2>
          <div>Disruption</div>
          <a>QEII Health Sciences Centre - Halifax Infirmary</a>
          <div>(Halifax, NS)</div>
          <h3>Emergency Department</h3>
          <p>Emergency department access is temporarily disrupted. The department remains open.</p>
          <div>Disruption</div>
          <a>Roseway Hospital</a>
          <div>(Shelburne, NS)</div>
          <h3>Emergency Department</h3>
          <p>Emergency department is temporarily closed.</p>
          <p>For Emergencies, Call 9-1-1</p>
        </main>
        """
        rows = nshealth_status.parse_html(html, self.NOW)
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("EMS", row.category)
        self.assertEqual("health_service_disruption", row.subtype)
        self.assertIn("QEII", row.title)
        self.assertIn("Halifax", row.location_text)
        self.assertTrue(row.metadata["currently_active"])
        self.assertTrue(row.metadata["source_timestamp_missing"])

    def test_non_hrm_status_is_excluded(self):
        html = """
        <main>
          <div>Advisory</div><div>Yarmouth Regional Hospital</div><div>(Yarmouth, NS)</div>
          <h3>All Clinics, Programs and Services</h3><p>Parking is temporarily restricted.</p>
        </main>
        """
        self.assertEqual([], nshealth_status.parse_html(html, self.NOW))

    def test_emergency_department_closure_has_higher_source_severity(self):
        html = """
        <main>
          <div>Disruption</div><div>Dartmouth General Hospital</div><div>(Dartmouth, NS)</div>
          <h3>Emergency Department</h3><p>The emergency department is temporarily closed.</p>
        </main>
        """
        rows = nshealth_status.parse_html(html, self.NOW)
        self.assertEqual(1, len(rows))
        self.assertEqual(3, rows[0].severity)


class SnapshotLifecycleTests(unittest.TestCase):
    def _old_active(self) -> Incident:
        return Incident(
            id="water-alert-test",
            source=water_alerts.SOURCE,
            source_url="https://example.test/alert",
            title="Boil water advisory",
            summary="Active advisory",
            category="UTILITY",
            subtype="boil_water_advisory",
            reported_at="2026-09-11T12:00:00Z",
            metadata={"currently_active": True},
        )

    def _health(self, status: str) -> SourceHealth:
        return SourceHealth(
            source=water_alerts.SOURCE,
            url="https://www.halifaxwater.ca/alerts",
            authority="official",
            status=status,
            checked_at="2026-09-11T18:00:00Z",
        )

    def test_missing_row_from_healthy_snapshot_is_resolved(self):
        rows = _apply_snapshot_lifecycle([self._old_active()], [], [self._health("ok")])
        self.assertEqual(1, len(rows))
        self.assertEqual("resolved", rows[0].status)
        self.assertFalse(rows[0].metadata["currently_active"])
        self.assertTrue(rows[0].metadata["resolved_by_snapshot_absence"])

    def test_source_failure_does_not_false_resolve_active_row(self):
        rows = _apply_snapshot_lifecycle([self._old_active()], [], [self._health("error")])
        self.assertEqual("monitoring", rows[0].status)
        self.assertTrue(rows[0].metadata["currently_active"])
        self.assertTrue(rows[0].metadata["freshness_unverified"])

    def test_fresh_row_is_not_marked_resolved(self):
        old = self._old_active()
        fresh = self._old_active()
        rows = _apply_snapshot_lifecycle([old], [fresh], [self._health("ok")])
        self.assertEqual("active", rows[0].status)
        self.assertTrue(rows[0].metadata["currently_active"])


if __name__ == "__main__":
    unittest.main()
