from pathlib import Path
import unittest

from hfxpulse.adapters.water import parse_html


class WaterNoticeTests(unittest.TestCase):
    def test_captured_current_cards_preserve_time_and_deduplicate(self):
        rows = parse_html((Path(__file__).parent / 'fixtures' / 'water.html').read_text())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].title, 'Lynnville Drive – Water System Repair')
        self.assertEqual(rows[0].reported_at, '2026-11-09T19:54:00Z')
        self.assertEqual(rows[0].metadata['source_timestamp_kind'], 'published')
        self.assertNotIn('Read more', rows[0].summary)
        self.assertEqual(rows[1].reported_at, '2024-10-07T17:35:30Z')
        self.assertEqual(rows[1].metadata['source_timestamp_kind'], 'updated')

    def test_date_does_not_leak_into_neighboring_card(self):
        html = '''<main>
        <article><h2><a href="/notice/water-repair">Water system repair</a></h2>
          <div class="date-published"><span class="field-value">2:30 PM | July 9, 2026</span></div></article>
        <article><h2><a href="/notice/undated-repair">Undated water repair</a></h2></article>
        <article><h2><a href="https://other.example/notice/foreign">External water notice</a></h2>
          <time datetime="2026-07-09T14:30:00-03:00"></time></article>
        </main>'''
        rows = parse_html(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].reported_at, '2026-07-09T17:30:00Z')

    def test_malformed_timestamps_are_not_invented(self):
        html = '''<div class="view__row"><div class="views-field-title">
        <a href="/notice/repair">Water system repair</a></div>
        <time datetime="not-a-date">November 9, 2026</time></div>'''
        self.assertEqual(parse_html(html), [])

    def test_news_and_navigation_are_not_service_notices(self):
        html = '''<article><h2><a href="/news/water-budget">Halifax Water budget</a></h2>
        <time datetime="2026-11-09T10:00:00-04:00"></time></article>
        <a href="/notices-and-news">Water service notices</a> November 9, 2026'''
        self.assertEqual(parse_html(html), [])


if __name__ == '__main__':
    unittest.main()
