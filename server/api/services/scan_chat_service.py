"""
services/scan_chat_service.py
-----------------------------
Records an AI album/track scan in the user's Open WebUI chat history.

The scan routes (``POST /api/v1/llm/extract-albums`` and ``/extract-tracks``)
answer with the extracted rows only. Without a chat the scan left no trace in
Open WebUI, so the user could not see what the model was asked or what it
answered.

This module writes that trace. Every scan becomes one turn in one chat:

  * the user message is the request ("Find the albums listed on <url>"),
  * the assistant message is what the model produced ("Scan finished.
    Found N album(s): ...").

One turn, not many: Open WebUI renders one assistant bubble per turn, and a
chat whose user message names exactly one model is the only shape it renders
(see ``openwebui_service.append_exchange``).

The chat is best-effort. When Open WebUI is unreachable, trusted auth is off
or the model list is empty, the scan still answers normally - only the chat
history is missing.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("scan_chats")

# How many rows the assistant message lists. A page can hold hundreds of
# albums; the chat stays readable with a cap.
MAX_LISTED = 100

ALBUM_KIND = "extract_albums"
TRACK_KIND = "extract_tracks"


def _clean(value) -> str:
    return str(value or "").strip()


def _line(row: dict, title_key: str) -> str:
    title = _clean(row.get(title_key))
    artist = _clean(row.get("artist"))
    if title and artist:
        return f"- {title} — {artist}"
    return f"- {title or artist or '?'}"


def _title_for(kind: str, source: str | None) -> str:
    label = "Album" if kind == ALBUM_KIND else "Track"
    if source:
        return f"{label} scan: {source}"[:200]
    return f"{label} scan: pasted text"


def _prompt_for(kind: str, source: str | None) -> str:
    noun = "albums" if kind == ALBUM_KIND else "tracks"
    if source:
        return f"Find the {noun} listed on {source}"
    return f"Find the {noun} listed in the pasted text"


def _summary(kind: str, rows: list[dict]) -> str:
    noun = "album" if kind == ALBUM_KIND else "track"
    title_key = "album" if kind == ALBUM_KIND else "title"
    if not rows:
        return f"Scan finished: no {noun}s found on the page."
    lines = [f"Scan finished. Found {len(rows)} {noun}(s):", ""]
    for row in rows[:MAX_LISTED]:
        lines.append(_line(row, title_key))
    if len(rows) > MAX_LISTED:
        lines.append(f"… and {len(rows) - MAX_LISTED} more.")
    return "\n".join(lines)


def record_scan(user, *, kind: str, source: str | None, rows: list[dict]) -> str | None:
    """Write the scan into a fresh Open WebUI chat. Returns the chat id.

    ``source`` is the page URL the user scanned (None for pasted text).
    ``rows`` are the extracted rows: ``{artist, album}`` for an album scan,
    ``{artist, title}`` for a track scan.

    Never raises: a missing chat must not fail the scan.
    """
    if user is None:
        return None
    from . import openwebui_service

    try:
        token = openwebui_service.get_user_token(user)
        model = openwebui_service.resolve_model_id(token)
        row = openwebui_service.create_chat(
            token,
            title=_title_for(kind, source),
            model=model,
            chat_type=kind,
        )
        chat_id = str(row.get("id") or "")
        if not chat_id:
            return None
        openwebui_service.append_exchange(
            token,
            chat_id,
            _prompt_for(kind, source),
            _summary(kind, rows),
            model=model,
        )
        return chat_id
    except Exception as exc:  # noqa: BLE001 - the chat is optional
        logger.info("Scan chat unavailable for %s: %s", kind, exc)
        return None
