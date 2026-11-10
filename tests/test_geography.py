from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hfxpulse.geocode import _query, cache_key, enrich
from hfxpulse.models import Incident
from hfxpulse.normalization import cluster_events, normalize_observations
from hfxpulse.scoring import _downtown


def incident(**changes):
    values = dict(id='x', source='Test', source_url='https://example.test', title='Alarms',
                  summary='', category='FIRE', reported_at='2026-11-10T10:00:00Z')
    values.update(changes)
    return Incident(**values)


class GeographyTests(unittest.TestCase):
    def test_sackville_requires_street_not_community_or_drive(self):
        for location in ('Lynnville Drive, Lower Sackville', 'Middle Sackville',
                         'Upper Sackville', 'Sackville Drive', 'Sackville', 'Sackville Drive, Halifax'):
            with self.subTest(location=location):
                row = incident(location_text=location, neighbourhood='DOWNTOWN')
                normalize_observations([row])
                self.assertNotEqual(row.neighbourhood, 'DOWNTOWN')
                self.assertFalse(_downtown(row))
        for location in ('SACKVILLE ST, HALIFAX', 'Sackville Street, Halifax'):
            row = incident(location_text=location)
            normalize_observations([row])
            self.assertEqual(row.neighbourhood, 'DOWNTOWN')
            self.assertTrue(_downtown(row))

    def test_cache_keys_keep_locality_and_street_type(self):
        locations = ('ATLANTIC ST, DARTMOUTH', 'ATLANTIC ST, HALIFAX', 'ATLANTIC DR, HALIFAX')
        self.assertEqual(len({cache_key(location) for location in locations}), 3)
        self.assertEqual(cache_key(' / , '), '')
        self.assertNotIn('Halifax', _query(locations[0]))
        self.assertIn('DARTMOUTH', _query(locations[0]))

    def test_legacy_cache_and_retained_approximation_are_not_reused(self):
        row = incident(location_text='ATLANTIC ST, DARTMOUTH', lat=44.6322456,
                       lon=-63.5757861, location_precision='approximate_geocode')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.json'
            path.write_text(json.dumps({'ATLANTIC': {'lat': row.lat, 'lon': row.lon}}))
            with patch.dict(os.environ, {'HFXPULSE_GEOCODE': '1'}), patch('hfxpulse.geocode.session') as session:
                cache = enrich([row], path, max_new=0)
                session.return_value.get.assert_not_called()
            self.assertIsNone(row.lat)
            self.assertIsNone(row.lon)
            self.assertNotIn('ATLANTIC', cache)

    def test_disabled_geocoding_still_invalidates_legacy_not_source_geometry(self):
        old = incident(location_text='ATLANTIC ST, DARTMOUTH', lat=44.63, lon=-63.57,
                       location_precision='approximate_geocode')
        source = incident(location_text=old.location_text, lat=44.67, lon=-63.56,
                          location_precision='source_geometry')
        with patch.dict(os.environ, {'HFXPULSE_GEOCODE': '0'}):
            enrich([old, source], Path('/unused'))
        self.assertIsNone(old.lat)
        self.assertEqual((source.lat, source.lon, source.location_precision), (44.67, -63.56, 'source_geometry'))

    def test_versioned_cache_is_used_only_for_matching_locality(self):
        dartmouth = incident(location_text='ATLANTIC ST, DARTMOUTH')
        halifax = incident(location_text='ATLANTIC ST, HALIFAX')
        key = cache_key(halifax.location_text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.json'
            path.write_text(json.dumps({key: {'lat': 44.63, 'lon': -63.57}}))
            with patch.dict(os.environ, {'HFXPULSE_GEOCODE': '1'}):
                enrich([dartmouth, halifax], path, max_new=0)
            self.assertIsNone(dartmouth.lat)
            self.assertEqual(halifax.lat, 44.63)
            self.assertEqual(halifax.metadata['geocode_key'], key)
            with patch.dict(os.environ, {'HFXPULSE_GEOCODE': '0'}):
                enrich([halifax], path)
            self.assertEqual(halifax.lat, 44.63)

    def test_different_calls_cannot_merge_through_unidentified_report(self):
        rows = [incident(id='a', location_text='HOLLIS ST, HALIFAX', metadata={'call_number': '16959'}),
                incident(id='mirror', location_text='HOLLIS ST, HALIFAX', metadata={'call_number': '16959'}),
                incident(id='generic', location_text='HOLLIS ST, HALIFAX'),
                incident(id='b', location_text='HOLLIS ST, HALIFAX', metadata={'call_number': '16957'})]
        normalize_observations(rows)
        events = cluster_events(rows)
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertFalse({'a', 'b'} <= set(event.related_ids))
        self.assertTrue(any({'a', 'mirror'} <= set(event.related_ids) for event in events))

    def test_open_data_raw_incident_ids_are_respected_but_other_raw_ids_are_not(self):
        rows = [incident(id='live', metadata={'call_number': '16959'}),
                incident(id='archive', source='HRFE Incident Initial Response · Open Data', raw_ids=['16959']),
                incident(id='other-call', source='HRFE Incident Initial Response · Open Data', raw_ids=['16957']),
                incident(id='news', source='News', raw_ids=['article-id'])]
        normalize_observations(rows)
        events = cluster_events(rows)
        self.assertEqual(len(events), 2)
        self.assertTrue(any({'live', 'archive', 'news'} <= set(event.related_ids) for event in events))
