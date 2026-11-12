"""Tests for the AI track scan (extract-tracks + resolve-tracks).

Mocked only: no Open WebUI, Spotify or network is contacted.

The two routes are read-only: the scan resolves tracks and returns them, it
never writes to Spotify (UI policy P9).
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
            email="tracks@test.com",
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


# ---- LLM extract-tracks ----

def test_extract_tracks_requires_auth(client):
    assert client.post("/api/v1/llm/extract-tracks", json={"text": "x"}).status_code == 401


def test_extract_tracks_from_text(client, user, monkeypatch):
    import api.services.llm_service as llm_service
    monkeypatch.setattr(
        llm_service, "extract_tracks",
        lambda text, token=None: {"tracks": [{"artist": "Radiohead", "title": "Weird Fishes"}]},
    )
    r = client.post(
        "/api/v1/llm/extract-tracks",
        json={"text": "Radiohead - Weird Fishes"},
        headers=_auth(user),
    )
    assert r.status_code == 200
    assert r.json()["data"]["tracks"] == [
        {"artist": "Radiohead", "title": "Weird Fishes"}
    ]


def test_extract_tracks_empty_input(client, user):
    r = client.post("/api/v1/llm/extract-tracks", json={}, headers=_auth(user))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "llm_empty_input"


def test_extract_tracks_dedupes_and_drops_empty_pairs(monkeypatch):
    import api.services.llm_service as llm_service

    def fake_extract(system, user_text, *, token=None, max_tokens=1024, timeout=None):
        return {
            "tracks": [
                {"artist": "Radiohead", "title": "Weird Fishes"},
                {"artist": "radiohead", "title": "weird fishes"},
                {"artist": "", "title": ""},
                {"artist": "Portishead", "title": "Roads"},
            ]
        }

    monkeypatch.setattr(llm_service, "extract_structured", fake_extract)
    out = llm_service.extract_tracks("page text")
    assert out["tracks"] == [
        {"artist": "Radiohead", "title": "Weird Fishes"},
        {"artist": "Portishead", "title": "Roads"},
    ]


def test_extract_tracks_retries_an_empty_answer(monkeypatch):
    """The local model sometimes answers {"tracks": []} for a real tracklist."""
    import api.services.llm_service as llm_service

    calls = []

    def fake_extract(system, user_text, *, token=None, max_tokens=1024, timeout=None):
        calls.append(user_text)
        if len(calls) == 1:
            return {"tracks": []}
        return {"tracks": [{"artist": "Radiohead", "title": "Weird Fishes"}]}

    monkeypatch.setattr(llm_service, "extract_structured", fake_extract)
    out = llm_service.extract_tracks("Radiohead Weird Fishes. Portishead Roads.")

    assert out["tracks"] == [{"artist": "Radiohead", "title": "Weird Fishes"}]
    assert len(calls) == 2
    # The retry nudges the model, and the nudge goes on the user message so
    # the cached prompt prefix survives.
    assert llm_service._TRACK_NUDGE_EMPTY in calls[1]
    assert llm_service._TRACK_NUDGE_EMPTY not in calls[0]


def test_extract_tracks_drops_a_nudged_track_the_page_does_not_mention(monkeypatch):
    """The retry must not be able to invent a song."""
    import api.services.llm_service as llm_service

    calls = []

    def fake_extract(system, user_text, *, token=None, max_tokens=1024, timeout=None):
        calls.append(user_text)
        if len(calls) == 1:
            return {"tracks": []}
        return {
            "tracks": [
                {"artist": "Radiohead", "title": "Weird Fishes"},
                {"artist": "Nobody", "title": "Song That Is Not Listed"},
            ]
        }

    monkeypatch.setattr(llm_service, "extract_structured", fake_extract)
    out = llm_service.extract_tracks("Radiohead Weird Fishes. Portishead Roads.")

    assert out["tracks"] == [{"artist": "Radiohead", "title": "Weird Fishes"}]


def test_extract_tracks_keeps_an_empty_page_empty(monkeypatch):
    """A page without songs stays empty, even after the retry."""
    import api.services.llm_service as llm_service

    def fake_extract(system, user_text, *, token=None, max_tokens=1024, timeout=None):
        return {"tracks": []}

    monkeypatch.setattr(llm_service, "extract_structured", fake_extract)
    out = llm_service.extract_tracks("A recipe for soup with potatoes and carrots.")

    assert out["tracks"] == []


# ---- Spotify resolve-tracks ----

def test_resolve_tracks_requires_auth(client):
    assert client.post("/api/v1/spotify/resolve-tracks", json={"items": []}).status_code == 401


def test_resolve_tracks(client, user, monkeypatch):
    import api.routers.spotify_actions as rmod
    monkeypatch.setattr(rmod, "is_authenticated", lambda uid: True)
    monkeypatch.setattr(rmod, "_token", lambda uid: "tok")
    monkeypatch.setattr(
        rmod, "resolve_tracks",
        lambda token, items: {
            "resolved": [{"spotify_id": "t1", "uri": "spotify:track:t1"}],
            "unresolved": [],
        },
    )
    r = client.post(
        "/api/v1/spotify/resolve-tracks",
        json={"items": [{"artist": "Radiohead", "title": "Weird Fishes"}]},
        headers=_auth(user),
    )
    assert r.status_code == 200
    assert r.json()["resolved"][0]["uri"] == "spotify:track:t1"


def test_resolve_tracks_service_maps_the_spotify_hit():
    from api.services import spotify_actions

    hit = {
        "id": "t1", "uri": "spotify:track:t1", "name": "Weird Fishes / Arpeggi",
        "artist": "Radiohead", "album": "OK Computer", "album_id": "a1",
        "image_url": "https://i.scdn.co/image/x", "spotify_url": "https://open.spotify.com/track/t1",
        "duration_ms": 281000,
    }
    with patch.object(spotify_actions, "search_spotify_tracks", return_value=[hit]):
        out = spotify_actions.resolve_tracks(
            "tok", [{"artist": "Radiohead", "title": "Weird Fishes"}],
        )

    assert out["unresolved"] == []
    resolved = out["resolved"][0]
    assert resolved["spotify_id"] == "t1"
    assert resolved["uri"] == "spotify:track:t1"
    assert resolved["name"] == "Weird Fishes / Arpeggi"
    assert resolved["artist_name"] == "Radiohead"
    assert resolved["album_name"] == "OK Computer"
    assert resolved["duration_ms"] == 281000


def test_resolve_tracks_reports_a_miss_as_unresolved():
    from api.services import spotify_actions

    with patch.object(spotify_actions, "search_spotify_tracks", return_value=[]):
        out = spotify_actions.resolve_tracks(
            "tok", [{"artist": "Nobody", "title": "Nothing"}],
        )

    assert out["resolved"] == []
    assert out["unresolved"] == [{"artist": "Nobody", "title": "Nothing"}]


def test_best_track_match_rejects_an_unrelated_first_result():
    from api.services import spotify_actions

    hits = [
        {"id": "m1", "name": "Mple", "artist": "Mple"},
        {"id": "m2", "name": "Mple Live", "artist": "Mple"},
    ]
    assert spotify_actions._best_track_match(
        hits, "Some Other Band", "Mple") is None


def test_resolve_tracks_skips_a_failing_search():
    from api.services import spotify_actions

    with patch.object(spotify_actions, "search_spotify_tracks",
                      side_effect=RuntimeError("spotify down")):
        out = spotify_actions.resolve_tracks(
            "tok", [{"artist": "Radiohead", "title": "Weird Fishes"}],
        )

    assert out["resolved"] == []
    assert out["unresolved"] == [{"artist": "Radiohead", "title": "Weird Fishes"}]
