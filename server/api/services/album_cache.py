"""
services/album_cache.py
-----------------------
Cached album track lists. Dialect-agnostic (Postgres + SQLite).
"""

import os
from sqlalchemy.orm import Session

from ..database import SessionLocal, is_sqlite
from ..models import AlbumTrack
from ..scoping import as_uuid

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")

_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    from .db_service import run_migrations, wait_for_db, MIGRATIONS_DIR as MD
    wait_for_db(DATABASE_URL)
    # on sqlite, run_migrations is a no-op that creates schema
    # on postgres, run migrations via psycopg2 (handled in db_service)
    if not is_sqlite():
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        try:
            run_migrations(conn, MD)
        finally:
            conn.close()
    _schema_ready = True


def get_album_tracks(album_spotify_id: str, user_id: str) -> list[dict]:
    _ensure_schema()
    owner = str(as_uuid(user_id))
    with SessionLocal() as db:
        rows = db.query(AlbumTrack).filter(
            AlbumTrack.user_id == owner,
            AlbumTrack.album_spotify_id == album_spotify_id,
        ).order_by(AlbumTrack.disc_number, AlbumTrack.track_number).all()
    return [
        {
            "spotify_id": r.track_spotify_id,
            "name": r.name,
            "artist_names": r.artist_names,
            "disc_number": r.disc_number,
            "track_number": r.track_number,
            "duration_ms": r.duration_ms,
            "uri": r.uri,
            "explicit": r.explicit,
            "preview_url": r.preview_url,
            "album_name": r.album_name,
            "album_image_url": r.album_image_url,
            "release_year": r.release_year,
        }
        for r in rows
    ]


def replace_album_tracks(album_spotify_id: str, tracks: list[dict], user_id: str) -> int:
    _ensure_schema()
    owner = str(as_uuid(user_id))
    rows = [
        t for t in tracks
        if t.get("spotify_id") or t.get("track_spotify_id")
    ]
    with SessionLocal() as db:
        db.query(AlbumTrack).filter(
            AlbumTrack.user_id == owner,
            AlbumTrack.album_spotify_id == album_spotify_id,
        ).delete()
        for t in rows:
            db.add(AlbumTrack(
                user_id=owner,
                album_spotify_id=album_spotify_id,
                track_spotify_id=t.get("spotify_id") or t.get("track_spotify_id"),
                name=t.get("name", ""),
                artist_names=t.get("artist_names", ""),
                disc_number=t.get("disc_number"),
                track_number=t.get("track_number"),
                duration_ms=t.get("duration_ms"),
                uri=t.get("uri"),
                explicit=bool(t.get("explicit", False)),
                preview_url=t.get("preview_url"),
                album_name=t.get("album_name", ""),
                album_image_url=t.get("album_image_url"),
                release_year=t.get("release_year"),
            ))
        db.commit()
    return len(rows)


def cached_album_ids(album_ids: list[str], user_id: str) -> set[str]:
    if not album_ids:
        return set()
    _ensure_schema()
    owner = str(as_uuid(user_id))
    with SessionLocal() as db:
        rows = db.query(AlbumTrack.album_spotify_id).filter(
            AlbumTrack.user_id == owner,
            AlbumTrack.album_spotify_id.in_(album_ids),
        ).distinct().all()
    return {r[0] for r in rows}