"""Regression tests for shortlived-playlist retention.

Run from the server directory:

    python -m unittest discover -s tests -v

The tests use mocks only; they never touch Postgres or Spotify.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from api.services import retention_service, spotify_actions


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://api.spotify.com/v1/test"
    return requests.HTTPError(f"{status_code} Client Error", response=response)


class UnfollowPlaylistTests(unittest.TestCase):
    def test_404_means_already_gone(self):
        with patch.object(
            spotify_actions, "_request", side_effect=_http_error(404),
        ) as request:
            spotify_actions.unfollow_playlist("token", "playlist-id")

        request.assert_called_once_with(
            "DELETE", "token", "/playlists/playlist-id/followers",
        )

    def test_other_errors_propagate(self):
        with patch.object(
            spotify_actions, "_request", side_effect=_http_error(500),
        ):
            with self.assertRaises(requests.HTTPError):
                spotify_actions.unfollow_playlist("token", "playlist-id")


class SweepExpiredTests(unittest.TestCase):
    def test_deletes_due_playlists_and_defers_failures(self):
        failure = RuntimeError("Spotify unavailable")
        due_rows = [
            {"user_id": "user-1", "playlist_spotify_id": "gone"},
            {"user_id": "user-1", "playlist_spotify_id": "busy"},
        ]

        with patch.object(
            retention_service, "due_for_deletion", return_value=due_rows,
        ), patch(
            "api.services.auth_service.is_authenticated", return_value=True,
        ), patch(
            "api.services.auth_service.get_valid_token", return_value="token",
        ), patch(
            "api.services.spotify_actions.unfollow_playlist",
            side_effect=[None, failure],
        ) as unfollow, patch(
            "api.services.playlist_cache.delete_playlist_cache",
        ) as delete_cache, patch.object(
            retention_service, "clear_retention",
        ) as clear_retention, patch.object(
            retention_service, "mark_error",
        ) as mark_error:
            result = retention_service.sweep_expired()

        self.assertEqual(result, {"deleted": 1, "deferred": 1})
        unfollow.assert_any_call("token", "gone")
        unfollow.assert_any_call("token", "busy")
        clear_retention.assert_called_once_with("gone", "user-1")
        delete_cache.assert_called_once_with("gone", "user-1")
        mark_error.assert_called_once_with("busy", str(failure), "user-1")

    def test_defers_users_without_a_spotify_connection(self):
        due_rows = [{"user_id": "user-1", "playlist_spotify_id": "gone"}]

        with patch.object(
            retention_service, "due_for_deletion", return_value=due_rows,
        ), patch(
            "api.services.auth_service.is_authenticated", return_value=False,
        ), patch(
            "api.services.spotify_actions.unfollow_playlist",
        ) as unfollow, patch.object(
            retention_service, "clear_retention",
        ) as clear_retention:
            result = retention_service.sweep_expired()

        self.assertEqual(result, {"deleted": 0, "deferred": 1})
        unfollow.assert_not_called()
        clear_retention.assert_not_called()

    def test_each_playlist_uses_its_owners_token(self):
        due_rows = [
            {"user_id": "user-1", "playlist_spotify_id": "p1"},
            {"user_id": "user-2", "playlist_spotify_id": "p2"},
        ]

        with patch.object(
            retention_service, "due_for_deletion", return_value=due_rows,
        ), patch(
            "api.services.auth_service.is_authenticated", return_value=True,
        ), patch(
            "api.services.auth_service.get_valid_token",
            side_effect=lambda uid: f"token-{uid}",
        ), patch(
            "api.services.spotify_actions.unfollow_playlist",
        ) as unfollow, patch(
            "api.services.playlist_cache.delete_playlist_cache",
        ), patch.object(
            retention_service, "clear_retention",
        ), patch.object(
            retention_service, "mark_error",
        ):
            result = retention_service.sweep_expired()

        self.assertEqual(result, {"deleted": 2, "deferred": 0})
        unfollow.assert_any_call("token-user-1", "p1")
        unfollow.assert_any_call("token-user-2", "p2")


class AsUtcTests(unittest.TestCase):
    def test_naive_datetime_is_treated_as_utc(self):
        value = datetime(2026, 10, 21, 0, 36, 0)
        self.assertEqual(
            retention_service.as_utc(value),
            datetime(2026, 10, 21, 0, 36, 0, tzinfo=timezone.utc),
        )

    def test_string_z_is_parsed_as_utc(self):
        self.assertEqual(
            retention_service.as_utc("2026-10-21T00:36:00Z"),
            datetime(2026, 10, 21, 0, 36, 0, tzinfo=timezone.utc),
        )

    def test_offset_is_normalised_to_utc(self):
        self.assertEqual(
            retention_service.as_utc("2026-10-21T03:36:00+03:00"),
            datetime(2026, 10, 21, 0, 36, 0, tzinfo=timezone.utc),
        )

class ExpiresAtTests(unittest.TestCase):
    def setUp(self):
        from api.routers.spotify_actions import CreatePlaylistBody

        self.CreatePlaylistBody = CreatePlaylistBody

    def _body(self, **kwargs):
        return self.CreatePlaylistBody(
            name="test", album_ids=[], **kwargs,
        )

    def test_relative_hours_are_added_to_now(self):
        from api.routers.spotify_actions import _expires_at

        before = datetime.now(timezone.utc)
        expires = _expires_at(self._body(retention_hours=1))
        after = datetime.now(timezone.utc)

        self.assertGreaterEqual(expires, before + timedelta(hours=1))
        self.assertLessEqual(expires, after + timedelta(hours=1))

    def test_custom_local_offset_is_converted_to_utc(self):
        from api.routers.spotify_actions import _expires_at

        expires = _expires_at(
            self._body(retention_until="2099-10-21T00:36:00+03:00"),
        )

        self.assertEqual(
            expires, datetime(2099, 10, 20, 21, 36, tzinfo=timezone.utc),
        )

    def test_past_custom_expiry_is_rejected(self):
        from fastapi import HTTPException

        from api.routers.spotify_actions import _expires_at

        with self.assertRaises(HTTPException) as raised:
            _expires_at(self._body(retention_until="2020-01-01T00:00:00Z"))

        self.assertEqual(raised.exception.status_code, 422)

    def test_negative_relative_retention_is_rejected(self):
        from fastapi import HTTPException

        from api.routers.spotify_actions import _expires_at

        with self.assertRaises(HTTPException) as raised:
            _expires_at(self._body(retention_hours=-1))

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
