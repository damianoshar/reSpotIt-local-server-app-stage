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
from api.models import Base, ScanSource, User  # noqa: E402
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


# ── Source persistence + chunking ─────────────────────────────────────────────

def test_create_scan_persists_full_source(Session, user):
    text = ("Radiohead at the O2 " * 200).strip()
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], text=text)
        assert scan.source_id
        assert scan.source == text[:120]
        src = concert_scan_service.get_source(db, user[0], scan.source_id)
        assert src is not None
        assert src.content == text and src.chars == len(text)
        assert src.sha256 == concert_scan_service._sha256(text)
        assert src.kind == "text"


def test_delete_scan_removes_linked_source(Session, user):
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], text="AC/DC 2026-07-01")
        source_id = scan.source_id
    with Session() as db:
        assert concert_scan_service.delete_scan(db, user[0], scan.id) == 1
        assert concert_scan_service.get_source(db, user[0], source_id) is None


def test_chunk_text_overlaps_and_covers():
    text = "x" * 100
    chunks = concert_scan_service._chunk_text(text, size=40, overlap=10)
    assert len(chunks) == 3
    assert all(len(c) <= 40 for c in chunks)
    # Overlap means the joined coverage extends past the source.
    assert chunks[0][-10:] == chunks[1][:10]


def test_chunk_text_short_is_single():
    assert concert_scan_service._chunk_text("short", size=40, overlap=10) == ["short"]
    assert concert_scan_service._chunk_text("", size=40, overlap=10) == []


def test_dedupe_merges_repeats():
    items = [
        {"artist": "Radiohead", "date": "2026-06-01", "venue": "O2", "url": ""},
        {"artist": "radiohead", "date": "2026-06-01", "venue": "o2", "url": "https://x"},
        {"artist": "Portishead", "date": "2026-06-02", "venue": "Brixton", "url": ""},
    ]
    out = concert_scan_service._dedupe(items)
    assert len(out) == 2
    assert out[0]["artist"] == "Radiohead" and out[1]["artist"] == "Portishead"


def test_run_scan_chunks_and_dedupes(Session, user):
    # Three chunks worth of text, one extract call per chunk.
    text = "Radiohead O2 2026-06-01 ".ljust(60000, "x")
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], text=text)

    calls = []
    def fake_extract(chunk, **kwargs):
        calls.append(chunk)
        return {"concerts": [
            {"artist": "Radiohead", "date": "2026-06-01", "venue": "O2", "url": ""},
        ]}

    with patch("api.services.llm_service.extract_concerts", side_effect=fake_extract), \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], None, None)

    assert len(calls) >= 2
    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.status == "ready"
        assert row.chunk_count == len(calls)
        # Every chunk returned the same concert; dedupe leaves one.
        assert len(row.items) == 1


def test_run_scan_stores_fetched_url_source(Session, user):
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], url="https://example.com/c")
    with patch("api.services.llm_service.fetch_page_text", return_value="page text"), \
         patch("api.services.llm_service.extract_concerts", return_value={"concerts": []}), \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], "https://example.com/c", None)
    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.source_id
        src = concert_scan_service.get_source(db, user[0], row.source_id)
        assert src.content == "page text" and src.kind == "url"


def test_run_scan_skips_failed_chunk(Session, user):
    text = "Radiohead O2 2026-06-01 ".ljust(60000, "x")
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], text=text)

    state = {"n": 0}
    def flaky(chunk, **kwargs):
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("chunk exploded")
        return {"concerts": [
            {"artist": "Radiohead", "date": "2026-06-01", "venue": "O2", "url": ""},
        ]}

    with patch("api.services.llm_service.extract_concerts", side_effect=flaky), \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], None, None)

    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.status == "ready" and "skipped" in row.message
        assert len(row.items) == 1


def test_upload_scan_creates_file_scan(client, user, Session):
    with patch.object(concert_scan_service, "run_scan") as worker:
        r = client.post(
            "/api/v1/concert-scans/upload",
            files={"file": ("concerts.html", b"<html><body><b>Radiohead</b> O2</body></html>", "text/html")},
            headers=_auth(user),
        )
    assert r.status_code == 202
    body = r.json()
    assert body["source_kind"] == "file"
    assert body["source_id"]
    with Session() as db:
        src = concert_scan_service.get_source(db, user[0], body["source_id"])
        # HTML is stripped to text before storing.
        assert "<b>" not in src.content and "Radiohead" in src.content
    worker.assert_called_once()


