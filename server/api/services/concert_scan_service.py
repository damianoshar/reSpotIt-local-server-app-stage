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
import re
import uuid
from datetime import date, datetime, timezone

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

# '"Fri, Nov 13"' / "March 30, 2027" / "Friday 04 December 2026" style dates
# mark a page that really lists events. Used to detect a degenerate model answer
# (all rows empty, or no rows at all) that the local model occasionally produces
# for such pages. Day-first dates matter: Songkick renders "Friday 04 December
# 2026", and a month-first-only pattern silently disabled the retry there.
_MONTH_DATE_RE = re.compile(
    r"(?:\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
    r"|\b\d{4}-\d{2}-\d{2}\b)",
    re.IGNORECASE,
)


def _looks_like_events(text: str) -> bool:
    return len(_MONTH_DATE_RE.findall(text or "")) >= 3


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


def _roll_past_dates(items: list[dict], today: date | None = None) -> list[dict]:
    """Move year-inference slips into the future ("15 Νοέ" listed in a 2025 page).

    Event pages keep a stale year in their header long after the events roll
    over, and the local model copies it, so a scan in November 2026 came back
    dated 2025. A date that is less than a year in the past is therefore moved
    to its nearest upcoming occurrence. Older dates are left alone: they are
    archive entries, not a year slip.
    """
    today = today or _utcnow().date()
    for item in items:
        raw = (item.get("date") or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        if parsed >= today or (today - parsed).days > 366:
            continue
        candidate = parsed
        for _ in range(8):
            try:
                candidate = candidate.replace(year=candidate.year + 1)
            except ValueError:  # 29 February
                candidate = candidate.replace(year=candidate.year + 1, day=28)
            if candidate >= today:
                break
        item["date"] = candidate.isoformat()
    return items


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


def fail_orphaned_scans(db=None) -> int:
    """Mark scans left "running"/"queued" by a previous process as failed.

    Scan workers live in the API process, so a restart (deploy, crash) leaves
    their rows ``running`` with no worker left to finish them. Clients poll
    ``/latest`` and would show "Scanning..." forever.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        orphans = (
            db.query(ConcertScan)
            .filter(ConcertScan.status.in_(("running", "queued")))
            .all()
        )
        now = _utcnow()
        for scan in orphans:
            scan.status = "error"
            scan.stage = "done"
            scan.error = "Interrupted by a server restart. Start the scan again."
            scan.message = "Scan failed."
            scan.updated_at = now
        if orphans:
            db.commit()
        return len(orphans)
    finally:
        if own_session:
            db.close()


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
    """Streams scan progress into a per-user Open WebUI chat (best-effort).

    The chat holds one turn: the request as the user message and the whole
    progress log as the assistant message. Open WebUI renders one assistant
    bubble per turn, so appending to that bubble keeps the scan readable
    instead of opening a new turn for every update.
    """

    def __init__(self, user: User | None, title: str, prompt: str = ""):
        self.token: str | None = None
        self.chat_id: str = ""
        self.model: str = ""
        self.prompt: str = prompt or title
        self._started = False
        if user is None:
            return
        from . import openwebui_service
        try:
            token = openwebui_service.get_user_token(user)
            self.model = openwebui_service.resolve_model_id(token)
            row = openwebui_service.create_chat(
                token, title=title[:200] or "Concert scan",
                model=self.model,
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
            if not self._started:
                # First update opens the turn: the request plus what is known.
                self._started = True
                openwebui_service.append_exchange(
                    self.token, self.chat_id, self.prompt, text,
                    model=self.model or None,
                )
                return
            openwebui_service.append_assistant_text(
                self.token, self.chat_id, text, model=self.model or None,
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
    if scan.source_kind in ("url", "page") and scan.source_url:
        return f"Concert scan: {scan.source_url}"
    if scan.source_kind == "file":
        return "Concert scan: uploaded file"
    return "Concert scan: pasted text"


def _prompt_for(scan: ConcertScan) -> str:
    """The request the chat shows as the user message."""
    if scan.source_kind in ("url", "page") and scan.source_url:
        return f"Find the concerts listed on {scan.source_url}"
    if scan.source_kind == "file":
        return "Find the concerts listed in the uploaded file"
    return "Find the concerts listed in the pasted text"


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
        chatter = _Chatter(user, _title_for(scan), _prompt_for(scan))
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
                    chunk_items = _normalise(data)
                    # The local model occasionally answers {"concerts": []} for a
                    # page full of dated events (seen finishing in ~1 second).
                    # Ask once more before reporting "no concerts".
                    if not chunk_items and _looks_like_events(chunk):
                        logger.warning(
                            "Concert scan %s chunk %d returned no concerts for "
                            "event-like text; retrying", scan_id, i)
                        data = llm_service.extract_concerts(
                            chunk, token=chatter.token, timeout=SCAN_LLM_TIMEOUT,
                            mode="empty")
                        chunk_items = _normalise(data)
                    # Same for undated rows: the calendar needs dates, so retry
                    # once when the text has dates but no row carries one.
                    if (chunk_items
                            and not any(item["date"] for item in chunk_items)
                            and _looks_like_events(chunk)):
                        logger.warning(
                            "Concert scan %s chunk %d returned undated rows; "
                            "retrying for dates", scan_id, i)
                        data = llm_service.extract_concerts(
                            chunk, token=chatter.token, timeout=SCAN_LLM_TIMEOUT,
                            mode="dates")
                        dated = _normalise(data)
                        if any(item["date"] for item in dated):
                            chunk_items = dated
                except Exception as chunk_exc:
                    if len(chunks) == 1:
                        raise
                    skipped += 1
                    logger.warning("Concert scan %s chunk %d failed: %s",
                                   scan_id, i, chunk_exc)
                    continue
                results.extend(chunk_items)

            items = _roll_past_dates(_dedupe(results))

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
