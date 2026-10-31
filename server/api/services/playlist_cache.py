"""
services/playlist_cache.py
--------------------------
Cached Spotify playlists + tracks (Postgres), powering the playlist
dashboard without re-hitting Spotify on every view.

Parsed track shape (produced by fetchers, stored as-is)::
  {spotify_id, name, artist_names, album_spotify_id, album_name,
   album_image_url, release_year, duration_ms, track_number}
"""
import os

import psycopg2
import psycopg2.extras

from ..scoping import as_uuid

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")

_schema_ready = False


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg2.connect(DATABASE_URL)


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    from .db_service import run_migrations, wait_for_db
    wait_for_db(DATABASE_URL)
    conn = _connect()
    try:
        run_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()
    _schema_ready = True


def upsert_playlist(meta: dict, user_id: str):
    """Insert or update this user's playlist row by spotify_id. Returns the UUID."""
    ensure_schema()
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO playlists
                (user_id, spotify_id, name, description, image_url, owner_name,
                 track_count, public, synced_at)
            VALUES (%(user_id)s, %(spotify_id)s, %(name)s, %(description)s, %(image_url)s,
                    %(owner_name)s, %(track_count)s, %(public)s, %(synced_at)s)
            ON CONFLICT (user_id, spotify_id) DO UPDATE SET
                name        = EXCLUDED.name,
                description = EXCLUDED.description,
                image_url   = EXCLUDED.image_url,
                owner_name  = EXCLUDED.owner_name,
                track_count = EXCLUDED.track_count,
                public      = EXCLUDED.public,
                synced_at   = EXCLUDED.synced_at,
                updated_at  = now()
            RETURNING id
            """,
            {
                "user_id":     owner,
                "spotify_id":  meta.get("id") or meta.get("spotify_id"),
                "name":        meta.get("name", ""),
                "description": meta.get("description", "") or "",
                "image_url":   meta.get("image_url"),
                "owner_name":  meta.get("owner"),
                "track_count": meta.get("track_count", 0) or 0,
                "public":      bool(meta.get("public", False)),
                "synced_at":   meta.get("synced_at"),
            },
        )
        playlist_id = cur.fetchone()[0]
        conn.commit()
        return playlist_id


def get_playlist_by_spotify(spotify_id: str, user_id: str):
    ensure_schema()
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM playlists WHERE spotify_id = %s AND user_id = %s",
            (spotify_id, owner),
        )
        return cur.fetchone()


def synced_map(user_id: str) -> dict[str, str]:
    """spotify_id → ISO `synced_at` for this user's completed playlist syncs.

    Backs the picker badges and the "does this playlist need its first sync
    before GET /albums can answer" decision (that endpoint 404s until the
    cache is built). Complements `album_groups`, which reads one playlist.
    """
    ensure_schema()
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT spotify_id, synced_at FROM playlists "
            "WHERE user_id = %s AND synced_at IS NOT NULL",
            (owner,),
        )
        return {r[0]: r[1].isoformat() for r in cur.fetchall()}


def replace_tracks(playlist_uuid, tracks: list[dict], user_id: str) -> int:
    """Replace all cached tracks for one owned playlist. Returns row count."""
    ensure_schema()
    owner = as_uuid(user_id)
    rows = [
        (
            str(playlist_uuid),
            idx,
            t.get("spotify_id"),
            t.get("name", ""),
            t.get("artist_names", ""),
            t.get("album_spotify_id"),
            t.get("album_name", ""),
            t.get("album_image_url"),
            t.get("release_year"),
            t.get("duration_ms"),
            t.get("track_number"),
        )
        for idx, t in enumerate(tracks)
    ]
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM playlists WHERE id = %s AND user_id = %s",
            (str(playlist_uuid), owner),
        )
        if not cur.fetchone():
            raise PermissionError("Playlist does not belong to this user.")
        cur.execute("DELETE FROM playlist_tracks WHERE playlist_id = %s", (str(playlist_uuid),))
        if rows:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO playlist_tracks
                   (playlist_id, position, spotify_id, name, artist_names,
                    album_spotify_id, album_name, album_image_url,
                    release_year, duration_ms, track_number)
                   VALUES %s""",
                rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                page_size=500,
            )
        conn.commit()
        return len(rows)


