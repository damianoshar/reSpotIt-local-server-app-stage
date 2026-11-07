"""Tests for Phase 0 AI URL scan endpoints.

Mocked only: no Open WebUI, Spotify or network is contacted.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

from api.database import engine, get_db
from api.main import app
from api.models import Base, User
from api.services import user_auth_service


@pytest.fixture()
def Session():
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.query(User).delete()
        db.commit()
    return factory


@pytest.fixture()
def user(Session):
    with Session() as db:
        row = User(
            email="phase0@test.com",
            password_hash=user_auth_service.hash_password("secret123"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id), row.email


@pytest.fixture()
def client(Session, monkeypatch):
    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _auth(user):
    user_id, email = user
    token = user_auth_service.create_access_token(user_id, email)
    return {"Authorization": f"Bearer {token}"}


# ---- LLM extract endpoints ----

def test_extract_albums_requires_auth(client):
    assert client.post("/api/v1/llm/extract-albums", json={"text": "x"}).status_code == 401


def test_extract_albums_from_text(client, user, monkeypatch):
    import api.services.llm_service as llm_service
    monkeypatch.setattr(llm_service, "extract_albums", lambda text, token=None: {"albums": [{"artist": "Radiohead", "album": "OK Computer"}]})
    r = client.post("/api/v1/llm/extract-albums", json={"text": "Radiohead OK Computer"}, headers=_auth(user))
    assert r.status_code == 200
    assert r.json()["data"]["albums"] == [{"artist": "Radiohead", "album": "OK Computer"}]


def test_extract_albums_empty_input(client, user):
    r = client.post("/api/v1/llm/extract-albums", json={}, headers=_auth(user))
    assert r.status_code == 422


def test_extract_concerts_requires_auth(client):
    assert client.post("/api/v1/llm/extract-concerts", json={"text": "x"}).status_code == 401


def test_extract_concerts_from_text(client, user, monkeypatch):
    import api.services.llm_service as llm_service
    monkeypatch.setattr(llm_service, "extract_concerts", lambda text, token=None: {"concerts": [{"artist": "Radiohead", "date": "2026-06-01", "venue": "O2", "url": ""}]})
    r = client.post("/api/v1/llm/extract-concerts", json={"text": "Radiohead at O2"}, headers=_auth(user))
    assert r.status_code == 200
    assert r.json()["data"]["concerts"][0]["artist"] == "Radiohead"


# ---- Spotify resolve endpoints ----

def test_resolve_albums_requires_auth(client):
    assert client.post("/api/v1/spotify/resolve-albums", json={"items": []}).status_code == 401


def test_resolve_albums(client, user, monkeypatch):
    import api.routers.spotify_actions as rmod
    monkeypatch.setattr(rmod, "is_authenticated", lambda uid: True)
    monkeypatch.setattr(rmod, "_token", lambda uid: "tok")
    monkeypatch.setattr(rmod, "resolve_albums", lambda token, items: {"resolved": [{"spotify_id": "abc", "title": "OK Computer"}], "unresolved": []})
    r = client.post("/api/v1/spotify/resolve-albums", json={"items": [{"artist": "Radiohead", "album": "OK Computer"}]}, headers=_auth(user))
    assert r.status_code == 200
    assert r.json()["resolved"][0]["spotify_id"] == "abc"


def test_followed_artists_requires_auth(client):
    assert client.get("/api/v1/spotify/followed-artists").status_code == 401


def test_followed_artists(client, user, monkeypatch):
    import api.routers.spotify_actions as rmod
    monkeypatch.setattr(rmod, "is_authenticated", lambda uid: True)
    monkeypatch.setattr(rmod, "_token", lambda uid: "tok")
    monkeypatch.setattr(rmod, "get_followed_artists", lambda token: [{"id": "a1", "name": "Radiohead", "image_url": "", "genres": []}])
    r = client.get("/api/v1/spotify/followed-artists", headers=_auth(user))
    assert r.status_code == 200
    assert r.json()["artists"][0]["name"] == "Radiohead"


def test_resolve_artists_requires_auth(client):
    assert client.post("/api/v1/spotify/resolve-artists", json={"names": ["Radiohead"]}).status_code == 401


def test_resolve_artists(client, user, monkeypatch):
    import api.routers.spotify_actions as rmod
    monkeypatch.setattr(rmod, "is_authenticated", lambda uid: True)
    monkeypatch.setattr(rmod, "_token", lambda uid: "tok")
    monkeypatch.setattr(rmod, "resolve_artists", lambda token, names: {"resolved": [{"name": "Radiohead", "spotify_id": "a1", "followed": True}], "unresolved": []})
    r = client.post("/api/v1/spotify/resolve-artists", json={"names": ["Radiohead"]}, headers=_auth(user))
    assert r.status_code == 200
    assert r.json()["resolved"][0]["followed"] is True
