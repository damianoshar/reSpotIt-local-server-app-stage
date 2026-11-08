"""Concerts + hidden-albums server store (Phase B, docs/STORAGE-POLICY.md).

Mocked/isolated only: SQLite engine, no Postgres/network. Exercises CRUD,
batch upsert, mirror import and per-user isolation.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

from api.database import engine, get_db  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Base, User  # noqa: E402
from api.services import user_auth_service  # noqa: E402


@pytest.fixture()
def Session():
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.query(User).delete()
        db.commit()
    return factory


def _make_user(Session, email):
    with Session() as db:
        row = User(
            email=email,
            password_hash=user_auth_service.hash_password("secret123"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id), row.email


@pytest.fixture()
def user(Session):
    return _make_user(Session, "stores@test.com")


@pytest.fixture()
def other_user(Session):
    return _make_user(Session, "other@test.com")


@pytest.fixture()
def client(Session):
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


CONCERT = {
    "id": "c1",
    "artist": "Radiohead",
    "artist_id": "a1",
    "title": "In Rainbows Tour",
    "date": "2026-06-01",
    "venue": "O2",
    "url": "https://example.com/c1",
    "source_url": "https://example.com",
    "followed": True,
    "created_at": "2026-05-01T10:00:00",
}

ALBUM = {
    "id": "h1",
    "title": "OK Computer",
    "artist": "Radiohead",
    "year": 1997,
    "genre": "Alternative",
    "album_type": "album",
    "image_url": "http://img/1",
    "added_at": "2026-01-01",
}


# ── Concerts ──────────────────────────────────────────────────────────────────

def test_concerts_require_auth(client):
    assert client.get("/api/v1/concerts").status_code == 401
    assert client.post("/api/v1/concerts", json={"items": []}).status_code == 401


def test_concert_upsert_list_delete_roundtrip(client, user):
    r = client.post("/api/v1/concerts", json={"items": [CONCERT]}, headers=_auth(user))
    assert r.status_code == 200 and r.json()["upserted"] == 1

    r = client.get("/api/v1/concerts", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    got = body["concerts"][0]
    assert got["id"] == "c1" and got["artist"] == "Radiohead"
    assert got["followed"] is True

    # Re-upsert updates rather than duplicates.
    updated = {**CONCERT, "venue": "Wembley"}
    client.post("/api/v1/concerts", json={"items": [updated]}, headers=_auth(user))
    body = client.get("/api/v1/concerts", headers=_auth(user)).json()
    assert body["total"] == 1 and body["concerts"][0]["venue"] == "Wembley"

    r = client.delete("/api/v1/concerts/c1", headers=_auth(user))
    assert r.json()["deleted"] == 1
    assert client.get("/api/v1/concerts", headers=_auth(user)).json()["total"] == 0


def test_concerts_clear(client, user):
    client.post("/api/v1/concerts", json={"items": [CONCERT]}, headers=_auth(user))
    r = client.delete("/api/v1/concerts", headers=_auth(user))
    assert r.json()["deleted"] == 1
    assert client.get("/api/v1/concerts", headers=_auth(user)).json()["total"] == 0


def test_concerts_import_mirror_removes_absent(client, user):
    client.post("/api/v1/concerts",
                json={"items": [CONCERT, {**CONCERT, "id": "c2"}]},
                headers=_auth(user))
    r = client.post("/api/v1/concerts/import",
                    json={"items": [CONCERT], "replace": True},
                    headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] == 1 and body["existing"] == 1
    remaining = client.get("/api/v1/concerts", headers=_auth(user)).json()
    assert [c["id"] for c in remaining["concerts"]] == ["c1"]


def test_concerts_import_replace_with_no_rows_never_wipes(client, user):
    client.post("/api/v1/concerts", json={"items": [CONCERT]}, headers=_auth(user))
    r = client.post("/api/v1/concerts/import",
                    json={"items": [], "replace": True}, headers=_auth(user))
    body = r.json()
    assert body["removed"] == 0
    assert any("Mirror skipped" in e for e in body["errors"])
    assert client.get("/api/v1/concerts", headers=_auth(user)).json()["total"] == 1


def test_concerts_are_user_scoped(client, user, other_user):
    client.post("/api/v1/concerts", json={"items": [CONCERT]}, headers=_auth(user))
    assert client.get("/api/v1/concerts", headers=_auth(other_user)).json()["total"] == 0
    assert client.delete("/api/v1/concerts/c1", headers=_auth(other_user)).json()["deleted"] == 0


# ── Hidden albums ─────────────────────────────────────────────────────────────

def test_hidden_require_auth(client):
    assert client.get("/api/v1/albums/hidden").status_code == 401


def test_hidden_route_does_not_shadow_album_detail(client, user):
    """GET /albums/hidden must hit this router, not albums' /{spotify_id}."""
    r = client.get("/api/v1/albums/hidden", headers=_auth(user))
    assert r.status_code == 200
    assert r.json() == {"total": 0, "albums": []}


def test_hidden_hide_list_restore(client, user):
    r = client.post("/api/v1/albums/hidden", json={"items": [ALBUM]}, headers=_auth(user))
    assert r.status_code == 200 and r.json()["hidden"] == 1

    body = client.get("/api/v1/albums/hidden", headers=_auth(user)).json()
    assert body["total"] == 1
    got = body["albums"][0]
    assert got["id"] == "h1" and got["spotify_id"] == "h1"
    assert got["year"] == 1997 and got["album_type"] == "album"

    r = client.delete("/api/v1/albums/hidden/h1", headers=_auth(user))
    assert r.json()["deleted"] == 1
    assert client.get("/api/v1/albums/hidden", headers=_auth(user)).json()["total"] == 0


def test_hidden_restore_all(client, user):
    client.post("/api/v1/albums/hidden",
                json={"items": [ALBUM, {**ALBUM, "id": "h2"}]}, headers=_auth(user))
    r = client.delete("/api/v1/albums/hidden", headers=_auth(user))
    assert r.json()["deleted"] == 2
    assert client.get("/api/v1/albums/hidden", headers=_auth(user)).json()["total"] == 0


def test_hidden_import_mirror(client, user):
    client.post("/api/v1/albums/hidden",
                json={"items": [ALBUM, {**ALBUM, "id": "h2"}]}, headers=_auth(user))
    r = client.post("/api/v1/albums/hidden/import",
                    json={"items": [ALBUM], "replace": True}, headers=_auth(user))
    body = r.json()
    assert body["removed"] == 1 and body["existing"] == 1
    remaining = client.get("/api/v1/albums/hidden", headers=_auth(user)).json()
    assert [a["id"] for a in remaining["albums"]] == ["h1"]


def test_hidden_accepts_spotify_id_alias(client, user):
    r = client.post("/api/v1/albums/hidden",
                    json={"items": [{"spotify_id": "h9", "title": "X"}]},
                    headers=_auth(user))
    assert r.status_code == 200 and r.json()["hidden"] == 1
