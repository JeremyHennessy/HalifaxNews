from __future__ import annotations

import unittest
from unittest.mock import patch

from hfxpulse.adapters import bluesky


class _Response:
    def __init__(self, payload=None, error: Exception | None = None):
        self._payload = payload or {}
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        query = (params or {}).get("q")
        if query == "Halifax sirens" and url.startswith("https://a/"):
            return _Response(error=RuntimeError("primary blocked"))
        if query == "Halifax sirens" and url.startswith("https://b/"):
            return _Response({"posts": [_post("at://did:plc:test/app.bsky.feed.post/1", "Halifax fire crews downtown", "2026-09-11T15:00:00Z")]})
        if query == "Halifax fire" and url.startswith("https://a/"):
            return _Response({"posts": [_post("at://did:plc:test/app.bsky.feed.post/2", "Smoke and fire response in Halifax", "2026-09-11T15:02:00Z")]})
        return _Response(error=RuntimeError("unexpected endpoint"))


def _post(uri: str, text: str, created_at: str) -> dict:
    return {
        "uri": uri,
        "author": {"handle": "observer.test"},
        "record": {"text": text, "createdAt": created_at},
        "indexedAt": created_at,
    }


class BlueskySearchFallbackTests(unittest.TestCase):
    def test_each_query_can_fall_back_to_other_appview(self):
        fake = _Session()
        with patch.object(bluesky, "SEARCH_APIS", ("https://a", "https://b")), patch.object(
            bluesky, "SEARCH_QUERIES", ("Halifax sirens", "Halifax fire")
        ), patch.object(bluesky, "session", return_value=fake):
            result = bluesky.fetch_search()

        self.assertEqual("ok", result.health.status)
        self.assertEqual(2, len(result.incidents))
        calls = [(url, params["q"]) for url, params in fake.calls]
        self.assertIn(("https://a/app.bsky.feed.searchPosts", "Halifax sirens"), calls)
        self.assertIn(("https://b/app.bsky.feed.searchPosts", "Halifax sirens"), calls)
        self.assertIn(("https://a/app.bsky.feed.searchPosts", "Halifax fire"), calls)


if __name__ == "__main__":
    unittest.main()