def mark_synced(spotify_id: str, track_count: int, user_id: str):
    ensure_schema()
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE playlists
               SET synced_at = now(), track_count = %s, updated_at = now()
               WHERE spotify_id = %s AND user_id = %s""",
            (track_count, spotify_id, owner),
        )
        conn.commit()


def album_groups(spotify_id: str, user_id: str) -> list[dict]:
    """Deduped albums for one of this user's cached playlists, first-appearance order."""
    ensure_schema()
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT pt.album_spotify_id, pt.album_name, pt.album_image_url,
                      pt.release_year, pt.artist_names, pt.name AS track_name
               FROM playlist_tracks pt
               JOIN playlists p ON p.id = pt.playlist_id
               WHERE p.spotify_id = %s AND p.user_id = %s
               ORDER BY pt.position""",
            (spotify_id, owner),
        )
        tracks = list(cur.fetchall())

    groups: dict[str, dict] = {}
    order: list[str] = []
    for t in tracks:
        album_id = t["album_spotify_id"]
        if not album_id:
            continue
        g = groups.get(album_id)
        if g is None:
            g = {
                "album_spotify_id": album_id,
                "title":            t["album_name"] or "Unknown Album",
                "artist":           t["artist_names"] or "",
                "year":             t["release_year"] or 0,
                "genre":            "",
                "image_url":        t["album_image_url"] or "",
                "track_titles":     [],
            }
            groups[album_id] = g
            order.append(album_id)
        if t["track_name"] and t["track_name"] not in g["track_titles"]:
            g["track_titles"].append(t["track_name"])

    # Genre resolves through the library when the album is known locally.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT a.spotify_id, array_to_string(a.genres, '; ')
               FROM albums a
               WHERE a.user_id = %s
                 AND a.spotify_id = ANY(%s)
                 AND a.genres IS NOT NULL""",
            (owner, order),
        )
        genre_map = {r[0]: (r[1] or "").split("; ")[0] for r in cur.fetchall()}

    result = []
    for album_id in order:
        g = groups[album_id]
        g["genre"] = genre_map.get(album_id, "")
        g["track_count"] = len(g["track_titles"])
        result.append(g)
    return result


def remove_track_uris(spotify_id: str, uris: list[str], user_id: str) -> int:
    """Drop individual track URIs from one of this user's cached playlists."""
    ids = [u.rsplit(":", 1)[-1] for u in uris if u.startswith("spotify:track:")]
    if not ids:
        return 0
    ensure_schema()
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM playlist_tracks pt
               USING playlists p
               WHERE pt.playlist_id = p.id
                 AND p.spotify_id = %s
                 AND p.user_id = %s
                 AND pt.spotify_id = ANY(%s)""",
            (spotify_id, owner, ids),
        )
        removed = cur.rowcount
        cur.execute(
            """UPDATE playlists
               SET track_count = GREATEST(track_count - %s, 0), updated_at = now()
               WHERE spotify_id = %s AND user_id = %s""",
            (removed, spotify_id, owner),
        )
        conn.commit()
    return removed


def album_track_uris(spotify_id: str, album_ids: list[str], user_id: str) -> list[str]:
    """Read-only: cached track URIs belonging to the given albums.

    Split from the cache delete so the router can call Spotify first and only
    mutate the cache once the removal is confirmed.
    """
    ensure_schema()
    if not album_ids:
        return []
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT pt.spotify_id
               FROM playlist_tracks pt
               JOIN playlists p ON p.id = pt.playlist_id
               WHERE p.spotify_id = %s AND p.user_id = %s
                 AND pt.album_spotify_id = ANY(%s)""",
            (spotify_id, owner, album_ids),
        )
        track_ids = [r[0] for r in cur.fetchall() if r[0]]
    return [f"spotify:track:{i}" for i in track_ids]


def remove_album_tracks_from_cache(spotify_id: str, album_ids: list[str], user_id: str) -> int:
    """Delete cached rows for the given albums, after Spotify confirms."""
    ensure_schema()
    if not album_ids:
        return 0
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM playlist_tracks pt
               USING playlists p
               WHERE pt.playlist_id = p.id
                 AND p.spotify_id = %s
                 AND p.user_id = %s
                 AND pt.album_spotify_id = ANY(%s)""",
            (spotify_id, owner, album_ids),
        )
        deleted = cur.rowcount
        cur.execute(
            """UPDATE playlists
               SET track_count = GREATEST(track_count - %s, 0), updated_at = now()
               WHERE spotify_id = %s AND user_id = %s""",
            (deleted, spotify_id, owner),
        )
        conn.commit()
    return deleted


def delete_playlist_cache(spotify_id: str, user_id: str) -> bool:
    """Drop one of this user's playlists and its track rows after unfollowing.

    ``playlist_tracks`` cascades from ``playlists``. Best-effort: the live
    Spotify list is the source of truth, so a cache miss here is harmless.
    """
    ensure_schema()
    owner = as_uuid(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM playlists WHERE spotify_id = %s AND user_id = %s",
            (spotify_id, owner),
        )
        deleted = cur.rowcount
        conn.commit()
    return deleted > 0


def remove_album_tracks(spotify_id: str, album_ids: list[str], user_id: str) -> list[str]:
    """Legacy helper: read URIs and delete the cache rows in one call.

    Prefer ``album_track_uris`` + ``remove_album_tracks_from_cache`` so a
    failed Spotify call cannot leave the cache ahead of reality.
    """
    uris = album_track_uris(spotify_id, album_ids, user_id)
    remove_album_tracks_from_cache(spotify_id, album_ids, user_id)
    return uris


def filter_options(spotify_id: str, user_id: str) -> dict:
    """Distinct genres/artists/years for one of this user's cached playlists."""
    groups = album_groups(spotify_id, user_id)
    artists: set[str] = set()
    for g in groups:
        for name in (g["artist"] or "").split(","):
            name = name.strip()
            if name:
                artists.add(name)
    return {
        "genres":  sorted({g["genre"] for g in groups if g["genre"]}),
        "artists": sorted(artists),
        "years":   sorted({g["year"] for g in groups if g["year"]}, reverse=True),
    }

