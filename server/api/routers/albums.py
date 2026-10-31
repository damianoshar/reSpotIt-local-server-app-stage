"""
routers/albums.py

Two query strategies:
  - Default sorts: use DISTINCT (safe because ORDER BY cols are all from albums table)
  - Artist sort: LEFT JOIN a position-0 artist subquery, no DISTINCT needed
    (position=0 guarantees ≤1 join row per album → no duplicates)
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Album, Artist, User, album_artists
from ..schemas import AlbumDetail, PaginatedAlbums
from ..services.export_log import record_export

router = APIRouter(prefix="/api/v1/albums", tags=["albums"])


def _apply_filters(q, db, search, album_type, min_pop, max_pop, genre, artist, year_from, year_to):
    """Apply all non-sort filters to a query and return it."""
    if search:
        q = q.filter(Album.name.ilike(f"%{search}%"))
    if album_type:
        q = q.filter(Album.album_type == album_type)
    if min_pop is not None:
        q = q.filter(Album.popularity >= min_pop)
    if max_pop is not None:
        q = q.filter(Album.popularity <= max_pop)
    if genre:
        q = q.filter(func.array_to_string(Album.genres, ",").ilike(f"%{genre}%"))
    if artist:
        q = q.join(Album.artists).filter(Artist.name.ilike(f"%{artist}%"))
    if year_from:
        q = q.filter(Album.release_date >= date(year_from, 1, 1))
    if year_to:
        q = q.filter(Album.release_date <= date(year_to, 12, 31))
    return q


_SORT_ALIASES = {
    "title":  "name",
    "year":   "year",
    "added_at": "added_at",
    "artist": "artist",
    "genre":  "genre",
    "name":   "name",
    "popularity": "popularity",
}

def _normalize_sort(sort: str, order: str | None) -> str:
    """Accept contract `sort`+`order` or legacy combined `sort=title_asc`."""
    if not sort:
        return "added_at_desc"
    if sort in ("artist_asc", "artist_desc"):
        return sort
    if sort.endswith(("_asc", "_desc")):
        return sort
    base = _SORT_ALIASES.get(sort, "added_at")
    direction = "asc" if (order or "").lower() == "asc" else "desc"
    return f"{base}_{direction}"


@router.get("", response_model=PaginatedAlbums, summary="List albums")
def list_albums(    db:         Session = Depends(get_db),
    user:       User    = Depends(get_current_user),
    page:       int     = Query(1,  ge=1),
    limit:      int     = Query(48, ge=1, le=200),
    search:     str     = Query(None),
    artist:     str     = Query(None),
    album_type: str     = Query(None),
    min_pop:    int     = Query(None, ge=0, le=100),
    max_pop:    int     = Query(None, ge=0, le=100),
    genre:      str     = Query(None),
    year_from:  int     = Query(None, ge=1900, le=2100),
    year_to:    int     = Query(None, ge=1900, le=2100),
    sort:       str     = Query("added_at_desc"),
    order:      str     = Query(None),
):
    # Contract style (sort=title&order=asc) maps onto the legacy combined
    # values (title_asc); combined values keep working as-is.
    sort = _normalize_sort(sort, order)
    offset = (page - 1) * limit

    # ── Artist sort ───────────────────────────────────────────────────────────
    # Join a subquery that yields exactly one row per album (position=0 artist).
    # Because there are no duplicates, DISTINCT is not needed and ORDER BY is free.
    if sort in ("artist_asc", "artist_desc"):
        # Strip a leading "The " (case-insensitive) before sorting so
        # "The Rolling Stones" sorts as "Rolling Stones"
        sort_name = func.regexp_replace(Artist.name, r"(?i)^the\s+", "", "i")

        artist_sq = (
            db.query(
                album_artists.c.album_id.label("album_id"),
                sort_name.label("artist_sort_name"),
            )
            .join(Artist, Artist.id == album_artists.c.artist_id)
            .join(Album, Album.id == album_artists.c.album_id)
            .filter(Album.user_id == user.id, album_artists.c.position == 0)
            .subquery()
        )

        q = (
            db.query(Album)
            .outerjoin(artist_sq, Album.id == artist_sq.c.album_id)
            .filter(Album.user_id == user.id)
        )
        q = _apply_filters(q, db, search, album_type, min_pop, max_pop, genre, artist, year_from, year_to)

        name_col = artist_sq.c.artist_sort_name
        primary  = name_col.asc() if sort == "artist_asc" else name_col.desc()
        secondary = Album.release_date.asc().nullslast()

        total = q.count()
        items = q.order_by(primary, secondary).offset(offset).limit(limit).all()

    # ── All other sorts ───────────────────────────────────────────────────────
    # Plain album columns use DISTINCT (safe); the genre *expression* needs
    # GROUP BY pk instead (Postgres rejects expressions in DISTINCT ordering).
    else:
        order_map = {
            "added_at_desc":   [Album.added_at.desc().nullslast()],
            "added_at_asc":    [Album.added_at.asc().nullsfirst()],
            "name_asc":        [Album.name.asc()],
            "name_desc":       [Album.name.desc()],
            "popularity_desc": [Album.popularity.desc().nullslast()],
            "popularity_asc":  [Album.popularity.asc().nullsfirst()],
            "year_desc":       [Album.release_date.desc().nullslast()],
            "year_asc":        [Album.release_date.asc().nullsfirst()],
            "genre_asc":       [func.min(func.array_to_string(Album.genres, ",")).asc().nullsfirst()],
            "genre_desc":      [func.min(func.array_to_string(Album.genres, ",")).desc().nullslast()],
        }
        order_clauses = order_map.get(sort, [Album.added_at.desc().nullslast()])

        q = db.query(Album).filter(Album.user_id == user.id)
        q = _apply_filters(q, db, search, album_type, min_pop, max_pop, genre, artist, year_from, year_to)

        if sort in ("genre_asc", "genre_desc"):
            q = q.group_by(Album.id)
            total = q.count()
            items = q.order_by(*order_clauses).offset(offset).limit(limit).all()
        else:
            total = q.distinct().count()
            items = (
                q.distinct()
                 .order_by(*order_clauses)
                 .offset(offset)
                 .limit(limit)
                 .all()
            )

    return PaginatedAlbums(total=total, page=page, limit=limit, items=items)


@router.get("/stats", summary="Library stats (canonical keys)")
def library_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    total_albums = (
        db.query(func.count(Album.id))
        .filter(Album.user_id == user.id)
        .scalar()
        or 0
    )
    total_artists = (
        db.query(func.count(func.distinct(album_artists.c.artist_id)))
        .select_from(album_artists)
        .join(Album, Album.id == album_artists.c.album_id)
        .filter(Album.user_id == user.id)
        .scalar()
        or 0
    )
    # unnest() is set-returning: select distinct genres in a subquery, count outside.
    genre_rows = (
        db.query(func.unnest(Album.genres).label("genre"))
        .filter(Album.user_id == user.id, Album.genres.isnot(None))
        .distinct()
        .subquery()
    )
    total_genres = db.query(func.count()).select_from(genre_rows).scalar() or 0
    newest_year = (
        db.query(func.max(func.extract("year", Album.release_date)))
        .filter(Album.user_id == user.id)
        .scalar()
    )
    oldest_year = (
        db.query(func.min(func.extract("year", Album.release_date)))
        .filter(Album.user_id == user.id)
        .scalar()
    )

    # ── Breakdowns for the stats views (top genres/artists, year histogram) ──
    # (reuses genre_rows above, minus DISTINCT — counts need every row)
    genre_all = (
        db.query(func.unnest(Album.genres).label("genre"))
        .filter(Album.user_id == user.id, Album.genres.isnot(None))
        .subquery()
    )
    top_genres = (
        db.query(genre_all.c.genre, func.count().label("n"))
        .filter(genre_all.c.genre != "")
        .group_by(genre_all.c.genre)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    top_artists = (
        db.query(Artist.name, func.count(func.distinct(album_artists.c.album_id)).label("n"))
        .join(album_artists, Artist.id == album_artists.c.artist_id)
        .join(Album, Album.id == album_artists.c.album_id)
        .filter(Album.user_id == user.id)
        .group_by(Artist.name)
        .order_by(func.count(func.distinct(album_artists.c.album_id)).desc())
        .limit(10)
        .all()
    )
    by_year = (
        db.query(func.extract("year", Album.release_date).label("year"), func.count().label("n"))
        .filter(Album.user_id == user.id, Album.release_date.isnot(None))
        .group_by("year")
        .order_by("year")
        .all()
    )

    return {
        "totalAlbums":  total_albums,
        "totalArtists": total_artists,
        "totalGenres":  total_genres,
        "newestYear":   int(newest_year) if newest_year is not None else 0,
        "oldestYear":   int(oldest_year) if oldest_year is not None else 0,
        "topGenres":    [{"name": g, "count": n} for g, n in top_genres],
        "topArtists":   [{"name": a, "count": n} for a, n in top_artists],
        "albumsByYear": [{"year": int(y), "count": n} for y, n in by_year],
    }


@router.get("/export", summary="Library CSV export (canonical columns)")
def export_library(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import csv
    import io
    from datetime import date
    from fastapi.responses import StreamingResponse

    rows = (
        db.query(Album)
        .filter(Album.user_id == user.id)
        .order_by(Album.name)
        .all()
    )

    def artists_of(a) -> str:
        return "; ".join(sorted({ar.name for ar in a.artists if ar.name}))

    def year_of(a) -> str:
        rd = a.release_date
        return str(rd.year) if isinstance(rd, date) else ""

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "title", "artist", "year", "genre", "image_url", "added_at"])
    for a in rows:
        genres = "; ".join(a.genres) if isinstance(a.genres, list) else (a.genres or "")
        added = a.added_at.date().isoformat() if a.added_at else ""
        writer.writerow([
            a.spotify_id or "", a.name or "", artists_of(a), year_of(a),
            genres, a.image_url or "", added,
        ])

    buf.seek(0)
    today = date.today().isoformat()
    filename = f"spotify-library-{today}.csv"
    # Audit trail for GET /api/v1/exports/history (best-effort; never raises).
    record_export(filename, len(rows), str(user.id))
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{spotify_id}", response_model=AlbumDetail, summary="Get album by Spotify ID")
def get_album(
    spotify_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    album = (
        db.query(Album)
        .filter(Album.spotify_id == spotify_id, Album.user_id == user.id)
        .first()
    )
    if not album:
        raise HTTPException(status_code=404, detail=f"Album '{spotify_id}' not found.")
    return album


@router.delete("", summary="Clear this user's library")
def clear_library(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # albums → album_artists is ON DELETE CASCADE; deleting the user's albums
    # cannot touch another user's join rows.
    n_albums = (
        db.query(Album)
        .filter(Album.user_id == user.id)
        .delete(synchronize_session=False)
    )
    db.query(Artist).filter(Artist.user_id == user.id).delete(synchronize_session=False)
    db.commit()
    return {"deleted": n_albums}