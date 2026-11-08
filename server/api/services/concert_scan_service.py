"""
services/concert_scan_service.py
--------------------------------
Click-and-forget AI concert scans.

A scan is created instantly (``create_scan``) and processed later in the
background (``run_scan``): progress is streamed into an Open WebUI chat with
``chat_type=extract_concerts`` and the extracted rows are stored on the scan
row. Clients render a ready scan as a *pending review list* -- nothing enters
the server-canonical ``concerts`` store until the user saves the selection.

The Open WebUI chat is best-effort: if trusted auth is off or Open WebUI is
unreachable, the scan still completes and the results still wait on the row.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from ..database import SessionLocal
from ..models import ConcertScan, User

logger = logging.getLogger("concert_scans")

# The scan already returned 202 to the client, so the worker can wait much
# longer than an interactive call: a local model can take minutes to answer.
SCAN_LLM_TIMEOUT = (5.0, 900.0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_scan(db, user_id, *, url: str | None = None, text: str | None = None) -> ConcertScan:
    url = (url or "").strip()
    text = (text or "").strip()
    is_url = bool(url)
    source = url if is_url else text[:120]
    scan = ConcertScan(
        user_id=str(user_id),
        id=str(uuid.uuid4()),
        source=source,
        source_url=url,
        source_kind="url" if is_url else "text",
        status="running",
        stage="queued",
        message="Queued. The scan runs in the background.",
        items=[],
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def get_scan(db, user_id, scan_id: str) -> ConcertScan | None:
    return (
        db.query(ConcertScan)
        .filter(ConcertScan.user_id == str(user_id), ConcertScan.id == scan_id)
        .first()
    )


def latest_scan(db, user_id) -> ConcertScan | None:
    return (
        db.query(ConcertScan)
        .filter(ConcertScan.user_id == str(user_id))
        .order_by(ConcertScan.created_at.desc())
        .first()
    )


def delete_scan(db, user_id, scan_id: str) -> int:
    deleted = (
        db.query(ConcertScan)
        .filter(ConcertScan.user_id == str(user_id), ConcertScan.id == scan_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


# ── Background worker ─────────────────────────────────────────────────────────

class _Chatter:
    """Streams scan progress into a per-user Open WebUI chat (best-effort)."""

    def __init__(self, user: User | None, title: str):
        self.token: str | None = None
        self.chat_id: str = ""
        if user is None:
            return
        from . import openwebui_service
        try:
            token = openwebui_service.get_user_token(user)
            row = openwebui_service.create_chat(
                token, title=title[:200] or "Concert scan",
                chat_type="extract_concerts",
            )
            self.token = token
            self.chat_id = str(row.get("id") or "")
        except Exception as exc:  # chat is optional; never fail the scan for it
            logger.info("Concert scan chat unavailable: %s", exc)

    def _append(self, text: str) -> None:
        if not self.chat_id:
            return
        from . import openwebui_service
        try:
            openwebui_service.append_exchange(
                self.token, self.chat_id, "Progress", text, title=None,
            )
        except Exception as exc:
            logger.info("Concert scan progress write failed: %s", exc)

    def progress(self, text: str) -> None:
        self._append(text)

    def finish(self, items: list[dict]) -> None:
        if not items:
            self._append("Scan finished: no concerts found on the page.")
            return
        lines = [
            f"Scan finished. Found {len(items)} concert(s):",
            "",
        ]
        for c in items[:100]:
            bits = [c.get("artist") or "?"]
            if c.get("date"):
                bits.append(c["date"])
            if c.get("venue"):
                bits.append("at " + c["venue"])
            lines.append("- " + " — ".join(bits))
        self._append("\n".join(lines))

    def fail(self, exc: Exception) -> None:
        self._append(f"Scan failed: {exc}")


def _normalise(data: dict) -> list[dict]:
    rows = data.get("concerts") if isinstance(data, dict) else None
    out: list[dict] = []
    for c in rows or []:
        if isinstance(c, dict):
            out.append({
                "artist": str(c.get("artist") or "").strip(),
                "date":   str(c.get("date") or "").strip(),
                "venue":  str(c.get("venue") or "").strip(),
                "url":    str(c.get("url") or "").strip(),
            })
    return out


def _title_for(scan: ConcertScan) -> str:
    if scan.source_kind == "url" and scan.source_url:
        return f"Concert scan: {scan.source_url}"
    return "Concert scan: pasted text"


def run_scan(scan_id: str, user_id: str, url: str | None, text: str | None) -> None:
    """Background entry point: extract concerts and stream progress.

    Runs with its own DB session (the request session is closed by the time a
    Starlette background task executes).
    """
    from . import llm_service

    if SessionLocal is None:  # pragma: no cover - DB not configured
        logger.warning("Concert scan skipped: DATABASE_URL is not configured.")
        return

    db = SessionLocal()
    try:
        scan = get_scan(db, user_id, scan_id)
        if scan is None:
            return
        user = db.query(User).filter(User.id == str(user_id)).first()
        chatter = _Chatter(user, _title_for(scan))
        if chatter.chat_id:
            scan.chat_id = chatter.chat_id
            scan.updated_at = _utcnow()
            db.commit()

        try:
            body_text = (text or "").strip()
            if (url or "").strip():
                chatter.progress("Fetching the page…")
                scan.stage = "fetching"
                scan.message = "Fetching the page…"
                scan.updated_at = _utcnow()
                db.commit()
                body_text = llm_service.fetch_page_text(url.strip(), max_chars=6000)

            if not body_text:
                raise llm_service.LLMError("Provide url or text.")

            chatter.progress("Extracting concerts with the model…")
            scan.stage = "extracting"
            scan.message = "Extracting concerts with the model…"
            scan.updated_at = _utcnow()
            db.commit()

            data = llm_service.extract_concerts(body_text, token=chatter.token,
                                                timeout=SCAN_LLM_TIMEOUT)
            items = _normalise(data)

            scan.items = items
            scan.status = "ready"
            scan.stage = "done"
            scan.message = f"Found {len(items)} concert(s)."
            scan.error = ""
            scan.updated_at = _utcnow()
            db.commit()
            chatter.finish(items)
        except Exception as exc:
            logger.warning("Concert scan %s failed: %s", scan_id, exc)
            scan.status = "error"
            scan.stage = "done"
            scan.error = str(exc)
            scan.message = "Scan failed."
            scan.updated_at = _utcnow()
            db.commit()
            chatter.fail(exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Concert scan worker error: %s", exc)
    finally:
        db.close()
