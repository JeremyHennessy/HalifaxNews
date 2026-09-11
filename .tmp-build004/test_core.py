from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hfxpulse.adapters.hrfe import parse_hrfe_text
from hfxpulse.adapters.ns511 import parse_text_report
from hfxpulse.adapters.weather import parse_atom
from hfxpulse.adapters.newsfeeds import parse_feed
from hfxpulse.adapters.reddit import parse_payload as parse_reddit
from hfxpulse.correlation import correlate
from hfxpulse.models import Incident
from hfxpulse.util import apparatus_count, infer_category, infer_text_siren_score, normalized_place


class HRFEParserTests(unittest.TestCase):
    def test_parses_public_labels(self):
        text = (ROOT / "tests" / "fixtures" / "hrfe.txt").read_text(encoding="utf-8")
        rows = parse_hrfe_text(text)
        self.assertEqual(2, len(rows))
        alarm = rows[0]
        self.assertEqual("hrfe-hf26000011831", alarm.id)
        self.assertEqual("FIRE", alarm.category)
        self.assertEqual("BARRINGTON ST, HALIFAX", alarm.location_text)
        self.assertEqual("A03 E02 E03 STN02", alarm.metadata["response"])
        self.assertEqual(3, apparatus_count(alarm.metadata["response"]))
        self.assertGreater(alarm.siren_score, 0)

    def test_collision_maps_to_rescue(self):
        text = (ROOT / "tests" / "fixtures" / "hrfe.txt").read_text(encoding="utf-8")
        row = parse_hrfe_text(text)[1]
        self.assertEqual("RESCUE", row.category)
        self.assertIn("COLLISION", row.subtype)


class CorrelationTests(unittest.TestCase):
    def test_two_official_sources_upgrade_to_corroborated(self):
        a = Incident(id="a", source="fire", source_url="x", title="Alarm", summary="", category="FIRE", reported_at="2026-09-11T11:00:00Z", location_text="BARRINGTON ST, HALIFAX")
        b = Incident(id="b", source="police", source_url="y", title="Closure", summary="", category="POLICE", reported_at="2026-09-11T11:15:00Z", location_text="Barrington Street")
        correlate([a,b])
        self.assertEqual("corroborated", a.confidence)
        self.assertEqual("corroborated", b.confidence)
        self.assertIn("b", a.related_ids)

    def test_community_does_not_create_corroborated_official(self):
        a = Incident(id="a", source="fire", source_url="x", title="Alarm", summary="", category="FIRE", reported_at="2026-09-11T11:00:00Z", location_text="BARRINGTON ST, HALIFAX")
        b = Incident(id="b", source="reddit", source_url="y", title="sirens", summary="", category="COMMUNITY", reported_at="2026-09-11T11:10:00Z", location_text="Barrington", source_kind="community", confidence="unverified")
        correlate([a,b])
        self.assertEqual("official", a.confidence)
        self.assertEqual("unverified", b.confidence)


class OtherParserTests(unittest.TestCase):
    def test_511_text_report_filters_to_hrm(self):
        html = (ROOT / "tests" / "fixtures" / "511.html").read_text(encoding="utf-8")
        rows = parse_text_report(html)
        self.assertEqual(1, len(rows))
        self.assertEqual("TRAFFIC", rows[0].category)
        self.assertIn("Macdonald Bridge", rows[0].title)

    def test_environment_canada_atom(self):
        data = (ROOT / "tests" / "fixtures" / "weather.xml").read_bytes()
        rows = parse_atom(data)
        self.assertEqual(1, len(rows))
        self.assertEqual("WEATHER", rows[0].category)
        self.assertEqual("Rainfall warning in effect", rows[0].title)

    def test_news_rss_parser(self):
        data = b"""<?xml version='1.0'?><rss><channel><item><title>Fire closes Barrington Street in Halifax</title><link>https://example.test/story</link><pubDate>Fri, 11 Sep 2026 09:30:00 -0300</pubDate><description>Crews are responding downtown.</description></item></channel></rss>"""
        rows = parse_feed(data, "Test News", "https://example.test/feed")
        self.assertEqual(1, len(rows)); self.assertEqual("FIRE", rows[0].category); self.assertEqual("reported", rows[0].confidence)

    def test_reddit_keeps_nonofficial_signal(self):
        payload = {"data":{"children":[{"data":{"id":"abc","title":"Lots of sirens on Lower Water in Halifax","selftext":"Fire boats too","created_utc":1789133400,"permalink":"/r/halifax/comments/abc/x","score":4,"num_comments":8}}]}}
        rows = parse_reddit(payload, "halifax")
        self.assertEqual(1, len(rows)); self.assertEqual("community", rows[0].source_kind); self.assertGreater(rows[0].siren_score, 0)


