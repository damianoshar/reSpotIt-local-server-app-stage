"""
services/db_service.py
-----------------------
Runs SQL migrations and bulk-upserts albums + artists from the CSV into Postgres.
"""

import csv
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import psycopg2
import psycopg2.extras

from ..scoping import as_uuid

MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")

def _ensure_sqlite_schema():
    try:
        from ..database import engine, is_sqlite
        from ..models import Base
        if is_sqlite() and engine is not None:
            Base.metadata.create_all(bind=engine)
    except Exception:
        pass




# ── Helpers ───────────────────────────────────────────────────────────────────

def wait_for_db(dsn: str, retries: int = 10, delay: float = 3.0):
    if dsn.startswith("sqlite"):
        _ensure_sqlite_schema()
        return
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(dsn)
            conn.close()
            return
        except psycopg2.OperationalError as e:
            if attempt == retries:
                raise RuntimeError(f"Could not connect to Postgres after {retries} attempts: {e}")
            time.sleep(delay)


def run_migrations(conn, migrations_dir: str = MIGRATIONS_DIR) -> int:
    try:
        from ..database import is_sqlite
        if is_sqlite():
            _ensure_sqlite_schema()
            return 0
    except Exception:
        pass
    """Apply unapplied .sql files once each, tracked in schema_migrations.

    Existing installations already ran 001-008 before tracking existed; those
    files are idempotent, so the first run of this tracker re-applies them and
    records them. Each file is committed independently: a failure rolls back
    only that file, and it remains pending for the next start.
    """
    sql_files = sorted(Path(migrations_dir).glob("*.sql"))
    with conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   filename   TEXT PRIMARY KEY,
                   applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

    applied_count = 0
    for path in sql_files:
        if path.name in applied:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(path.read_text())
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
                    (path.name,),
                )
            conn.commit()
            applied_count += 1
        except Exception:
            conn.rollback()
            raise
    return applied_count


def _parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(value) -> int | None:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_list(value: str) -> list[str]:
    if not value or not value.strip():
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


# ── Main loader ───────────────────────────────────────────────────────────────

def load_csv_to_db(
    dsn: str,
    csv_path: str,
    migrations_dir: str = MIGRATIONS_DIR,
    progress_cb: Callable | None = None,
    user_id: str | None = None,
) -> dict:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    if not user_id:
        raise ValueError("user_id is required for per-user loading")
    owner = as_uuid(user_id)

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return {"inserted": 0, "updated": 0, "skipped": 0, "total": 0}

    wait_for_db(dsn)
    conn = psycopg2.connect(dsn)
    psycopg2.extras.register_uuid()

    migrations_applied = run_migrations(conn, migrations_dir)

    total = len(rows)
    inserted = updated = skipped = 0

    with conn.cursor() as cur:
        for i, row in enumerate(rows, 1):
            spotify_id = row.get("album_id", "").strip()
            if not spotify_id:
                skipped += 1
                continue

            name = row.get("name", "").strip() or "Unknown"

            # ── Upsert album ────────────────────────────────────────────────
            cur.execute(
                """
                INSERT INTO albums (
                    user_id, spotify_id, name, release_date, total_tracks, album_type,
                    label, popularity, genres, spotify_url, image_url, image_file, added_at
                ) VALUES (
                    %(user_id)s, %(spotify_id)s, %(name)s, %(release_date)s, %(total_tracks)s,
                    %(album_type)s, %(label)s, %(popularity)s, %(genres)s,
                    %(spotify_url)s, %(image_url)s, %(image_file)s, %(added_at)s
                )
                ON CONFLICT (user_id, spotify_id) DO UPDATE SET
                    name         = EXCLUDED.name,
                    release_date = EXCLUDED.release_date,
                    total_tracks = EXCLUDED.total_tracks,
                    album_type   = EXCLUDED.album_type,
                    label        = EXCLUDED.label,
                    popularity   = EXCLUDED.popularity,
                    genres       = EXCLUDED.genres,
                    spotify_url  = EXCLUDED.spotify_url,
                    image_url    = EXCLUDED.image_url,
                    image_file   = EXCLUDED.image_file,
                    added_at     = EXCLUDED.added_at
                RETURNING id, (xmax = 0) AS was_inserted
                """,
                {
                    "user_id":      owner,
                    "spotify_id":   spotify_id,
                    "name":         name,
                    "release_date": _parse_date(row.get("release_date", "")),
                    "total_tracks": _parse_int(row.get("total_tracks")),
                    "album_type":   row.get("album_type", "").strip() or None,
                    "label":        row.get("label",      "").strip() or None,
                    "popularity":   _parse_int(row.get("popularity")),
                    "genres":       _parse_list(row.get("genres", "")),
                    "spotify_url":  row.get("spotify_url", "").strip() or None,
                    "image_url":    row.get("image_url",   "").strip() or None,
                    "image_file":   row.get("image_file",  "").strip() or None,
                    "added_at":     row.get("added_at",    "").strip() or None,
                },
            )
            album_id, was_inserted = cur.fetchone()
            if was_inserted:
                inserted += 1
            else:
                updated += 1

            # ── Upsert artists + join rows ───────────────────────────────────
            cur.execute("DELETE FROM album_artists WHERE album_id = %s", (album_id,))

            for position, artist_name in enumerate(_parse_list(row.get("artists", ""))):
                cur.execute(
                    """
                    INSERT INTO artists (user_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id, name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                    """,
                    (owner, artist_name),
                )
                artist_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO album_artists (album_id, artist_id, position)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (album_id, artist_id, position),
                )

            if progress_cb:
                progress_cb(
                    done=i,
                    total=total,
                    inserted=inserted,
                    updated=updated,
                    skipped=skipped,
                    current_album=name,
                )

    conn.commit()
    conn.close()

    return {
        "total":              total,
        "inserted":           inserted,
        "updated":            updated,
        "skipped":            skipped,
        "migrations_applied": migrations_applied,
    }
