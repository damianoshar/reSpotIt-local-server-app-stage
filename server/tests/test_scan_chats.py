"""Tests for the AI scan chats (album scan + track scan).

A scan used to leave no trace in Open WebUI: the route answered with the
extracted rows and nothing else. Now every scan is written into a one-turn
chat (the request as the user message, the answer as the assistant message)
and the route answers with the chat id next to the rows.

Mocked only: no Open WebUI, no llama-server, no network.
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
from api.services import llm_service, user_auth_service


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
            email="scan-chat@test.com",
            password_hash=user_auth_service.hash_password("secret123"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id), row.email


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


@pytest.fixture()
def owui(monkeypatch):
    """Capture what the scan writes into Open WebUI."""
    from api.services import openwebui_service

    seen = {"chats": [], "exchanges": []}

    monkeypatch.setattr(openwebui_service, "get_user_token", lambda u: "owui-token")
    monkeypatch.setattr(openwebui_service, "resolve_model_id", lambda token=None: "model-x")

    def fake_create_chat(token, *, title="New Chat", model=None, chat_type=None):
        seen["chats"].append({"title": title, "model": model, "chat_type": chat_type})
        return {"id": "chat-1"}

    def fake_append_exchange(token, chat_id, user_text, assistant_text, **kwargs):
        seen["exchanges"].append({
            "chat_id": chat_id,
            "user_text": user_text,
            "assistant_text": assistant_text,
            "model": kwargs.get("model"),
        })
        return {"id": chat_id}

    monkeypatch.setattr(openwebui_service, "create_chat", fake_create_chat)
    monkeypatch.setattr(openwebui_service, "append_exchange", fake_append_exchange)
    return seen


# ---- album scan ----

def test_album_scan_writes_one_turn_into_a_chat(client, user, owui, monkeypatch):
    monkeypatch.setattr(
        llm_service, "extract_albums",
        lambda text, token=None: {"albums": [{"artist": "Radiohead", "album": "OK Computer"}]},
    )
    r = client.post(
        "/api/v1/llm/extract-albums",
        json={"text": "Radiohead - OK Computer"},
        headers=_auth(user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["albums"] == [
        {"artist": "Radiohead", "album": "OK Computer"}
    ]
    assert r.json()["chat_id"] == "chat-1"

    assert len(owui["chats"]) == 1
    assert owui["chats"][0]["chat_type"] == "extract_albums"
    assert owui["chats"][0]["model"] == "model-x"

    assert len(owui["exchanges"]) == 1
    turn = owui["exchanges"][0]
    assert turn["user_text"] == "Find the albums listed in the pasted text"
    assert "OK Computer" in turn["assistant_text"]
    assert "1 album(s)" in turn["assistant_text"]
    assert turn["model"] == "model-x"


def test_album_scan_names_the_page_in_the_chat(client, user, owui, monkeypatch):
    monkeypatch.setattr(
        llm_service, "fetch_page_text",
        lambda url, max_chars=6000: "Radiohead - OK Computer",
    )
    monkeypatch.setattr(
        llm_service, "extract_albums",
        lambda text, token=None: {"albums": [{"artist": "Radiohead", "album": "OK Computer"}]},
    )
    r = client.post(
        "/api/v1/llm/extract-albums",
        json={"url": "https://example.com/list"},
        headers=_auth(user),
    )
    assert r.status_code == 200, r.text
    assert owui["exchanges"][0]["user_text"] == (
        "Find the albums listed on https://example.com/list"
    )
    assert "https://example.com/list" in owui["chats"][0]["title"]


def test_an_empty_scan_still_writes_the_chat(client, user, owui, monkeypatch):
    monkeypatch.setattr(
        llm_service, "extract_albums", lambda text, token=None: {"albums": []},
    )
    r = client.post(
        "/api/v1/llm/extract-albums",
        json={"text": "nothing here"},
        headers=_auth(user),
    )
    assert r.status_code == 200, r.text
    assert "no albums found" in owui["exchanges"][0]["assistant_text"]


# ---- track scan ----

def test_track_scan_writes_one_turn_into_a_chat(client, user, owui, monkeypatch):
    monkeypatch.setattr(
        llm_service, "extract_tracks",
        lambda text, token=None: {"tracks": [{"artist": "Portishead", "title": "Roads"}]},
    )
    r = client.post(
        "/api/v1/llm/extract-tracks",
        json={"text": "Portishead - Roads"},
        headers=_auth(user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["chat_id"] == "chat-1"
    assert owui["chats"][0]["chat_type"] == "extract_tracks"
    turn = owui["exchanges"][0]
    assert turn["user_text"] == "Find the tracks listed in the pasted text"
    assert "Roads" in turn["assistant_text"]


# ---- resilience ----

def test_a_broken_chat_does_not_fail_the_scan(client, user, monkeypatch):
    """Open WebUI being down must not lose the extracted rows."""
    from api.services import openwebui_service

    monkeypatch.setattr(
        llm_service, "extract_albums",
        lambda text, token=None: {"albums": [{"artist": "Radiohead", "album": "OK Computer"}]},
    )
    monkeypatch.setattr(openwebui_service, "get_user_token", lambda u: "owui-token")
    monkeypatch.setattr(
        openwebui_service, "create_chat",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Open WebUI is down")),
    )
    r = client.post(
        "/api/v1/llm/extract-albums",
        json={"text": "Radiohead - OK Computer"},
        headers=_auth(user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["albums"] == [
        {"artist": "Radiohead", "album": "OK Computer"}
    ]
    assert r.json()["chat_id"] is None
