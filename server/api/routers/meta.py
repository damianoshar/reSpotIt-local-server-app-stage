"""
routers/meta.py
---------------
Distinct filter-option lists (canonical):
  GET /api/v1/meta/genres | /meta/artists | /meta/years
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Album, Artist, User

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


@router.get("/genres", summary="Distinct genres in the library")
def genres(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(func.distinct(func.unnest(Album.genres)).label("genre"))
        .filter(Album.user_id == user.id, Album.genres.isnot(None))
        .order_by("genre")
        .all()
    )
    return {"data": sorted({r[0] for r in rows if r[0]})}


@router.get("/artists", summary="Distinct artist names in the library")
def artists(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(Artist.name)
        .filter(Artist.user_id == user.id)
        .order_by(Artist.name)
        .all()
    )
    return {"data": [r[0] for r in rows]}


@router.get("/years", summary="Distinct release years in the library")
def years(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(func.extract("year", Album.release_date).label("year"))
        .filter(Album.user_id == user.id, Album.release_date.isnot(None))
        .distinct()
        .order_by(func.extract("year", Album.release_date).desc())
        .all()
    )
    return {"data": [int(r[0]) for r in rows]}
