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

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone

from ..database import SessionLocal
from ..models import ConcertScan, ScanSource, User

logger = logging.getLogger("concert_scans")

# The scan already returned 202 to the client, so the worker can wait much
# longer than an interactive call: a local model can take minutes to answer.
SCAN_LLM_TIMEOUT = (5.0, 900.0)

# Long pages are extracted in overlapping chunks (map) and merged (reduce):
# exhaustive extraction, unlike top-k retrieval which drops events.
CHUNK_CHARS = int(os.getenv("CONCERT_SCAN_CHUNK_CHARS", "24000"))
CHUNK_OVERLAP = int(os.getenv("CONCERT_SCAN_CHUNK_OVERLAP", "1000"))
# Hard ceiling on fetched/stored source text (guards against huge pages).
MAX_SOURCE_CHARS = int(os.getenv("CONCERT_SCAN_MAX_SOURCE_CHARS", "2000000"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split ``text`` into overlapping chunks. Short text -> a single chunk."""
    size = CHUNK_CHARS if size is None else size
    overlap = CHUNK_OVERLAP if overlap is None else overlap
    text = text or ""
    if size <= 0 or len(text) <= size:
        return [text] if text else []
    step = max(1, size - max(0, overlap))
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + size])
        if start + size >= len(text):
            break
        start += step
    return chunks


def _dedupe(items: list[dict]) -> list[dict]:
    """Merge per-chunk results, dropping rows that repeat (artist, date, venue)."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for c in items:
        key = (
            (c.get("artist") or "").strip().lower(),
            (c.get("date") or "").strip(),
            (c.get("venue") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _store_source(db, user_id, *, kind: str, content: str, source_url: str = "") -> ScanSource:
    """Persist the full source text and return its row."""
    content = content or ""
    source = ScanSource(
        user_id=str(user_id),
        id=str(uuid.uuid4()),
        kind=kind,
        source_url=source_url or "",
        content=content,
        sha256=_sha256(content),
        chars=len(content),
    )
    db.add(source)
    db.flush()
    return source


def get_source(db, user_id, source_id: str) -> ScanSource | None:
    if not source_id:
        return None
    return (
        db.query(ScanSource)
        .filter(ScanSource.user_id == str(user_id), ScanSource.id == source_id)
        .first()
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_scan(db, user_id, *, url: str | None = None, text: str | None = None,
                kind: str | None = None) -> ConcertScan:
    url = (url or "").strip()
    text = (text or "").strip()
    is_url = bool(url)
    source_kind = kind or ("url" if is_url else "text")
    source = url if is_url else text[:120]

    scan = ConcertScan(
        user_id=str(user_id),
        id=str(uuid.uuid4()),
        source=source,
        source_url=url,
        source_kind=source_kind,
        status="running",
        stage="queued",
        message="Queued. The scan runs in the background.",
        items=[],
    )

    # Persist the full source now when we already have it (paste or upload).
    # URLs are fetched in the worker, which stores the text after fetching.
    if text:
        if len(text) > MAX_SOURCE_CHARS:
            text = text[:MAX_SOURCE_CHARS]
        row = _store_source(db, user_id, kind=source_kind, content=text, source_url=url)
        scan.source_id = row.id
        scan.source = text[:120]

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
    scan = get_scan(db, user_id, scan_id)
    source_id = scan.source_id if scan is not None else None
    deleted = (
        db.query(ConcertScan)
        .filter(ConcertScan.user_id == str(user_id), ConcertScan.id == scan_id)
        .delete(synchronize_session=False)
    )
    if deleted and source_id:
        db.query(ScanSource).filter(
            ScanSource.user_id == str(user_id), ScanSource.id == source_id
        ).delete(synchronize_session=False)
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
    if scan.source_kind == "file":
        return "Concert scan: uploaded file"
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
            # Prefer the persisted source (paste/upload/previous fetch); fall
            # back to the values the caller passed for old-client compatibility.
            body_text = ""
            if scan.source_id:
                src = get_source(db, user_id, scan.source_id)
                if src is not None:
                    body_text = (src.content or "").strip()
            if not body_text and (text or "").strip():
                body_text = text.strip()
            if (url or "").strip() and not body_text:
                chatter.progress("Fetching the page…")
                scan.stage = "fetching"
                scan.message = "Fetching the page…"
                scan.updated_at = _utcnow()
                db.commit()
                body_text = llm_service.fetch_page_text(
                    url.strip(), max_chars=MAX_SOURCE_CHARS)
                if len(body_text) > MAX_SOURCE_CHARS:
                    body_text = body_text[:MAX_SOURCE_CHARS]
                if body_text and not scan.source_id:
                    row = _store_source(
                        db, user_id, kind="url",
                        content=body_text, source_url=url.strip(),
                    )
                    scan.source_id = row.id

            if not body_text:
                raise llm_service.LLMError("Provide url or text.")

            chunks = _chunk_text(body_text)
            scan.chunk_count = len(chunks)
            scan.updated_at = _utcnow()
            db.commit()

            results: list[dict] = []
            skipped = 0
            for i, chunk in enumerate(chunks, 1):
                if len(chunks) == 1:
                    chatter.progress("Extracting concerts with the model…")
                else:
                    chatter.progress(f"Extracting concerts (chunk {i}/{len(chunks)})…")
                scan.stage = f"extracting {i}/{len(chunks)}"
                scan.message = (
                    "Extracting concerts with the model…"
                    if len(chunks) == 1
                    else f"Extracting concerts (chunk {i} of {len(chunks)})…"
                )
                scan.updated_at = _utcnow()
                db.commit()
                try:
                    data = llm_service.extract_concerts(
                        chunk, token=chatter.token, timeout=SCAN_LLM_TIMEOUT)
                except Exception as chunk_exc:
                    if len(chunks) == 1:
                        raise
                    skipped += 1
                    logger.warning("Concert scan %s chunk %d failed: %s",
                                   scan_id, i, chunk_exc)
                    continue
                results.extend(_normalise(data))

            items = _dedupe(results)

            scan.items = items
            scan.status = "ready"
            scan.stage = "done"
            scan.message = f"Found {len(items)} concert(s)."
            if skipped:
                scan.message += f" {skipped} chunk(s) skipped."
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