def test_upload_scan_with_source_url_records_a_page_snapshot(client, user, Session):
    """A WebView snapshot uploads text but keeps the page URL it came from."""
    with patch.object(concert_scan_service, "run_scan") as worker:
        r = client.post(
            "/api/v1/concert-scans/upload",
            files={"file": ("page-snapshot.txt", b"Napalm Death 2026-07-01 Gagarin", "text/plain")},
            data={"source_url": "https://www.bandsintown.com/c/athens"},
            headers=_auth(user),
        )
    assert r.status_code == 202
    body = r.json()
    assert body["source_kind"] == "page"
    assert body["source_url"] == "https://www.bandsintown.com/c/athens"
    with Session() as db:
        src = concert_scan_service.get_source(db, user[0], body["source_id"])
        assert "Napalm Death" in src.content
        assert src.source_url == "https://www.bandsintown.com/c/athens"
    # The client already rendered the page: the worker must not re-fetch it.
    args = worker.call_args.args
    assert args[2] is None and args[3] is None


def test_upload_scan_with_bad_source_url_falls_back_to_a_file_scan(client, user):
    with patch.object(concert_scan_service, "run_scan"):
        r = client.post(
            "/api/v1/concert-scans/upload",
            files={"file": ("concerts.txt", b"Radiohead O2", "text/plain")},
            data={"source_url": "not a url"},
            headers=_auth(user),
        )
    assert r.status_code == 202
    body = r.json()
    assert body["source_kind"] == "file"
    assert body["source_url"] == ""


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


# ── Degenerate-answer retries ─────────────────────────────────────────────────

_EVENT_PAGE = (
    "Sólstafir\nFri, Nov 13 • 9 PM\nEightball Club\n"
    "Whiplash\nSat, Nov 14 • 8 PM\nEightball Club\n"
    "Kovacs\nSun, Nov 15 • 9 PM\nWE\n"
)


def test_looks_like_events_detects_dated_pages():
    assert concert_scan_service._looks_like_events(_EVENT_PAGE) is True
    assert concert_scan_service._looks_like_events("no dates here at all") is False
    assert concert_scan_service._looks_like_events("") is False


_DAY_FIRST_PAGE = (
    "Friday 04 December 2026\n\nKovacs\n\nWE, Thessaloníki, Greece\n\n"
    "Sunday 06 December 2026\n\nNouvelle Vague\n\nWE, Thessaloníki, Greece\n\n"
    "Monday 01 February 2027\n\nAndrea Vanzo\n\nRoyal Theatre\n"
)


def test_looks_like_events_detects_day_first_and_iso_dates():
    # Songkick renders day-first dates ("Friday 04 December 2026"). A
    # month-first-only pattern missed them, so a page full of events skipped the
    # empty-answer retry and the scan finished with 0 concerts.
    assert concert_scan_service._looks_like_events(_DAY_FIRST_PAGE) is True
    iso = "2026-12-04 Gagarin 205\n2026-12-05 Fuzz Club\n2026-12-10 Kyttaro"
    assert concert_scan_service._looks_like_events(iso) is True


def test_run_scan_retries_empty_answer_for_event_page(Session, user):
    """An empty list on an obviously dated page is retried once with a nudge."""
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], url="https://example.com/events")

    empty = {"concerts": []}
    filled = {"concerts": [
        {"artist": "Sólstafir", "date": "2026-11-13", "venue": "Eightball Club", "url": ""},
    ]}
    with patch("api.services.llm_service.fetch_page_text", return_value=_EVENT_PAGE), \
         patch("api.services.llm_service.extract_concerts",
               side_effect=[empty, filled]) as extract, \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], "https://example.com/events", None)

    assert extract.call_count == 2
    assert extract.call_args.kwargs.get("mode") == "empty"
    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.status == "ready"
        assert [i["artist"] for i in row.items] == ["Sólstafir"]


def test_run_scan_does_not_retry_empty_answer_without_events(Session, user):
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], url="https://example.com/blog")

    with patch("api.services.llm_service.fetch_page_text",
               return_value="A blog post with no events whatsoever."), \
         patch("api.services.llm_service.extract_concerts",
               return_value={"concerts": []}) as extract, \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], "https://example.com/blog", None)

    assert extract.call_count == 1
    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.status == "ready" and row.items == []


