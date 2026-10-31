"""Regression tests for Keycloak auth (Phase 3) and per-user Open WebUI (Phase 4).

The tests never touch a real Keycloak: JWKS and the token endpoint are
replaced with an in-process RSA key pair. They do exercise the real SQLAlchemy
models, the user-mapping path and the FastAPI dependency chain.
"""

import os
import pathlib
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import config
from api.database import engine
from api.main import app
from api.models import Base, KeycloakIdentity, KeycloakToken, User
from api.services import keycloak_service, openwebui_service, user_auth_service

ISSUER = "http://kc.test/authKeycloak/realms/open-webui"
CLIENT_ID = "open-webui"
KID = "test-key-1"

os.environ["KEYCLOAK_ENABLED"] = "true"
os.environ["KEYCLOAK_REALM"] = "open-webui"
os.environ["KEYCLOAK_CLIENT_ID"] = CLIENT_ID
os.environ["KEYCLOAK_ISSUER"] = ISSUER
os.environ["KEYCLOAK_INTERNAL_URL"] = "http://kc.test/authKeycloak"
os.environ["KEYCLOAK_PUBLIC_URL"] = "http://kc.test/authKeycloak"
config.reset_settings_cache()


def _keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = KID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return private_key, jwk


PRIVATE_KEY, PUBLIC_JWK = _keypair()


