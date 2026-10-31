"""Mobile PKCE token hand-off: POST /api/v1/auth/spotify/token.

The phone cannot use the server's loopback OAuth callback, so it authorises
with its custom scheme and posts the tokens here.
"""

import os
import pathlib

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_spotify_import.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest

from fastapi.testclient import TestClient

from api.database import SessionLocal, engine
from api.main import app
from api.models import Base, SpotifyToken, User


class SpotifyTokenImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine, checkfirst=True)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        try:
            pathlib.Path("test_spotify_import.db").unlink(missing_ok=True)
        except Exception:
            pass

    def setUp(self):
        with SessionLocal() as db:
            db.query(SpotifyToken).delete()
            db.query(User).delete()
            db.commit()
        r = self.client.post(
            "/api/v1/auth/register",
            json={"email": "mobile@example.com", "password": "secret123"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.jwt = r.json()["access_token"]

    def _post(self, body, jwt=None):
        headers = {"Authorization": f"Bearer {jwt or self.jwt}"} if jwt is not False else {}
        return self.client.post("/api/v1/auth/spotify/token", json=body, headers=headers)

    def test_import_stores_tokens_for_current_user(self):
        r = self._post({
            "access_token": "access-abc",
            "refresh_token": "refresh-xyz",
            "expires_in": 3600,
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["connected"])
        with SessionLocal() as db:
            row = db.query(SpotifyToken).one()
            self.assertEqual(row.access_token, "access-abc")
            self.assertEqual(row.refresh_token, "refresh-xyz")
            self.assertIsNotNone(row.expires_at)

    def test_import_requires_jwt(self):
        r = self._post({"access_token": "a", "refresh_token": "r"}, jwt=False)
        self.assertEqual(r.status_code, 401)

    def test_import_rejects_missing_refresh_token(self):
        r = self._post({"access_token": "a", "refresh_token": ""})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
