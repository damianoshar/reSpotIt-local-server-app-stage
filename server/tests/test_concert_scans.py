"""Click-and-forget AI concert scans (additive /api/v1/concert-scans).

Isolated SQLite, no network: the Open WebUI progress writes and the LLM
extraction are mocked. Endpoint tests patch the background worker so the
TestClient's synchronous background execution never reaches the network.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

from api.database import engine, get_db  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Base, User  # noqa: E402
from api.services import concert_scan_service, user_auth_service  # noqa: E402


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
        row = User(email=email, password_hash=user_auth_service.hash_password("secret123"))
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id), row.email


@pytest.fixture()
def user(Session):
    return _make_user(Session, "scans@test.com")


@pytest.fixture()
def other_user(Session):
    return _make_user(Session, "other-scan@test.com")


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
    return {"Authorization": f"Bearer {user_auth_service.create_access_token(user_id, email)}"}


# ── Endpoints ─────────────────────────────────────────────────────────────────

def test_scans_require_auth(client):
    assert client.get("/api/v1/concert-scans/latest").status_code == 401
    assert client.post("/api/v1/concert-scans", json={"url": "https://x"}).status_code == 401


def test_latest_is_null_without_scans(client, user):
    r = client.get("/api/v1/concert-scans/latest", headers=_auth(user))
    assert r.status_code == 200
    assert r.json() == {"scan": None}


def test_start_scan_returns_running_row_and_schedules_worker(client, user):
    with patch.object(concert_scan_service, "run_scan") as worker:
        r = client.post(
            "/api/v1/concert-scans",
            json={"url": "https://example.com/concerts"},
            headers=_auth(user),
        )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "running" and body["source_kind"] == "url"
    assert body["source_url"] == "https://example.com/concerts"
    assert body["items"] == []
    worker.assert_called_once()
    args = worker.call_args.args
    assert args[1] == user[0] and args[2] == "https://example.com/concerts"

    latest = client.get("/api/v1/concert-scans/latest", headers=_auth(user)).json()["scan"]
    assert latest["id"] == body["id"] and latest["status"] == "running"


def test_start_scan_requires_input(client, user):
    r = client.post("/api/v1/concert-scans", json={}, headers=_auth(user))
    assert r.status_code == 422


def test_delete_scan(client, user):
    with patch.object(concert_scan_service, "run_scan"):
        scan = client.post(
            "/api/v1/concert-scans", json={"text": "AC/DC 2026-07-01"}, headers=_auth(user)
        ).json()
    r = client.delete(f"/api/v1/concert-scans/{scan['id']}", headers=_auth(user))
    assert r.json()["deleted"] == 1
    assert client.get("/api/v1/concert-scans/latest", headers=_auth(user)).json()["scan"] is None


def test_scans_are_user_scoped(client, user, other_user, Session):
    with Session() as db:
        mine = concert_scan_service.create_scan(db, user[0], text="mine")
    assert client.get(f"/api/v1/concert-scans/{mine.id}", headers=_auth(other_user)).status_code == 404
    assert client.get("/api/v1/concert-scans/latest", headers=_auth(other_user)).json()["scan"] is None
    assert client.delete(f"/api/v1/concert-scans/{mine.id}", headers=_auth(other_user)).json()["deleted"] == 0


def test_latest_returns_most_recent(client, user, Session):
    with Session() as db:
        concert_scan_service.create_scan(db, user[0], text="first")
        newest = concert_scan_service.create_scan(db, user[0], text="second")
    latest = client.get("/api/v1/concert-scans/latest", headers=_auth(user)).json()["scan"]
    assert latest["id"] == newest.id


# ── Background worker ─────────────────────────────────────────────────────────

def test_run_scan_stores_items_and_streams_progress(Session, user):
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], url="https://example.com/concerts")

    progress: list[str] = []
    with patch("api.services.llm_service.fetch_page_text", return_value="page text") as fetch, \
         patch("api.services.llm_service.extract_concerts", return_value={"concerts": [
             {"artist": "Radiohead", "date": "2026-06-01", "venue": "O2", "url": "https://x/1"},
             {"artist": "---", "date": "", "venue": "", "url": ""},
         ]}) as extract, \
         patch("api.services.openwebui_service.get_user_token", return_value="tok"), \
         patch("api.services.openwebui_service.create_chat", return_value={"id": "chat-1"}), \
         patch("api.services.openwebui_service.append_exchange",
               side_effect=lambda *a, **k: progress.append(a[3])):
        concert_scan_service.run_scan(scan.id, user[0], "https://example.com/concerts", None)

    fetch.assert_called_once()
    # The worker waits far longer than an interactive call for a slow local model.
    assert extract.call_args.kwargs.get("timeout") == concert_scan_service.SCAN_LLM_TIMEOUT
    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.status == "ready" and row.stage == "done"
        assert row.chat_id == "chat-1"
        assert len(row.items) == 2 and row.items[0]["artist"] == "Radiohead"
    assert any("Fetching the page" in p for p in progress)
    assert any("Extracting concerts" in p for p in progress)
    assert any("Found 2 concert" in p for p in progress)


def test_run_scan_text_skips_fetch(Session, user):
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], text="AC/DC 2026-07-01")
    with patch("api.services.llm_service.fetch_page_text") as fetch, \
         patch("api.services.llm_service.extract_concerts", return_value={"concerts": []}), \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], None, "AC/DC 2026-07-01")

    fetch.assert_not_called()
    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.status == "ready" and row.items == []


def test_run_scan_records_error(Session, user):
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], url="https://example.com/x")
    with patch("api.services.llm_service.fetch_page_text", return_value="text"), \
         patch("api.services.llm_service.extract_concerts",
               side_effect=RuntimeError("model exploded")), \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], "https://example.com/x", None)

    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.status == "error" and "model exploded" in row.error