class UtilityTests(unittest.TestCase):
    def test_normalized_place(self): self.assertEqual("BARRINGTON", normalized_place("Barrington St, Halifax"))
    def test_text_classification_and_siren_score(self):
        self.assertEqual("RESCUE", infer_category("Coast Guard water rescue on Halifax waterfront"))
        score = infer_text_siren_score("many sirens, police and ambulance", "2026-09-11T13:00:00Z", "community")
        self.assertGreater(score, 0)


class PriorityScoringTests(unittest.TestCase):
    def test_structure_fire_scores_high_without_relying_on_source_authority(self):
        from hfxpulse.scoring import score_incidents
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        row = Incident(id='x', source='community', source_url='https://example.test', title='Structure fire downtown', summary='Large response on Barrington Street', category='FIRE', subtype='STRUCTURE FIRE', reported_at=now, source_kind='community', confidence='unverified', location_text='BARRINGTON ST, HALIFAX', metadata={'response':'E02 E03 E04 E05 Q03 A03 STN02'})
        score_incidents([row]); self.assertGreaterEqual(row.seriousness_score, 68); self.assertGreaterEqual(row.priority_score, 60); self.assertIn(row.priority_band, {'high', 'critical'})

    def test_small_routine_power_outages_are_suppressed(self):
        from hfxpulse.adapters.ns_power import parse_payload
        payload = [{'id':'small','area':'Halifax','customers':12,'cause':'Equipment failure'},{'id':'large','area':'Halifax','customers':850,'cause':'Equipment failure'},{'id':'safety','area':'Halifax','customers':25,'cause':'Vehicle collision'}]
        rows = parse_payload(payload, min_customers=100); ids = {r.raw_ids[0] for r in rows}
        self.assertNotIn('small', ids); self.assertIn('large', ids); self.assertIn('safety', ids)

