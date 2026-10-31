"""Playlist album/track removal regression tests (mocked, no Spotify)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api.routers import spotify_actions as routes
from api.services import spotify_actions


class RemoveTracksServiceTests(unittest.TestCase):
    def test_chunks_requests_at_one_hundred_uris(self):
        uris = [f"spotify:track:{i}" for i in range(205)]

        with patch.object(spotify_actions, "_request") as request:
            removed = spotify_actions.remove_tracks_from_playlist(
                "token", "playlist", uris,
            )

        self.assertEqual(removed, 205)
        self.assertEqual(request.call_count, 3)
        self.assertTrue(all(
            call.args[2] == "/playlists/playlist/items"
            for call in request.call_args_list
        ))
        self.assertEqual(
            [len(call.kwargs["json"]["items"]) for call in request.call_args_list],
            [100, 100, 5],
        )


class RemoveAlbumsRouteTests(unittest.TestCase):
    def setUp(self):
        self.body = routes.AlbumSelection(album_ids=["album-1"])
        self.user = SimpleNamespace(id="user-1")
        self.auth = patch.object(routes, "is_authenticated", return_value=True)
        self.token = patch.object(routes, "_token", return_value="token")
        self.auth.start()
        self.token.start()
        self.addCleanup(self.auth.stop)
        self.addCleanup(self.token.stop)

    def test_cache_is_only_mutated_after_spotify_confirms(self):
        with patch.object(
            routes, "album_track_uris", return_value=["spotify:track:t1"],
        ), patch.object(
            routes, "remove_tracks_from_playlist",
            side_effect=RuntimeError("Spotify failed"),
        ), patch.object(
            routes, "remove_album_tracks_from_cache",
        ) as remove_cache:
            with self.assertRaises(HTTPException) as raised:
                routes.remove_albums_from_playlist("playlist", self.body, self.user)

        self.assertEqual(raised.exception.status_code, 502)
        remove_cache.assert_not_called()

    def test_success_removes_tracks_then_cache_rows(self):
        with patch.object(
            routes, "album_track_uris", return_value=["spotify:track:t1"],
        ), patch.object(
            routes, "remove_tracks_from_playlist", return_value=1,
        ) as remove_tracks, patch.object(
            routes, "remove_album_tracks_from_cache", return_value=1,
        ) as remove_cache:
            result = routes.remove_albums_from_playlist("playlist", self.body, self.user)

        self.assertEqual(
            result,
            {
                "playlist_id": "playlist",
                "albums_removed": 1,
                "tracks_removed": 1,
            },
        )
        remove_tracks.assert_called_once_with(
            "token", "playlist", ["spotify:track:t1"],
        )
        remove_cache.assert_called_once_with("playlist", ["album-1"], "user-1")

    def test_uncached_albums_fall_back_to_live_playlist_tracks(self):
        with patch.object(
            routes, "album_track_uris", return_value=[],
        ), patch.object(
            routes, "get_playlist_tracks",
            return_value=[
                {"spotify_id": "t1", "album_spotify_id": "album-1"},
                {"spotify_id": "t2", "album_spotify_id": "album-2"},
            ],
        ), patch.object(
            routes, "remove_tracks_from_playlist", return_value=1,
        ) as remove_tracks, patch.object(
            routes, "remove_album_tracks_from_cache", return_value=1,
        ):
            result = routes.remove_albums_from_playlist("playlist", self.body, self.user)

        self.assertEqual(result["tracks_removed"], 1)
        remove_tracks.assert_called_once_with(
            "token", "playlist", ["spotify:track:t1"],
        )

    def test_no_matching_tracks_is_a_successful_noop(self):
        with patch.object(
            routes, "album_track_uris", return_value=[],
        ), patch.object(
            routes, "get_playlist_tracks", return_value=[],
        ), patch.object(
            routes, "remove_tracks_from_playlist",
        ) as remove_tracks, patch.object(
            routes, "remove_album_tracks_from_cache",
        ) as remove_cache:
            result = routes.remove_albums_from_playlist("playlist", self.body, self.user)

        self.assertEqual(result["tracks_removed"], 0)
        remove_tracks.assert_not_called()
        remove_cache.assert_not_called()

    def test_requires_a_connected_account(self):
        with patch.object(routes, "is_authenticated", return_value=False):
            with self.assertRaises(HTTPException) as raised:
                routes.remove_albums_from_playlist("playlist", self.body, self.user)

        self.assertEqual(raised.exception.status_code, 401)


class AddTracksServiceTests(unittest.TestCase):
    def test_uses_items_endpoint_and_chunks_at_one_hundred(self):
        uris = [f"spotify:track:{i}" for i in range(205)]

        with patch.object(spotify_actions, "_post") as post:
            added = spotify_actions.add_tracks_to_playlist(
                "token", "playlist", uris,
            )

        self.assertEqual(added, 205)
        self.assertEqual(post.call_count, 3)
        self.assertTrue(all(
            call.args[1] == "/playlists/playlist/items"
            for call in post.call_args_list
        ))
        self.assertEqual(
            [len(call.kwargs["json"]["uris"]) for call in post.call_args_list],
            [100, 100, 5],
        )


class CreatePlaylistRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user-1")
        self.token = patch.object(routes, "_token", return_value="token")
        self.create = patch.object(
            routes, "create_playlist",
            return_value={"id": "new", "name": "Queue snapshot", "url": "https://x"},
        )
        self.add = patch.object(routes, "add_tracks_to_playlist", return_value=2)
        self.token.start()
        self.create_mock = self.create.start()
        self.add_mock = self.add.start()
        self.addCleanup(self.token.stop)
        self.addCleanup(self.create.stop)
        self.addCleanup(self.add.stop)

    def test_accepts_uris_without_albums(self):
        body = routes.CreatePlaylistBody(
            name="Queue snapshot",
            uris=["spotify:track:t1", "spotify:episode:e1"],
        )

        result = routes.create_new_playlist(body, self.user)

        self.assertEqual(result["tracks_added"], 2)
        self.create_mock.assert_called_once_with("token", "Queue snapshot", "")
        self.add_mock.assert_called_once_with(
            "token", "new", ["spotify:track:t1", "spotify:episode:e1"],
        )

    def test_rejects_unsupported_uri(self):
        body = routes.CreatePlaylistBody(
            name="Queue snapshot",
            uris=["spotify:local:artist:album:track:1"],
        )

        with self.assertRaises(HTTPException) as raised:
            routes.create_new_playlist(body, self.user)

        self.assertEqual(raised.exception.status_code, 422)
        self.create_mock.assert_not_called()


class AddItemsRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user-1")

    def test_appends_tracks_and_episodes(self):
        body = routes.TrackUrisBody(
            uris=["spotify:track:t1", "spotify:episode:e1"],
        )

        with patch.object(
            routes, "_token", return_value="token",
        ), patch.object(
            routes, "add_tracks_to_playlist", return_value=2,
        ) as add:
            result = routes.add_items_to_existing("playlist", body, self.user)

        self.assertEqual(
            result, {"playlist_id": "playlist", "tracks_added": 2},
        )
        add.assert_called_once_with(
            "token", "playlist", ["spotify:track:t1", "spotify:episode:e1"],
        )

    def test_rejects_unsupported_uri(self):
        body = routes.TrackUrisBody(uris=["spotify:album:a1"])

        with self.assertRaises(HTTPException) as raised:
            routes.add_items_to_existing("playlist", body, self.user)

        self.assertEqual(raised.exception.status_code, 422)


class RemoveTracksRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user-1")

    def test_rejects_non_track_uris(self):
        body = routes.TrackUrisBody(uris=["spotify:album:album-1"])

        with self.assertRaises(HTTPException) as raised:
            routes.remove_tracks_from_playlist_route("playlist", body, self.user)

        self.assertEqual(raised.exception.status_code, 422)

    def test_cache_failure_does_not_fail_confirmed_spotify_removal(self):
        body = routes.TrackUrisBody(uris=["spotify:track:t1"])

        with patch.object(
            routes, "_token", return_value="token",
        ), patch.object(
            routes, "remove_tracks_from_playlist", return_value=1,
        ), patch(
            "api.services.playlist_cache.remove_track_uris",
            side_effect=RuntimeError("cache unavailable"),
        ):
            result = routes.remove_tracks_from_playlist_route("playlist", body, self.user)

        self.assertEqual(
            result, {"playlist_id": "playlist", "tracks_removed": 1},
        )


class DeletePlaylistRouteTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user-1")
        self.auth = patch.object(routes, "is_authenticated", return_value=True)
        self.token = patch.object(routes, "_token", return_value="token")
        self.unfollow = patch.object(routes, "unfollow_playlist")
        self.cache = patch.object(routes, "delete_playlist_cache")
        self.auth.start()
        self.token.start()
        self.unfollow.start()
        self.cache.start()
        self.addCleanup(self.auth.stop)
        self.addCleanup(self.token.stop)
        self.addCleanup(self.unfollow.stop)
        self.addCleanup(self.cache.stop)

    def test_success_unfollows_then_clears_cache(self):
        result = getattr(routes, "delete_playlist")("playlist", self.user)
        self.assertEqual(
            result,
            {"playlist_id": "playlist", "deleted": True},
        )
        routes.unfollow_playlist.assert_called_once_with("token", "playlist")
        routes.delete_playlist_cache.assert_called_once_with("playlist", "user-1")

    def test_requires_connected_account(self):
        with patch.object(routes, "is_authenticated", return_value=False):
            with self.assertRaises(HTTPException) as raised:
                getattr(routes, "delete_playlist")("playlist", self.user)
        self.assertEqual(raised.exception.status_code, 401)
        routes.unfollow_playlist.assert_not_called()
        routes.delete_playlist_cache.assert_not_called()

    def test_spotify_error_propagates(self):
        routes.unfollow_playlist.side_effect = RuntimeError("Spotify failed")
        with self.assertRaises(HTTPException) as raised:
            getattr(routes, "delete_playlist")("playlist", self.user)
        self.assertEqual(raised.exception.status_code, 502)
        routes.delete_playlist_cache.assert_not_called()

if __name__ == "__main__":
    unittest.main()