def _claims(**overrides):
    now = int(time.time())
    claims = {
        "sub": "kc-sub-123",
        "email": "kc@test.com",
        "preferred_username": "kc",
        "iss": ISSUER,
        "azp": CLIENT_ID,
        "aud": "account",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return claims


def _token(**overrides):
    return jwt.encode(_claims(**overrides), PRIVATE_KEY, algorithm="RS256",
                      headers={"kid": KID})


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.query(KeycloakToken).delete()
        db.query(KeycloakIdentity).delete()
        db.query(User).delete()
        db.commit()
    monkeypatch.setattr(
        keycloak_service, "_fetch_jwks", lambda force=False: {"keys": [PUBLIC_JWK]}
    )
    yield Session


@pytest.fixture()
def client():
    return TestClient(app)


class TestValidateToken:
    def test_accepts_valid_token(self):
        claims = keycloak_service.validate_token(_token())
        assert claims["sub"] == "kc-sub-123"
        assert claims["email"] == "kc@test.com"

    def test_rejects_wrong_issuer(self):
        token = _token(iss="http://evil.test/realms/open-webui")
        with pytest.raises(keycloak_service.KeycloakAuthError):
            keycloak_service.validate_token(token)

    def test_rejects_other_client(self):
        token = _token(azp="another-client")
        with pytest.raises(keycloak_service.KeycloakAuthError):
            keycloak_service.validate_token(token)

    def test_rejects_expired_token(self):
        token = _token(exp=int(time.time()) - 120)
        with pytest.raises(keycloak_service.KeycloakAuthError):
            keycloak_service.validate_token(token)


class TestUserMapping:
    def test_creates_then_reuses_identity(self, _isolated_db):
        Session = _isolated_db
        with Session() as db:
            first = keycloak_service.ensure_local_user(db, _claims())
            second = keycloak_service.ensure_local_user(db, _claims())
            assert str(first.id) == str(second.id)
            assert db.query(User).count() == 1
            assert db.query(KeycloakIdentity).count() == 1

    def test_links_existing_local_user_by_email(self, _isolated_db):
        Session = _isolated_db
        with Session() as db:
            local = User(
                email="kc@test.com",
                password_hash=user_auth_service.hash_password("local-pass"),
            )
            db.add(local)
            db.commit()
            user = keycloak_service.ensure_local_user(db, _claims())
            assert str(user.id) == str(local.id)

    def test_rejects_token_without_email(self, _isolated_db):
        Session = _isolated_db
        claims = _claims()
        claims.pop("email")
        claims.pop("preferred_username")
        with Session() as db:
            with pytest.raises(keycloak_service.KeycloakAuthError):
                keycloak_service.ensure_local_user(db, claims)


class TestTokenStorage:
    def test_refreshes_expired_token(self, _isolated_db, monkeypatch):
        Session = _isolated_db
        with Session() as db:
            user = keycloak_service.ensure_local_user(db, _claims())
            row = KeycloakToken(
                user_id=str(user.id),
                access_token="old",
                refresh_token="refresh-1",
                expires_at=keycloak_service.datetime.now(
                    keycloak_service.timezone.utc
                ) - keycloak_service.timedelta(minutes=5),
            )
            db.add(row)
            db.commit()

            monkeypatch.setattr(
                keycloak_service,
                "refresh",
                lambda rt: {"access_token": "new", "expires_in": 300,
                            "refresh_token": "refresh-2"},
            )
            token = keycloak_service.get_valid_access_token(db, str(user.id))
            assert token == "new"
            db.expire_all()
            stored = db.get(KeycloakToken, str(user.id))
            assert stored.access_token == "new"
            assert stored.refresh_token == "refresh-2"


class TestApiIntegration:
    def test_keycloak_bearer_authenticates_me(self, client, _isolated_db):
        resp = client.get(
            "/api/v1/auth/keycloak/me",
            headers={"Authorization": f"Bearer {_token()}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["email"] == "kc@test.com"
        assert body["keycloak"] is True
        assert body["keycloak_sub"] == "kc-sub-123"

    def test_keycloak_bearer_works_on_existing_routes(self, client, _isolated_db):
        resp = client.get(
            "/api/v1/auth/status",
            headers={"Authorization": f"Bearer {_token()}"},
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_local_jwt_still_works(self, client, _isolated_db):
        Session = _isolated_db
        with Session() as db:
            user = user_auth_service.register_user(db, "local@test.com", "secret123")
        tokens = user_auth_service.issue_tokens(user)
        resp = client.get(
            "/api/v1/auth/status",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "local@test.com"

    def test_invalid_bearer_is_401(self, client, _isolated_db):
        resp = client.get(
            "/api/v1/auth/keycloak/me",
            headers={"Authorization": "Bearer not-a-token"},
        )
        assert resp.status_code == 401

    def test_status_reports_keycloak_enabled(self, client):
        resp = client.get("/api/v1/auth/keycloak/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        assert resp.json()["client_id"] == CLIENT_ID

    def test_login_rejects_foreign_redirect(self, client):
        resp = client.get(
            "/api/v1/auth/keycloak/login",
            params={"redirect_uri": "https://evil.example/steal"},
            follow_redirects=False,
        )
        assert resp.status_code == 400


class TestOpenWebUIIdentity:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("OPENWEBUI_TRUSTED_AUTH", "false")
        config.reset_settings_cache()
        try:
            assert openwebui_service.trusted_auth_enabled() is False
            user = User(email="x@test.com", password_hash="x")
            assert openwebui_service.get_user_token(user) is None
        finally:
            monkeypatch.setenv("OPENWEBUI_TRUSTED_AUTH", "true")
            config.reset_settings_cache()

    def test_caches_signed_in_token(self, monkeypatch):
        monkeypatch.setenv("OPENWEBUI_TRUSTED_AUTH", "true")
        config.reset_settings_cache()
        calls = {"n": 0}

        def fake_signin(email, name=None):
            calls["n"] += 1
            return jwt.encode(
                {"exp": int(time.time()) + 600, "email": email},
                "owui-secret", algorithm="HS256",
            )

        monkeypatch.setattr(openwebui_service, "_signin", fake_signin)
        openwebui_service.invalidate("u1")
        user = User(id="u1", email="u1@test.com", password_hash="x")
        first = openwebui_service.get_user_token(user)
        second = openwebui_service.get_user_token(user)
        assert first == second
        assert calls["n"] == 1
        openwebui_service.invalidate("u1")


@pytest.fixture(autouse=True, scope="session")
def _cleanup_db():
    yield
    try:
        pathlib.Path("test_auth.db").unlink(missing_ok=True)
    except Exception:
        pass