def test_run_scan_retries_undated_rows(Session, user):
    """Rows without any date are retried once so the calendar stays usable."""
    with Session() as db:
        scan = concert_scan_service.create_scan(db, user[0], url="https://example.com/events")

    undated = {"concerts": [
        {"artist": "Sólstafir", "date": "", "venue": "Eightball Club", "url": ""},
    ]}
    dated = {"concerts": [
        {"artist": "Sólstafir", "date": "2026-11-13", "venue": "Eightball Club", "url": ""},
    ]}
    with patch("api.services.llm_service.fetch_page_text", return_value=_EVENT_PAGE), \
         patch("api.services.llm_service.extract_concerts",
               side_effect=[undated, dated]) as extract, \
         patch("api.services.openwebui_service.get_user_token", return_value=None), \
         patch("api.services.openwebui_service.create_chat", side_effect=RuntimeError("no chat")):
        concert_scan_service.run_scan(scan.id, user[0], "https://example.com/events", None)

    assert extract.call_count == 2
    assert extract.call_args.kwargs.get("mode") == "dates"
    with Session() as db:
        row = concert_scan_service.get_scan(db, user[0], scan.id)
        assert row.items[0]["date"] == "2026-11-13"


# ── Compact output + prompt-cache-friendly retries ────────────────────────────

def test_extract_concerts_parses_compact_arrays():
    """Rows come back as [artist, date, venue] arrays to cut generated tokens."""
    from api.services import llm_service

    with patch("api.services.llm_service.extract_structured",
               return_value={"concerts": [
                   ["Sólstafir", "2026-11-13", "Eightball Club"],
                   ["Kovacs"],
                   {"artist": "Whiplash", "date": "", "venue": "Soul", "url": "u"},
               ]}) as es:
        out = llm_service.extract_concerts("page text")

    rows = out["concerts"]
    assert rows[0] == {"artist": "Sólstafir", "date": "2026-11-13",
                       "venue": "Eightball Club", "url": ""}
    assert rows[1]["artist"] == "Kovacs" and rows[1]["date"] == "" and rows[1]["venue"] == ""
    # Legacy object rows (and a url) still parse.
    assert rows[2]["url"] == "u"

    system = es.call_args.args[0]
    assert "ARRAY" in system and '"url"' not in system


def test_extract_concerts_nudge_keeps_system_prompt_cached():
    """Retries must not rewrite the system prompt, or llama.cpp re-reads the page."""
    from api.services import llm_service

    base = llm_service._CONCERTS_SYSTEM
    for mode in ("empty", "dates"):
        with patch("api.services.llm_service.extract_structured",
                   return_value={"concerts": []}) as es:
            llm_service.extract_concerts("PAGE", mode=mode)
        assert es.call_args.args[0] == base, "system prompt changed; cache lost"
        prompt = es.call_args.args[1]
        assert prompt.startswith("PAGE") and len(prompt) > len("PAGE")

    with patch("api.services.llm_service.extract_structured",
               return_value={"concerts": []}) as es:
        llm_service.extract_concerts("PAGE")
    assert es.call_args.args[1] == "PAGE", "no-mode call must pass the text unchanged"


def test_fail_orphaned_scans_marks_running_as_error(Session, user):
    """Scans left running by a restart must not hang clients on /latest."""
    with Session() as db:
        running = concert_scan_service.create_scan(db, user[0], text="x")
        done = concert_scan_service.create_scan(db, user[0], text="y")
        done.status = "ready"
        done.stage = "done"
        db.commit()
        running_id, done_id = running.id, done.id

    with Session() as db:
        # Other tests in this module leave running rows behind too.
        assert concert_scan_service.fail_orphaned_scans(db) >= 1

    with Session() as db:
        failed = concert_scan_service.get_scan(db, user[0], running_id)
        assert failed.status == "error" and "restart" in failed.error
        assert concert_scan_service.get_scan(db, user[0], done_id).status == "ready"

    # Idempotent: nothing left to fail on the next startup.
    with Session() as db:
        assert concert_scan_service.fail_orphaned_scans(db) == 0
