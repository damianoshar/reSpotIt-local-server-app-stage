"""
routers/import_csv.py
---------------------
Canonical CSV import (API-PARITY-PLAN §1):

  POST /api/v1/import/csv {csv_content} → {imported, existing, skipped, errors[]}

Headers are tolerant (case/whitespace-insensitive + aliases); rows missing
id/title/artist are skipped with a capped error list. Autocommit per row so
one bad row never rolls back the rest.
"""
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import get_current_user
from ..models import User
from ..scoping import as_uuid
from ..services.db_service import _parse_date, run_migrations, wait_for_db

import os

import psycopg2

router = APIRouter(prefix="/api/v1/import", tags=["import"])

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")

ALIASES = {
    "id":        {"id", "spotify_id", "album_id"},
    "title":     {"title", "album_title", "album", "name", "album_name"},
    "artist":    {"artist", "artists", "artist_name"},
    "year":      {"year", "release_year"},
    "genre":     {"genre", "genres"},
    "image_url": {"image_url", "imageurl", "image", "cover", "cover_url", "artwork", "artwork_url"},
    "added_at":  {"added_at", "date_added", "added"},
}

MAX_ERRORS = 20


class ImportBody(BaseModel):
    csv_content: str
    # Mirror mode: after upserting, delete this user's albums that are absent
    # from the payload (and any artists left with no albums). This is how a
    # phone that synced locally becomes the source of truth for its server
    # library. Playlists, tracks and retention are deliberately untouched.
    replace: bool = False


def _normalize_header(raw: str) -> str:
    return "_".join(raw.strip().lower().split())


def _column_map(fieldnames: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(fieldnames or []):
        norm = _normalize_header(raw)
        for field, aliases in ALIASES.items():
            if norm in aliases and field not in mapping:
                mapping[field] = idx
    return mapping


def _year_to_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date(int(value), 1, 1)
    except (ValueError, TypeError):
        return None


@router.post("/csv", summary="Import library rows from CSV text")
def import_csv(body: ImportBody, user: User = Depends(get_current_user)):
    if DATABASE_URL.startswith("sqlite"):
        return {"imported": 0, "existing": 0, "skipped": 0, "removed": 0,
                "errors": ["CSV import requires Postgres; not available in the desktop/SQLite build."]}
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not configured.")
    owner = as_uuid(user.id)

    text = (body.csv_content or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return {"imported": 0, "existing": 0, "skipped": 0, "removed": 0,
                "errors": ["CSV file is empty"]}

    reader = csv.reader(io.StringIO("\n".join(lines)))
    try:
        headers = next(reader)
    except StopIteration:
        return {"imported": 0, "existing": 0, "skipped": 0, "removed": 0,
                "errors": ["CSV file is empty"]}

    cols = _column_map(headers)
    missing = [f for f in ("id", "title", "artist") if f not in cols]
    if missing:
        return {"imported": 0, "existing": 0, "skipped": 0, "removed": 0,
                "errors": [f"Missing required column(s): {', '.join(missing)}"]}

    wait_for_db(DATABASE_URL)
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    try:
        run_migrations(conn, MIGRATIONS_DIR)

        imported = existing = skipped = 0
        removed = 0
        errors: list[str] = []
        pushed_ids: list[str] = []

        with conn.cursor() as cur:
            for line_no, row in enumerate(reader, start=2):
                def cell(field: str) -> str:
                    idx = cols.get(field)
                    return row[idx].strip() if idx is not None and idx < len(row) else ""

                spotify_id = cell("id")
                title      = cell("title")
                artist     = cell("artist")
                if not spotify_id or not title or not artist:
                    skipped += 1
                    if len(errors) < MAX_ERRORS:
                        errors.append(f"Line {line_no}: skipped — missing id/title/artist")
                    continue

                try:
                    cur.execute(
                        """
                        INSERT INTO albums (user_id, spotify_id, name, release_date, image_url, added_at)
                        VALUES (%(user_id)s, %(spotify_id)s, %(name)s, %(release_date)s,
                                %(image_url)s, %(added_at)s)
                        ON CONFLICT (user_id, spotify_id) DO UPDATE SET
                            name         = EXCLUDED.name,
                            release_date = EXCLUDED.release_date,
                            image_url    = EXCLUDED.image_url,
                            added_at     = EXCLUDED.added_at
                        RETURNING id, (xmax = 0) AS was_inserted
                        """,
                        {
                            "user_id":      owner,
                            "spotify_id":   spotify_id,
                            "name":         title,
                            "release_date": _year_to_date(cell("year")),
                            "image_url":    cell("image_url") or None,
                            "added_at":     _parse_date(cell("added_at")),
                        },
                    )
                    album_id, was_inserted = cur.fetchone()
                    pushed_ids.append(spotify_id)
                    if was_inserted:
                        imported += 1
                    else:
                        existing += 1

                    cur.execute("DELETE FROM album_artists WHERE album_id = %s", (album_id,))
                    for position, artist_name in enumerate(
                        [v.strip() for v in artist.split(",") if v.strip()]
                    ):
                        cur.execute(
                            """INSERT INTO artists (user_id, name) VALUES (%s, %s)
                               ON CONFLICT (user_id, name) DO UPDATE SET name = EXCLUDED.name
                               RETURNING id""",
                            (owner, artist_name),
                        )
                        artist_id = cur.fetchone()[0]
                        cur.execute(
                            """INSERT INTO album_artists (album_id, artist_id, position)
                               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                            (album_id, artist_id, position),
                        )

                    genre = cell("genre")
                    if genre:
                        cur.execute(
                            "UPDATE albums SET genres = string_to_array(%s, ';') WHERE id = %s AND user_id = %s",
                            (genre, album_id, owner),
                        )
                except Exception as e:
                    skipped += 1
                    if len(errors) < MAX_ERRORS:
                        errors.append(f'"{title}": {e}')

            # Mirror mode: drop what the payload no longer contains, so "phone
            # synced, then pushed" really replaces the server library instead
            # of growing it forever. Guarded: an all-invalid payload (0 kept
            # rows) must never empty the library — that is a bad file, not a
            # decision. Stays inside the cursor block: psycopg2 closes it on
            # exit, and the DELETE must share the connection state anyway.
            if body.replace:
                if imported + existing == 0:
                    if len(errors) < MAX_ERRORS:
                        errors.append("Mirror skipped: no valid rows to keep — library left as is.")
                else:
                    cur.execute(
                        "DELETE FROM albums WHERE user_id = %s AND NOT (spotify_id = ANY(%s))",
                        (owner, pushed_ids),
                    )
                    removed = cur.rowcount or 0
                    # Artists are joined per album; drop the ones now orphaned.
                    cur.execute(
                        """DELETE FROM artists a WHERE a.user_id = %s
                           AND NOT EXISTS (SELECT 1 FROM album_artists aa WHERE aa.artist_id = a.id)""",
                        (owner,),
                    )

        return {"imported": imported, "existing": existing, "skipped": skipped,
                "removed": removed, "errors": errors}
    finally:
        conn.close()