class ExpandedSourceParserTests(unittest.TestCase):
    def test_hrp_accepts_posted_timestamp_with_hyphen(self):
        from hfxpulse.adapters.hrp import parse_hrp_html
        html = '''<div class="card"><div>Posted: September 11, 2026 - 10:45 am</div><div><a href="/home/news/police-investigate-downtown-incident">Police investigate downtown incident</a></div></div>'''
        rows = parse_hrp_html(html); self.assertEqual(1, len(rows)); self.assertEqual("POLICE", rows[0].category)
    def test_hrfe_bluesky_mirror_preserves_dispatch_fields(self):
        from hfxpulse.adapters.hrfe_mirror import parse_mirror_post
        text = """HRFE Incident Feed\nALARMS\nLocation: BARRINGTON ST, HALIFAX\nCall Number: HF26000011831\nResponse: A03 E02 E03 STN02\nSeptember 11, 2026 at 08:06AM"""
        rows = parse_mirror_post(text, "hrfeincidents.bsky.social"); self.assertEqual(1, len(rows)); self.assertEqual("HF26000011831", rows[0].metadata["call_number"]); self.assertEqual("secondary", rows[0].source_kind)
    def test_reddit_atom_fallback(self):
        from hfxpulse.adapters.reddit import parse_rss
        data = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>t3_abc</id><updated>2026-09-11T12:00:00Z</updated><title>Lots of sirens on Lower Water in Halifax</title><link href="https://www.reddit.com/r/halifax/comments/abc/test/"/><content type="html">Fire boats and police downtown</content></entry></feed>'''
        rows = parse_rss(data, "halifax"); self.assertEqual(1, len(rows)); self.assertEqual("community", rows[0].source_kind)
    def test_emergency_arcgis_parser(self):
        from hfxpulse.adapters.emergency_ns import parse_arcgis
        payload = {"features":[{"attributes":{"OBJECTID":1,"GlobalID":"g1","status":"Yes","incidentnm":"Flooding","shortmessage":"Avoid travel","longmessage":"Roads are flooded","CreationDate":1789130000000,"EditDate":1789133000000,"actionrequired":"Yes","actionmessage":"Stay away"}}]}
        rows = parse_arcgis(payload); self.assertEqual(1, len(rows)); self.assertEqual("EMERGENCY", rows[0].category)
    def test_active_street_closure_parser(self):
        from hfxpulse.adapters.street_closures import parse_payload
        now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
        payload = {"features":[{"attributes":{"OBJECTID":7,"GLOBALID":"g7","CLOSURE_TYPE":"Construction","CLOSURE_STAGE":"Full Closure","START_DATE":1789120000000,"END_DATE":1789200000000,"MODDATE":1789125000000,"STREET_NAME":"Barrington Street","FROM_STR":"Duke Street","TO_STR":"Prince Street","COMMENTS":"Detour in place"}}]}
        rows = parse_payload(payload, now=now); self.assertEqual(1, len(rows)); self.assertEqual("TRAFFIC", rows[0].category); self.assertTrue(rows[0].metadata["currently_active"])

class NormalizationTests(unittest.TestCase):
    def test_matching_observations_cluster_into_one_event(self):
        from hfxpulse.normalization import cluster_events, normalize_observations
        from hfxpulse.scoring import score_incidents
        a = Incident(id='fire-a', source='HRFE', source_url='https://example.test/a', title='Structure fire', summary='Crews responding', category='FIRE', subtype='STRUCTURE FIRE', reported_at='2026-09-11T13:00:00Z', location_text='1500 BARRINGTON ST, HALIFAX', source_kind='official', confidence='official', metadata={'call_number':'HF260001'})
        b = Incident(id='fire-b', source='Local News', source_url='https://example.test/b', title='Structure fire closes Barrington Street', summary='Emergency crews are on scene downtown', category='FIRE', reported_at='2026-09-11T13:10:00Z', location_text='Barrington Street, Halifax', source_kind='news', confidence='reported')
        normalize_observations([a,b]); score_incidents([a,b]); events = cluster_events([a,b])
        self.assertEqual(1, len(events)); self.assertEqual(2, events[0].source_count); self.assertEqual(2, events[0].evidence_count); self.assertEqual('corroborated', events[0].confidence)
    def test_different_incident_types_same_street_do_not_merge_without_similarity(self):
        from hfxpulse.normalization import cluster_events, normalize_observations
        from hfxpulse.scoring import score_incidents
        fire = Incident(id='fire', source='A', source_url='x', title='Alarm activation', summary='', category='FIRE', reported_at='2026-09-11T13:00:00Z', location_text='Barrington St, Halifax')
        crash = Incident(id='crash', source='B', source_url='y', title='Vehicle collision', summary='', category='RESCUE', reported_at='2026-09-11T13:15:00Z', location_text='Barrington St, Halifax')
        normalize_observations([fire,crash]); score_incidents([fire,crash]); events = cluster_events([fire,crash]); self.assertEqual(2, len(events))
    def test_normalization_strips_html_and_sets_controlled_fields(self):
        from hfxpulse.normalization import normalize_observations
        row = Incident(id='n', source='News', source_url='x', title='<b>Fire</b> on Barrington', summary='  smoke &amp; crews ', category='fire', reported_at='2026-09-11T13:00:00Z', location_text='Barrington St, Halifax', source_kind='news', confidence='reported')
        normalize_observations([row]); self.assertEqual('Fire on Barrington', row.title); self.assertEqual('smoke & crews', row.summary); self.assertEqual('FIRE', row.category); self.assertEqual('news', row.source_class); self.assertEqual('BARRINGTON', row.canonical_location); self.assertEqual('DOWNTOWN', row.neighbourhood)

class ApparatusDecoderTests(unittest.TestCase):
    def test_decodes_lower_water_response(self):
        from hfxpulse.apparatus import decode_response, response_summary
        response = 'DC02 E02 E15 FB1 JRCC PCE Q13 STN02'; units = decode_response(response); labels = {u['code']: u['label'] for u in units}
        self.assertEqual('District Chief 2', labels['DC02']); self.assertEqual('Engine 2', labels['E02']); self.assertEqual('Engine 15', labels['E15']); self.assertEqual('Fire Boat 1', labels['FB1']); self.assertEqual('Joint Rescue Coordination Centre Halifax', labels['JRCC']); self.assertEqual('Platoon Captain East', labels['PCE']); self.assertEqual('Quint 13', labels['Q13']); self.assertIn('Station 2', labels['STN02'])
        summary = response_summary('SALT WATER INCIDENT', response); self.assertIn('Marine search-and-rescue response', summary); self.assertIn('Engines 2 and 15', summary); self.assertIn('JRCC Halifax', summary)
    def test_hrfe_salt_water_is_rescue(self):
        from hfxpulse.adapters.hrfe import parse_hrfe_text
        text = 'SALT WATER INCIDENT Location: LOWER WATER ST, HALIFAX Call Number: HF26000013629 Response: DC02 E02 E15 FB1 JRCC PCE Q13 STN02 September 11, 2026 at 08:01 AM'
        rows = parse_hrfe_text(text); self.assertEqual(1, len(rows)); self.assertEqual('RESCUE', rows[0].category)

if __name__ == "__main__":
    unittest.main()
