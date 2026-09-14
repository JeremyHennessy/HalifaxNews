from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hfxpulse.adapters.reddit import _incident_hit, parse_atom


class RedditAtomParserTests(unittest.TestCase):
    def test_filters_incident_posts_and_never_persists_author_identity(self):
        data = (ROOT / "tests" / "fixtures" / "reddit_atom.xml").read_bytes()
        rows = parse_atom(data)
        by_title = {row.title: row for row in rows}

        self.assertIn("Sirens downtown?", by_title)
        self.assertIn("Police operation on Barrington Street", by_title)
        self_post = by_title["Sirens downtown?"]
        self.assertEqual("community", self_post.source_kind)
        self.assertEqual("unverified", self_post.confidence)
        self.assertEqual("2026-09-11T13:19:54Z", self_post.reported_at)
        self.assertIn("Lots of sirens and police downtown", self_post.summary)
        self.assertNotIn("FixtureUser", self_post.summary)
        self.assertNotIn("FixtureUser", str(self_post.metadata))

        link_post = by_title["Police operation on Barrington Street"]
        self.assertEqual("Community report — not independently verified.", link_post.summary)
        self.assertNotIn("LinkPoster", str(link_post.metadata))

    def test_location_only_noise_is_not_promoted_by_author_metadata(self):
        data = (ROOT / "tests" / "fixtures" / "reddit_atom.xml").read_bytes()
        titles = [row.title for row in parse_atom(data)]
        self.assertNotIn("Where to find local pickled items", titles)
        self.assertNotIn("adult ballet/barre downtown?", titles)

    def test_accident_substring_does_not_match_accidently(self):
        self.assertFalse(_incident_hit("Accidently pocketed an AirPod case on my flight into Halifax"))
        self.assertTrue(_incident_hit("Accident on Barrington Street in Halifax"))


if __name__ == "__main__":
    unittest.main()
