"""
csv_to_postgres.py
------------------
Loads spotify_albums.csv into Postgres.

  - Runs the migration SQL if the tables don't exist yet.
  - Upserts albums (keyed on spotify_id) so re-runs are safe.
  - Upserts artists (keyed on name) and wires up the join table.
  - Skips rows with missing spotify_id.

Env vars:
  DATABASE_URL   postgres://user:pass@host:5432/dbname
  INPUT_CSV      (default: /data/spotify_albums.csv)
  MIGRATIONS_DIR (default: /app/migrations)
"""

import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

# ── Config ─────────────────────────────────────────────────────────────────
DATABASE_URL   = os.environ["DATABASE_URL"]
INPUT_CSV      = os.getenv("INPUT_CSV",      "/data/spotify_albums.csv")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")
# ───────────────────────────────────────────────────────────────────────────


def wait_for_db(dsn: str, retries: int = 10, delay: float = 3.0):
    """Retry connecting until Postgres is ready (useful in docker compose)."""
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(dsn)
            conn.close()
            print(f"  DB ready after {attempt} attempt(s).")
            return
        except psycopg2.OperationalError as e:
            print(f"  Waiting for DB ({attempt}/{retries}): {e}")
            time.sleep(delay)
    print("ERROR: Could not connect to Postgres. Check DATABASE_URL.")
    sys.exit(1)


def run_migrations(conn):
    """Execute every *.sql file in MIGRATIONS_DIR in sorted order."""
    sql_files = sorted(Path(MIGRATIONS_DIR).glob("*.sql"))
    if not sql_files:
        print(f"  No migration files found in {MIGRATIONS_DIR}")
        return
    with conn.cursor() as cur:
        for path in sql_files:
            print(f"  Running migration: {path.name}")
            cur.execute(path.read_text())
    conn.commit()
    print(f"  {len(sql_files)} migration(s) applied.")


def parse_date(value: str):
    """Parse Spotify release_date — can be YYYY, YYYY-MM, or YYYY-MM-DD."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(value: str):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_genres(value: str):
    """Split comma-separated genres into a list (empty list if blank)."""
    if not value or not value.strip():
        return []
    return [g.strip() for g in value.split(",") if g.strip()]


def parse_artists(value: str):
    """Split comma-separated artist names, preserving order."""
    if not value or not value.strip():
        return []
    return [a.strip() for a in value.split(",") if a.strip()]


def bar(done: int, total: int, width: int = 20) -> str:
    pct    = int(done / total * 100) if total else 0
    filled = pct // (100 // width)
    return f"[{'#' * filled}{'-' * (width - filled)}] {pct:3d}%  {done}/{total}"


def load_csv(conn, rows: list[dict]):
    total    = len(rows)
    inserted = 0
    updated  = 0
    skipped  = 0

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
                    spotify_id, name, release_date, total_tracks, album_type,
                    label, popularity, genres, spotify_url, image_url,
                    image_file, added_at
                )
                VALUES (
                    %(spotify_id)s, %(name)s, %(release_date)s, %(total_tracks)s,
                    %(album_type)s, %(label)s, %(popularity)s, %(genres)s,
                    %(spotify_url)s, %(image_url)s, %(image_file)s, %(added_at)s
                )
                ON CONFLICT (spotify_id) DO UPDATE SET
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
                    "spotify_id":   spotify_id,
                    "name":         name,
                    "release_date": parse_date(row.get("release_date", "")),
                    "total_tracks": parse_int(row.get("total_tracks")),
                    "album_type":   row.get("album_type", "").strip() or None,
                    "label":        row.get("label", "").strip() or None,
                    "popularity":   parse_int(row.get("popularity")),
                    "genres":       parse_genres(row.get("genres", "")),
                    "spotify_url":  row.get("spotify_url", "").strip() or None,
                    "image_url":    row.get("image_url", "").strip() or None,
                    "image_file":   row.get("image_file", "").strip() or None,
                    "added_at":     row.get("added_at", "").strip() or None,
                },
            )
            album_id, was_inserted = cur.fetchone()
            if was_inserted:
                inserted += 1
            else:
                updated += 1

            # ── Upsert artists & join rows ───────────────────────────────────
            artist_names = parse_artists(row.get("artists", ""))
            cur.execute("DELETE FROM album_artists WHERE album_id = %s", (album_id,))

            for position, artist_name in enumerate(artist_names):
                cur.execute(
                    """
                    INSERT INTO artists (name)
                    VALUES (%s)
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                    """,
                    (artist_name,),
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

            label = name[:35].ljust(35)
            status = "INS" if was_inserted else "UPD"
            print(f"  {bar(i, total)}  {status}  {label}", flush=True)

        conn.commit()

    return inserted, updated, skipped


def main():
    print("-- CSV -> Postgres Loader ----------------------------------------")

    if not os.path.exists(INPUT_CSV):
        print(f"ERROR: CSV not found at {INPUT_CSV}")
        sys.exit(1)

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"\n  Input : {INPUT_CSV}  ({len(rows)} rows)")
    print(f"  DB    : {DATABASE_URL.split('@')[-1]}\n")   # hide credentials

    wait_for_db(DATABASE_URL)

    conn = psycopg2.connect(DATABASE_URL)
    psycopg2.extras.register_uuid()

    print("\nRunning migrations ...")
    run_migrations(conn)

    print(f"\nLoading {len(rows)} albums ...\n")
    inserted, updated, skipped = load_csv(conn, rows)

    conn.close()

    print(f"""
-- Done ----------------------------------------------------------
  Timestamp : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
  Inserted  : {inserted}
  Updated   : {updated}
  Skipped   : {skipped}  (missing spotify_id)
-----------------------------------------------------------------""")


if __name__ == "__main__":
    main()
