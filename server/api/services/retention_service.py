"""
services/retention_service.py
----------------------------
Shortlived-playlist retention. Dialect-agnostic (Postgres + SQLite).
"""

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..database import SessionLocal, is_sqlite
from ..models import PlaylistRetention
from ..scoping import as_uuid

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")

_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    from .db_service import run_migrations, wait_for_db
    wait_for_db(DATABASE_URL)
    if not is_sqlite():
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        try:
            run_migrations(conn, MIGRATIONS_DIR)
        finally:
            conn.close()
    _schema_ready = True


def set_retention(playlist_spotify_id: str, expires_at, user_id: str):
    _ensure_schema()
    owner = str(as_uuid(user_id))
    with SessionLocal() as db:
        row = db.query(PlaylistRetention).filter(
            PlaylistRetention.user_id == owner,
            PlaylistRetention.playlist_spotify_id == playlist_spotify_id,
        ).first()
        if row:
            row.expires_at = expires_at
            row.keep_forever = False
            row.last_error = None
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(PlaylistRetention(
                user_id=owner,
                playlist_spotify_id=playlist_spotify_id,
                expires_at=expires_at,
                keep_forever=False,
            ))
        db.commit()


def clear_retention(playlist_spotify_id: str, user_id: str) -> bool:
    _ensure_schema()
    owner = str(as_uuid(user_id))
    with SessionLocal() as db:
        n = db.query(PlaylistRetention).filter(
            PlaylistRetention.playlist_spotify_id == playlist_spotify_id,
            PlaylistRetention.user_id == owner,
        ).delete()
        db.commit()
        return n > 0


def list_retention(user_id: str) -> list[dict]:
    _ensure_schema()
    owner = str(as_uuid(user_id))
    with SessionLocal() as db:
        rows = db.query(PlaylistRetention).filter(
            PlaylistRetention.user_id == owner,
        ).order_by(PlaylistRetention.expires_at).all()
    return [
        {"playlist_spotify_id": r.playlist_spotify_id,
         "expires_at": r.expires_at,
         "keep_forever": r.keep_forever,
         "last_error": r.last_error}
        for r in rows
    ]


def due_for_deletion() -> list[dict]:
    _ensure_schema()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        rows = db.query(PlaylistRetention).filter(
            PlaylistRetention.keep_forever == False,  # noqa: E712
            PlaylistRetention.expires_at <= now,
        ).order_by(PlaylistRetention.user_id, PlaylistRetention.expires_at).all()
    return [{"user_id": r.user_id, "playlist_spotify_id": r.playlist_spotify_id} for r in rows]


def mark_error(playlist_spotify_id: str, message: str, user_id: str, retry_minutes: int = 15):
    _ensure_schema()
    owner = str(as_uuid(user_id))
    with SessionLocal() as db:
        row = db.query(PlaylistRetention).filter(
            PlaylistRetention.playlist_spotify_id == playlist_spotify_id,
            PlaylistRetention.user_id == owner,
        ).first()
        if row:
            row.last_error = message[:500]
            row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=retry_minutes)
            row.updated_at = datetime.now(timezone.utc)
            db.commit()


def sweep_expired() -> dict:
    from .auth_service import get_valid_token, is_authenticated
    from .spotify_actions import unfollow_playlist

    deleted = deferred = 0
    for row in due_for_deletion():
        user_id = row["user_id"]
        playlist_id = row["playlist_spotify_id"]

        if not is_authenticated(user_id):
            deferred += 1
            continue

        try:
            token = get_valid_token(user_id)
            unfollow_playlist(token, playlist_id)
            clear_retention(playlist_id, user_id)
            try:
                from .playlist_cache import delete_playlist_cache
                delete_playlist_cache(playlist_id, user_id)
            except Exception:
                pass
            deleted += 1
        except Exception as e:
            mark_error(playlist_id, str(e), user_id)
            deferred += 1
    return {"deleted": deleted, "deferred": deferred}


def as_utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value