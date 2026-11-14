"""Tests for GET /api/v1/playlists/{id}/albums (filters + "Date Added").

Regression: the route used to declare ``year_from``/``year_to`` as ``int``.
Clients that send an empty filter (``year_from=``) got a 422 and the playlist
album grid never loaded. The parameters are now strings that tolerate an
empty value, and "Date Added" sorts by the album's playlist position.

Mocked only: no Postgres, no Spotify.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

from api.database import engine, get_db
from api.main import app
from api.models import Base, User
from api.services import user_auth_service

GROUPS = [
    {
        "album_spotify_id": "a2",
        "title": "Rumours",
        "artist": "Fleetwood Mac",
        "year": 1977,
        "genre": "Rock",
        "image_url": "",
        "track_count": 2,
        "track_titles": ["Second Hand News", "Go Your Own Way"],
        "position": 3,
    },
    {
        "album_spotify_id": "a1",
        "title": "OK Computer",
        "artist": "Radiohead",
        "year": 1997,
        "genre": "Rock",
        "image_url": "",
        "track_count": 1,
        "track_titles": ["Let Down"],
        "position": 1,
    },
]


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
            email="playlist-albums@test.com",
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
    import api.routers.spotify_actions as rmod
    from api.services import playlist_cache

    monkeypatch.setattr(rmod, "_cached_or_404", lambda playlist_id, user_id: {
        "id": playlist_id, "name": "Test", "synced_at": "2026-01-01T00:00:00Z",
    })
    monkeypatch.setattr(playlist_cache, "album_groups", lambda spotify_id, user_id: GROUPS)
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _auth(user):
    user_id, email = user
    token = user_auth_service.create_access_token(user_id, email)
    return {"Authorization": f"Bearer {token}"}


def _get(client, user, query=""):
    return client.get(
        f"/api/v1/playlists/pl-1/albums{query}", headers=_auth(user),
    )


def test_empty_year_filters_do_not_fail_the_request(client, user):
    """The regression: year_from= / year_to= used to answer 422."""
    r = _get(client, user, "?year_from=&year_to=&search=&genre=&artist=")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2


def test_missing_year_filters_are_ignored(client, user):
    r = _get(client, user)
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_year_filters_still_apply(client, user):
    r = _get(client, user, "?year_from=1990&year_to=2000")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["items"]] == ["a1"]


def test_an_unparsable_year_filter_is_ignored(client, user):
    r = _get(client, user, "?year_from=abc")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_date_added_sorts_by_the_playlist_position(client, user):
    r = _get(client, user, "?sort=added_at&order=asc")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["items"]] == ["a1", "a2"]

    r = _get(client, user, "?sort=added_at&order=desc")
    assert [i["id"] for i in r.json()["items"]] == ["a2", "a1"]


def test_each_album_carries_its_playlist_position(client, user):
    r = _get(client, user)
    positions = {i["id"]: i["position"] for i in r.json()["items"]}
    assert positions == {"a1": 1, "a2": 3}


def test_the_default_sort_is_still_the_artist(client, user):
    r = _get(client, user)
    assert [i["id"] for i in r.json()["items"]] == ["a2", "a1"]
