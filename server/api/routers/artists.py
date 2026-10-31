"""
routers/artists.py
------------------
GET /artists             → paginated artist list
GET /artists/{artist_id} → single artist with their albums
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Artist, User
from ..schemas import ArtistDetail, PaginatedArtists

router = APIRouter(prefix="/api/v1/artists", tags=["artists"])


@router.get("", response_model=PaginatedArtists, summary="List artists")
def list_artists(
    db:     Session = Depends(get_db),
    user:   User = Depends(get_current_user),
    page:   int = Query(1,  ge=1),
    limit:  int = Query(50, ge=1, le=1000),
    search: str = Query(None, description="Filter by artist name (case-insensitive)"),
):
    q = db.query(Artist).filter(Artist.user_id == user.id)
    if search:
        q = q.filter(Artist.name.ilike(f"%{search}%"))

    total = q.count()
    items = q.order_by(Artist.name).offset((page - 1) * limit).limit(limit).all()

    return PaginatedArtists(total=total, page=page, limit=limit, items=items)


@router.get("/{artist_id}", response_model=ArtistDetail, summary="Get artist with albums")
def get_artist(
    artist_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    artist = (
        db.query(Artist)
        .filter(Artist.id == artist_id, Artist.user_id == user.id)
        .first()
    )
    if not artist:
        raise HTTPException(status_code=404, detail=f"Artist '{artist_id}' not found.")
    return artist
