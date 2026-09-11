from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hfxpulse.adapters.reddit import parse_atom


class RedditAtomParserTests(unittest.TestCase):
    def test_filters_incident_posts_and_never_persists_author_identity(self):
        data = (ROOT / "tests" / "fixtures" / "reddit_atom.xml").read_bytes()
        rows = parse_atom(data)
        self.assertEqual(2, len(rows))

        self_post = rows[0]
        self.assertEqual("COMMUNITY", self_post.category)
        self.assertEqual("unverified", self_post.confidence)
        self.assertEqual("community", self_post.source_kind)
        self.assertEqual("Sirens downtown?", self_post.title)
        self.assertEqual("2026-09-11T13:19:54Z", self_post.reported_at)
        self.assertEqual(["incident123"], self_post.raw_ids)
        self.assertIn("Lots of sirens and police downtown", self_post.summary)
        self.assertNotIn("FixtureUser", self_post.summary)
        self.assertEqual({}, self_post.metadata)

        link_post = rows[1]
        self.assertEqual("Police operation on Barrington Street", link_post.title)
        self.assertEqual("2026-09-11T15:00:00Z", link_post.reported_at)
        self.assertEqual("Community report — not independently verified.", link_post.summary)
        self.assertNotIn("LinkPoster", link_post.summary)
        self.assertEqual({}, link_post.metadata)

    def test_non_incident_post_is_filtered(self):
        data = (ROOT / "tests" / "fixtures" / "reddit_atom.xml").read_bytes()
        titles = [row.title for row in parse_atom(data)]
        self.assertNotIn("Where to find local pickled items", titles)


if __name__ == "__main__":
    unittest.main()
