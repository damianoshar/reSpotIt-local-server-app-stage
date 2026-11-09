"""resolve_artists correlation: followed matching + fast, concurrent resolution.

Regression cover for the scan "0 followed" bug: /me/following is paginated
(~64 calls for a large library) and the per-artist catalog search used to run
serially, so a scan took >60 s and the Kotlin client's 30 s cap dropped every
match. These tests pin the fast paths (cache-only followed list, concurrent
search, batched /me/following/contains).
"""
import threading
import time
import unittest
from unittest.mock import patch

from api.services import spotify_actions


def _followed(artist_id, name):
    return {"id": artist_id, "name": name, "image_url": "", "genres": []}


def _candidate(artist_id, name):
    return {"id": artist_id, "name": name, "image_url": "", "genres": []}


class ResolveArtistsTests(unittest.TestCase):
    def setUp(self):
        spotify_actions.invalidate_followed_artists()

    def test_followed_name_matches_without_a_catalog_search(self):
        followed = [_followed("a1", "Radiohead")]
        with patch.object(spotify_actions, "_cached_followed_artists", return_value=followed), \
             patch.object(spotify_actions, "_search_artist_candidates",
                          side_effect=AssertionError("search must not run for followed")):
            out = spotify_actions.resolve_artists("token", ["radiohead", "RADIOHEAD"])

        self.assertEqual(len(out["resolved"]), 2)
        self.assertTrue(all(r["followed"] for r in out["resolved"]))
        self.assertTrue(all(r["spotify_id"] == "a1" for r in out["resolved"]))
        self.assertTrue(all(r["matched_name"] == "Radiohead" for r in out["resolved"]))
        self.assertEqual(out["unresolved"], [])

    def test_cold_cache_uses_contains_without_paginating(self):
        def search(token, name, limit=5):
            return [_candidate("s1", "Napalm Death")] if name == "Napalm Death" else []

        with patch.object(spotify_actions, "_cached_followed_artists", return_value=None), \
             patch.object(spotify_actions, "_warm_followed_artists") as warm, \
             patch.object(spotify_actions, "get_followed_artists",
                          side_effect=AssertionError("must not paginate in resolve")), \
             patch.object(spotify_actions, "_search_artist_candidates", side_effect=search), \
             patch.object(spotify_actions, "_followed_contains", return_value={"s1"}) as contains:
            out = spotify_actions.resolve_artists("token", ["Napalm Death", "Nobody"])

        warm.assert_called_once()  # cache warmed in the background instead of blocking
        contains.assert_called_once()
        self.assertEqual([r["name"] for r in out["resolved"]], ["Napalm Death"])
        self.assertTrue(out["resolved"][0]["followed"])
        self.assertEqual(out["unresolved"], ["Nobody"])

    def test_unfollowed_names_are_resolved_via_search(self):
        def search(token, name, limit=5):
            return [_candidate("x9", "Kovacs")] if name == "Kovacs" else []

        with patch.object(spotify_actions, "_cached_followed_artists", return_value=[]), \
             patch.object(spotify_actions, "_followed_contains", return_value=set()), \
             patch.object(spotify_actions, "_search_artist_candidates", side_effect=search):
            out = spotify_actions.resolve_artists("token", ["Kovacs", "  ", "Nobody"])

        # Blank names are dropped; unknown names land in unresolved.
        self.assertEqual([r["name"] for r in out["resolved"]], ["Kovacs"])
        self.assertFalse(out["resolved"][0]["followed"])
        self.assertEqual(out["unresolved"], ["Nobody"])

    def test_warm_name_match_survives_a_search_miss(self):
        # The followed list is the safety net when the catalog search misfires.
        followed = [_followed("s1", "Sólstafir")]
        with patch.object(spotify_actions, "_cached_followed_artists", return_value=followed), \
             patch.object(spotify_actions, "_followed_contains", return_value=set()), \
             patch.object(spotify_actions, "_search_artist_candidates", return_value=[]):
            out = spotify_actions.resolve_artists("token", ["Sólstafir"])

        self.assertEqual(len(out["resolved"]), 1)
        self.assertTrue(out["resolved"][0]["followed"])
        self.assertEqual(out["resolved"][0]["spotify_id"], "s1")

    def test_followed_list_is_cached_between_calls(self):
        calls = {"n": 0}

        def fetch(token):
            calls["n"] += 1
            return [_followed(f"a{i}", f"Artist {i}") for i in range(3)]

        with patch.object(spotify_actions, "_fetch_followed_artists", side_effect=fetch):
            first = spotify_actions.get_followed_artists("tok")
            second = spotify_actions.get_followed_artists("tok")

        self.assertEqual(calls["n"], 1, "second call must hit the cache")
        self.assertEqual(first, second)

    def test_searches_run_concurrently(self):
        active = {"now": 0, "max": 0}
        lock = threading.Lock()

        def fake_search(token, name, limit=5):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.2)
            with lock:
                active["now"] -= 1
            return [_candidate(f"id-{name}", name)]

        names = [f"Artist {i}" for i in range(8)]
        with patch.object(spotify_actions, "_cached_followed_artists", return_value=[]), \
             patch.object(spotify_actions, "_followed_contains", return_value=set()), \
             patch.object(spotify_actions, "_search_artist_candidates", side_effect=fake_search):
            start = time.monotonic()
            out = spotify_actions.resolve_artists("token", names)
            elapsed = time.monotonic() - start

        self.assertEqual(len(out["resolved"]), 8)
        self.assertGreater(active["max"], 1, "searches should overlap")
        # 8 x 0.2 s serially is 1.6 s; concurrency must beat that comfortably.
        self.assertLess(elapsed, 1.2)


if __name__ == "__main__":
    unittest.main()
