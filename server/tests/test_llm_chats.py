"""Tests for Phase 5/6 chat history: current-chat pointer + Open WebUI chats.

Mocked only: no Open WebUI, llama-server or Keycloak is contacted. The SQL
tests use the throwaway SQLite database configured in ``conftest.py``.

Run from the server directory:

    python -m pytest tests/test_llm_chats.py -q
"""

import os
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

from api.database import engine, get_db
from api.main import app
from api.models import Base, LLMChatSession, User
from api.services import (
    chat_session_service,
    llm_service,
    openwebui_service,
    user_auth_service,
)


def _response(status: int = 200, payload=None, text: str = "") -> Mock:
    resp = Mock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = text
    resp.content = b"x" if payload is not None else b""
    return resp


@pytest.fixture()
def Session():
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.query(LLMChatSession).delete()
        db.query(User).delete()
        db.commit()
    return factory


@pytest.fixture()
def user(Session):
    with Session() as db:
        row = User(
            email="chats@test.com",
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
    monkeypatch.setattr(openwebui_service, "get_user_token", lambda u: "owui-token")
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _auth(user):
    user_id, email = user
    token = user_auth_service.create_access_token(user_id, email)
    return {"Authorization": f"Bearer {token}"}


# ── current-chat pointer ───────────────────────────────────────────────────


class TestChatSessionService:
    def test_set_then_get(self, Session, user):
        user_id, _ = user
        with Session() as db:
            assert chat_session_service.get_current_chat_id(db, user_id) is None
            chat_session_service.set_current_chat_id(db, user_id, "chat-1")
            assert chat_session_service.get_current_chat_id(db, user_id) == "chat-1"

    def test_set_reuses_one_row(self, Session, user):
        user_id, _ = user
        with Session() as db:
            chat_session_service.set_current_chat_id(db, user_id, "chat-1")
            chat_session_service.set_current_chat_id(db, user_id, "chat-2")
            assert db.query(LLMChatSession).count() == 1
            assert chat_session_service.get_current_chat_id(db, user_id) == "chat-2"

    def test_clear_matching_only(self, Session, user):
        user_id, _ = user
        with Session() as db:
            chat_session_service.set_current_chat_id(db, user_id, "chat-1")
            chat_session_service.clear_current_chat_id(db, user_id, "other")
            assert chat_session_service.get_current_chat_id(db, user_id) == "chat-1"
            chat_session_service.clear_current_chat_id(db, user_id, "chat-1")
            assert chat_session_service.get_current_chat_id(db, user_id) is None

    def test_clear_unknown_user_is_noop(self, Session):
        with Session() as db:
            chat_session_service.clear_current_chat_id(db, "missing", "chat-1")
            assert chat_session_service.get_current_chat_id(db, "missing") is None


# ── Open WebUI chat helpers ────────────────────────────────────────────────


class TestChatHelpers:
    def test_requires_token(self):
        with pytest.raises(openwebui_service.OpenWebUIError):
            openwebui_service.list_chats(None)

    def test_list_chats_uses_bearer_and_limit(self, monkeypatch):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _response(200, [{"id": "a"}, {"id": "b"}, {"id": "c"}])

        monkeypatch.setattr(openwebui_service.requests, "request", fake_request)
        rows = openwebui_service.list_chats("tok", limit=2)
        assert [r["id"] for r in rows] == ["a", "b"]
        method, url, kwargs = calls[0]
        assert method == "GET"
        assert url.endswith("/api/v1/chats/")
        assert kwargs["headers"]["Authorization"] == "Bearer tok"

    def test_get_chat_404_maps_to_not_found(self, monkeypatch):
        monkeypatch.setattr(
            openwebui_service.requests, "request",
            lambda *a, **k: _response(404, {"detail": "Not found"}),
        )
        with pytest.raises(openwebui_service.OpenWebUIChatNotFound):
            openwebui_service.get_chat("tok", "missing")

    def test_get_chat_401_maps_to_credential_rejected(self, monkeypatch):
        monkeypatch.setattr(
            openwebui_service.requests, "request",
            lambda *a, **k: _response(401, {"detail": "bad token"}),
        )
        with pytest.raises(openwebui_service.OpenWebUICredentialRejected):
            openwebui_service.get_chat("tok", "chat-1")

    def test_create_chat_posts_chat_shape(self, monkeypatch):
        seen = {}

        def fake_request(method, url, **kwargs):
            seen.update({"method": method, "url": url, "json": kwargs["json"]})
            return _response(200, {"id": "new-chat", "chat": kwargs["json"]["chat"]})

        monkeypatch.setattr(openwebui_service.requests, "request", fake_request)
        row = openwebui_service.create_chat("tok", title="Hi", model="m")
        assert row["id"] == "new-chat"
        assert seen["method"] == "POST"
        assert seen["url"].endswith("/api/v1/chats/new")
        chat = seen["json"]["chat"]
        assert chat["title"] == "Hi"
        assert chat["models"] == ["m"]
        assert chat["history"] == {"messages": {}, "currentId": None}

    def test_history_messages_keeps_last_turns(self):
        row = {
            "chat": {
                "messages": [
                    {"role": "system", "content": "ignore"},
                    {"role": "user", "content": "one"},
                    {"role": "assistant", "content": "two"},
                    {"role": "user", "content": "   "},
                    {"role": "user", "content": "three"},
                ]
            }
        }
        assert openwebui_service.history_messages(row, 2) == [
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ]
        assert openwebui_service.history_messages(row, 0) == []

    def test_append_exchange_keeps_flat_and_tree_in_sync(self, monkeypatch):
        stored = {
            "id": "chat-1",
            "title": "Existing",
            "chat": {
                "title": "Existing",
                "messages": [
                    {"id": "m1", "parentId": None, "childrenIds": [],
                     "role": "user", "content": "old"},
                ],
                "history": {
                    "messages": {
                        "m1": {"id": "m1", "parentId": None,
                               "childrenIds": [], "role": "user",
                               "content": "old"},
                    },
                    "currentId": "m1",
                },
            },
        }
        captured = {}

        monkeypatch.setattr(openwebui_service, "get_chat", lambda token, cid: stored)
        monkeypatch.setattr(
            openwebui_service, "update_chat",
            lambda token, cid, chat: captured.update(chat=chat) or {"id": cid},
        )

        openwebui_service.append_exchange(
            "tok", "chat-1", "new question", "new answer", model="m"
        )

        chat = captured["chat"]
        assert len(chat["messages"]) == 3
        user_msg, assistant_msg = chat["messages"][1:]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == "new question"
        assert user_msg["parentId"] == "m1"
        assert assistant_msg["parentId"] == user_msg["id"]
        assert assistant_msg["done"] is True

        tree = chat["history"]["messages"]
        assert tree["m1"]["childrenIds"] == [user_msg["id"]]
        assert tree[user_msg["id"]]["childrenIds"] == [assistant_msg["id"]]
        assert chat["history"]["currentId"] == assistant_msg["id"]
        # A chat that already has a title keeps it.
        assert chat["title"] == "Existing"

    def test_append_exchange_titles_new_chat(self, monkeypatch):
        stored = {
            "id": "chat-1",
            "title": "New Chat",
            "chat": {"title": "New Chat", "messages": [],
                     "history": {"messages": {}, "currentId": None}},
        }
        captured = {}
        monkeypatch.setattr(openwebui_service, "get_chat", lambda token, cid: stored)
        monkeypatch.setattr(
            openwebui_service, "update_chat",
            lambda token, cid, chat: captured.update(chat=chat) or {"id": cid},
        )

        openwebui_service.append_exchange("tok", "chat-1", "q", "a", title="My title")
        assert captured["chat"]["title"] == "My title"

    def test_append_exchange_names_one_model_on_the_user_message(self, monkeypatch):
        """Open WebUI hides an answer when the user message has no model."""
        stored = {
            "id": "chat-1",
            "title": "Scan",
            "chat": {"title": "Scan", "messages": [],
                     "history": {"messages": {}, "currentId": None}},
        }
        captured = {}

        monkeypatch.setattr(openwebui_service, "get_chat", lambda token, cid: stored)
        monkeypatch.setattr(
            openwebui_service, "update_chat",
            lambda token, cid, chat: captured.update(chat=chat) or {"id": cid},
        )
        monkeypatch.setattr(
            openwebui_service, "resolve_model_id", lambda token=None: "model-x",
        )

        openwebui_service.append_exchange("tok", "chat-1", "question", "answer")

        chat = captured["chat"]
        user_msg, assistant_msg = chat["messages"]
        assert user_msg["models"] == ["model-x"]
        assert assistant_msg["model"] == "model-x"
        assert assistant_msg["modelName"] == "model-x"

    def test_append_assistant_text_extends_the_last_assistant_message(self, monkeypatch):
        stored = {
            "id": "chat-1",
            "title": "Scan",
            "chat": {
                "title": "Scan",
                "messages": [
                    {"id": "u1", "parentId": None, "childrenIds": ["a1"],
                     "role": "user", "content": "question", "models": ["m"]},
                    {"id": "a1", "parentId": "u1", "childrenIds": [],
                     "role": "assistant", "content": "first", "model": "m",
                     "done": True},
                ],
                "history": {
                    "messages": {
                        "u1": {"id": "u1", "parentId": None, "childrenIds": ["a1"],
                               "role": "user", "content": "question", "models": ["m"]},
                        "a1": {"id": "a1", "parentId": "u1", "childrenIds": [],
                               "role": "assistant", "content": "first", "model": "m",
                               "done": True},
                    },
                    "currentId": "a1",
                },
            },
        }
        captured = {}

        monkeypatch.setattr(openwebui_service, "get_chat", lambda token, cid: stored)
        monkeypatch.setattr(
            openwebui_service, "update_chat",
            lambda token, cid, chat: captured.update(chat=chat) or {"id": cid},
        )

        openwebui_service.append_assistant_text("tok", "chat-1", "second", model="m")

        chat = captured["chat"]
        assert len(chat["messages"]) == 2
        assert chat["messages"][1]["content"] == "first\n\nsecond"
        assert chat["history"]["messages"]["a1"]["content"] == "first\n\nsecond"
        assert chat["history"]["currentId"] == "a1"

    def test_append_assistant_text_without_assistant_message_fails(self, monkeypatch):
        stored = {
            "id": "chat-1",
            "title": "Scan",
            "chat": {"title": "Scan", "messages": [],
                     "history": {"messages": {}, "currentId": None}},
        }
        monkeypatch.setattr(openwebui_service, "get_chat", lambda token, cid: stored)
        with pytest.raises(openwebui_service.OpenWebUIChatNotFound):
            openwebui_service.append_assistant_text("tok", "chat-1", "text")


# ── routes ─────────────────────────────────────────────────────────────────


class TestChatRoutes:
    def test_requires_auth(self, client):
        assert client.get("/api/v1/llm/chats").status_code == 401
        assert client.get("/api/v1/llm/chats/current").status_code == 401

    def test_list_chats(self, client, user, monkeypatch):
        monkeypatch.setattr(
            openwebui_service, "list_chats",
            lambda token, limit=50, chat_type=None: [{"id": "chat-1", "title": "One"}],
        )
        r = client.get("/api/v1/llm/chats", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["data"] == [{"id": "chat-1", "title": "One"}]

    def test_create_sets_current_pointer(self, client, user, monkeypatch):
        monkeypatch.setattr(
            openwebui_service, "create_chat",
            lambda token, title="New Chat", model=None, chat_type=None: {
                "id": "chat-new", "title": title,
            },
        )
        r = client.post(
            "/api/v1/llm/chats", json={"title": "Plan"}, headers=_auth(user)
        )
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "chat-new"

        monkeypatch.setattr(
            openwebui_service, "get_chat",
            lambda token, chat_id: {"id": chat_id, "title": "Plan"},
        )
        r = client.get("/api/v1/llm/chats/current", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "chat-new"

    def test_current_chat_clears_stale_pointer(self, client, user, Session, monkeypatch):
        user_id, _ = user
        with Session() as db:
            chat_session_service.set_current_chat_id(db, user_id, "gone")

        def raise_missing(token, chat_id):
            raise openwebui_service.OpenWebUIChatNotFound("Chat not found.")

        monkeypatch.setattr(openwebui_service, "get_chat", raise_missing)
        r = client.get("/api/v1/llm/chats/current", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["data"] is None
        with Session() as db:
            assert chat_session_service.get_current_chat_id(db, user_id) is None

    def test_clear_current_pointer(self, client, user, Session, monkeypatch):
        user_id, _ = user
        with Session() as db:
            chat_session_service.set_current_chat_id(db, user_id, "chat-1")

        r = client.delete("/api/v1/llm/chats/current", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["data"] == {"cleared": True}
        with Session() as db:
            assert chat_session_service.get_current_chat_id(db, user_id) is None

    def test_delete_clears_pointer(self, client, user, Session, monkeypatch):
        user_id, _ = user
        with Session() as db:
            chat_session_service.set_current_chat_id(db, user_id, "chat-1")

        monkeypatch.setattr(
            openwebui_service, "delete_chat", lambda token, chat_id: True
        )
        r = client.delete("/api/v1/llm/chats/chat-1", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["data"] == {"deleted": True, "chat_id": "chat-1"}
        with Session() as db:
            assert chat_session_service.get_current_chat_id(db, user_id) is None

    def test_missing_chat_returns_404(self, client, user, monkeypatch):
        def raise_missing(token, chat_id):
            raise openwebui_service.OpenWebUIChatNotFound("Chat not found.")

        monkeypatch.setattr(openwebui_service, "get_chat", raise_missing)
        r = client.get("/api/v1/llm/chats/nope", headers=_auth(user))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "llm_chat_not_found"

    def test_chat_prepends_history_and_persists(self, client, user, monkeypatch):
        stored = {
            "id": "chat-1",
            "chat": {
                "messages": [
                    {"role": "user", "content": "earlier q"},
                    {"role": "assistant", "content": "earlier a"},
                ],
                "history": {"messages": {}, "currentId": None},
            },
        }
        seen = {}

        monkeypatch.setattr(openwebui_service, "get_chat", lambda token, cid: stored)

        def fake_llm(messages, **kwargs):
            seen["messages"] = list(messages)
            seen["kwargs"] = kwargs
            return {"content": "fresh answer", "model": "qwen"}

        monkeypatch.setattr(llm_service, "chat", fake_llm)

        def fake_append(token, chat_id, user_text, assistant_text, **kwargs):
            seen["append"] = (chat_id, user_text, assistant_text, kwargs)
            return {"id": chat_id}

        monkeypatch.setattr(openwebui_service, "append_exchange", fake_append)

        r = client.post(
            "/api/v1/llm/chat",
            json={
                "messages": [{"role": "user", "content": "new q"}],
                "chat_id": "chat-1",
                "use_history": True,
                "history_limit": 2,
                "persist": True,
            },
            headers=_auth(user),
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["content"] == "fresh answer"
        assert data["chat_id"] == "chat-1"
        assert data["persisted"] is True
        assert seen["messages"] == [
            {"role": "user", "content": "earlier q"},
            {"role": "assistant", "content": "earlier a"},
            {"role": "user", "content": "new q"},
        ]
        assert seen["append"][:3] == ("chat-1", "new q", "fresh answer")

    def test_chat_without_persist_does_not_write(self, client, user, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat",
            lambda messages, **kwargs: {"content": "answer", "model": "qwen"},
        )

        def boom(*args, **kwargs):
            raise AssertionError("append_exchange must not be called")

        monkeypatch.setattr(openwebui_service, "append_exchange", boom)
        r = client.post(
            "/api/v1/llm/chat",
            json={"messages": [{"role": "user", "content": "q"}], "persist": False},
            headers=_auth(user),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["chat_id"] is None
        assert data["persisted"] is False
