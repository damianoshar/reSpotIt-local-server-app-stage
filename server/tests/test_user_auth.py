"""Regression tests for multi-user JWT auth (Phase 1)."""

import os

import pathlib
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import engine, SessionLocal
from api.main import app
from api.models import Base, User
from api.services import user_auth_service


class UserAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        User.__table__.create(bind=engine, checkfirst=True)
        cls.Session = sessionmaker(bind=engine)

    @classmethod
    def tearDownClass(cls):
        try:
            pathlib.Path("test_auth.db").unlink(missing_ok=True)
        except Exception:
            pass

    def setUp(self):
        # clean users
        with self.Session() as db:
            db.query(User).delete()
            db.commit()

    def _client(self):
        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        from api.database import get_db
        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def tearDown(self):
        from api.database import get_db
        app.dependency_overrides.pop(get_db, None)

    def test_register_login_refresh_me(self):
        client = self._client()
        r = client.post("/api/v1/auth/register", json={"email": "a@b.com", "password": "secret123"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["email"], "a@b.com")

        # duplicate register
        r2 = client.post("/api/v1/auth/register", json={"email": "a@b.com", "password": "secret123"})
        self.assertEqual(r2.status_code, 409)

        # login
        r3 = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "secret123"})
        self.assertEqual(r3.status_code, 200)
        access = r3.json()["access_token"]

        # me
        r4 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(r4.json()["email"], "a@b.com")

        # status
        r5 = client.get("/api/v1/auth/status", headers={"Authorization": f"Bearer {access}"})
        self.assertEqual(r5.status_code, 200)
        self.assertTrue(r5.json()["authenticated"])

        # refresh
        refresh = r3.json()["refresh_token"]
        r6 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        self.assertEqual(r6.status_code, 200)
        self.assertIn("access_token", r6.json())

        # bad login
        r7 = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "wrong"})
        self.assertEqual(r7.status_code, 401)

    def test_service_hash_verify(self):
        h = user_auth_service.hash_password("secret")
        self.assertTrue(user_auth_service.verify_password("secret", h))
        self.assertFalse(user_auth_service.verify_password("wrong", h))

    def test_jwt_round_trip(self):
        tok = user_auth_service.create_access_token("uid", "e@x.com")
        payload = user_auth_service.decode_token(tok, "access")
        self.assertEqual(payload["sub"], "uid")
        self.assertEqual(payload["email"], "e@x.com")