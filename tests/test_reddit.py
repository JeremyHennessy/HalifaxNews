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
        self.assertEqual(3, len(rows))
        by_title = {row.title: row for row in rows}

        self_post = by_title["Sirens downtown?"]
        self.assertEqual("COMMUNITY", self_post.category)
        self.assertEqual("unverified", self_post.confidence)
        self.assertEqual("community", self_post.source_kind)
        self.assertEqual("2026-09-11T13:19:54Z", self_post.reported_at)
        self.assertEqual(["incident123"], self_post.raw_ids)
        self.assertIn("Lots of sirens and police downtown", self_post.summary)
        self.assertNotIn("FixtureUser", self_post.summary)
        self.assertEqual({}, self_post.metadata)

        question_post = by_title["What happened around Spring Garden?"]
        self.assertEqual("2026-09-11T12:20:00Z", question_post.reported_at)
        self.assertNotIn("QuestionPerson", question_post.summary)

        link_post = by_title["Police operation on Barrington Street"]
        self.assertEqual("2026-09-11T15:00:00Z", link_post.reported_at)
        self.assertEqual("Community report — not independently verified.", link_post.summary)
        self.assertNotIn("LinkPoster", link_post.summary)
        self.assertEqual({}, link_post.metadata)

    def test_irrelevant_and_location_only_posts_are_filtered(self):
        data = (ROOT / "tests" / "fixtures" / "reddit_atom.xml").read_bytes()
        titles = [row.title for row in parse_atom(data)]
        self.assertNotIn("Where to find local pickled items", titles)
        self.assertNotIn("adult ballet/barre downtown?", titles)
        self.assertIn("What happened around Spring Garden?", titles)


if __name__ == "__main__":
    unittest.main()
