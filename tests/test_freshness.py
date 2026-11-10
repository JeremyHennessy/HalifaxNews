import copy
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.check_freshness import fetch_publication, main, timestamp, validate_publication
from hfxpulse.adapters import port_cruise


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 2, tzinfo=timezone.utc)
        self.payload = {"generated_at": "2026-11-10T01:58:00Z", "events": [],
                        "event_count": 0, "incidents": [], "observation_count": 0,
                        "source_health": [{"status": "ok"}, {"status": "error"}]}

    def check(self, payload=None, **kwargs):
        return validate_publication(self.payload if payload is None else payload,
                                    now=self.now, **kwargs)

    def test_fresh_publication_reports_age_separately_from_health(self):
        summary = self.check()
        self.assertEqual(summary["age_minutes"], 2)
        self.assertEqual(summary["sources_ok_at_collection"], 1)

    def test_successful_older_job_does_not_make_publication_fresh(self):
        self.payload["generated_at"] = "2026-11-10T00:39:15Z"
        with self.assertRaisesRegex(ValueError, "stale"):
            self.check()

    def test_pages_must_catch_up_to_expected_collection(self):
        with self.assertRaisesRegex(ValueError, "older"):
            self.check(expected_at=self.now - timedelta(minutes=1))
        self.check(expected_at=self.now - timedelta(minutes=3))

    def test_future_publication_fails(self):
        self.payload["generated_at"] = "2026-11-10T02:06:00Z"
        with self.assertRaisesRegex(ValueError, "future"):
            self.check()

    def test_missing_invalid_or_naive_timestamps_fail(self):
        for value in (None, 42, "garbage", "2026-11-10T01:59:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timestamp(value)

    def test_offset_timestamp_is_normalized(self):
        self.assertEqual(timestamp("2026-11-09T22:00:00-04:00"), self.now)

    def test_missing_lists_counts_and_health_fail(self):
        for key in ("events", "event_count", "incidents", "observation_count", "source_health"):
            payload = copy.deepcopy(self.payload)
            del payload[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(payload)
        with self.assertRaises(ValueError):
            self.check([])

    def test_default_check_is_single_attempt_and_fails_on_network_error(self):
        with patch("scripts.check_freshness.fetch_publication", side_effect=OSError("unavailable")) as fetch:
            self.assertEqual(main([]), 1)
            fetch.assert_called_once()

    def test_port_remains_visible_without_network_retry(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Must not request blocked port")) as request:
            result = port_cruise.fetch()
        request.assert_not_called()
        self.assertEqual(result.incidents, [])
        self.assertEqual(result.health.status, "error")
        self.assertIsNone(result.health.fetched_at)
        self.assertIn("no network request", result.health.error)

    def test_propagation_retry_succeeds_only_when_new_payload_arrives(self):
        current = {**self.payload, "generated_at": datetime.now(timezone.utc).isoformat()}
        stale = {**self.payload, "generated_at": "2000-01-01T00:00:00Z"}
        with patch("scripts.check_freshness.fetch_publication", side_effect=[stale, current]) as fetch, \
             patch("scripts.check_freshness.time.monotonic", side_effect=[0, 1, 16]), \
             patch("scripts.check_freshness.time.sleep") as sleep:
            self.assertEqual(main(["--wait-seconds", "30"]), 0)
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(15)

    def test_retry_stops_when_deadline_passes(self):
        with patch("scripts.check_freshness.fetch_publication", side_effect=OSError("unavailable")) as fetch, \
             patch("scripts.check_freshness.time.monotonic", side_effect=[0, 31]), \
             patch("scripts.check_freshness.time.sleep") as sleep:
            self.assertEqual(main(["--wait-seconds", "30"]), 1)
        fetch.assert_called_once()
        sleep.assert_not_called()

    def test_access_denial_is_not_retried(self):
        for status in (401, 403):
            with self.subTest(status=status), \
                 patch("scripts.check_freshness.fetch_publication", side_effect=HTTPError("https://example.org", status, "Denied", {}, None)) as fetch, \
                 patch("scripts.check_freshness.time.sleep") as sleep:
                self.assertEqual(main(["--wait-seconds", "30"]), 1)
            fetch.assert_called_once()
            sleep.assert_not_called()

    def test_no_extra_request_after_sleep_reaches_deadline(self):
        with patch("scripts.check_freshness.fetch_publication", side_effect=OSError("unavailable")) as fetch, \
             patch("scripts.check_freshness.time.monotonic", side_effect=[0, 1, 5]), \
             patch("scripts.check_freshness.time.sleep") as sleep:
            self.assertEqual(main(["--wait-seconds", "5"]), 1)
        fetch.assert_called_once()
        sleep.assert_called_once_with(4)

    def test_expected_file_requires_publication_to_catch_up(self):
        now = datetime.now(timezone.utc)
        current = {**self.payload, "generated_at": now.isoformat()}
        older = {**current, "generated_at": (now - timedelta(minutes=1)).isoformat()}
        with patch("scripts.check_freshness.Path.read_text", return_value=json.dumps(current)) as read, \
             patch("scripts.check_freshness.fetch_publication", return_value=older):
            self.assertEqual(main(["--expected-file", "collected.json"]), 1)
        read.assert_called_once()

    def test_request_preserves_query_and_avoids_cached_response(self):
        with patch("scripts.check_freshness.urlopen") as open_url, \
             patch("scripts.check_freshness.time.time_ns", return_value=123):
            open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(self.payload).encode())
            self.assertEqual(fetch_publication("https://example.org/data.json?existing=1"), self.payload)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.org/data.json?existing=1&freshness_check=123")
        self.assertEqual(request.get_header("Cache-control"), "no-cache")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 10)
        with self.assertRaises(ValueError):
            fetch_publication("http://example.org/data.json")
