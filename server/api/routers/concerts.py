"""
routers/concerts.py
-------------------
Server-canonical concert store (docs/STORAGE-POLICY.md).

Endpoints (all user-scoped via ``get_current_user``):

  GET    /api/v1/concerts          → {total, concerts[]}
  POST   /api/v1/concerts          → upsert a batch of concerts
  DELETE /api/v1/concerts/{id}     → remove one concert
  DELETE /api/v1/concerts          → clear this user's concerts
  POST   /api/v1/concerts/import   → {items, replace} mirror/merge import

The import endpoint is what push/pull uses: with ``replace=true`` the server is
mirrored onto the device payload (rows absent from the payload are removed); the
all-invalid guard means a bad payload can never wipe the store.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Concert, User
from ..schemas import (
    ConcertImport,
    ConcertsResponse,
    ConcertUpsert,
)

router = APIRouter(prefix="/api/v1/concerts", tags=["concerts"])

_FIELDS = ("artist", "artist_id", "title", "date", "venue", "url", "source_url",
           "followed", "created_at")


def _apply(row: Concert, item) -> None:
    for field in _FIELDS:
        setattr(row, field, getattr(item, field))


def _upsert(db: Session, user_id, items) -> tuple[int, int]:
    """Insert-or-update each item; return ``(imported, existing)``."""
    imported = existing = 0
    for item in items:
        row = (
            db.query(Concert)
            .filter(Concert.user_id == user_id, Concert.id == item.id)
            .first()
        )
        if row is None:
            row = Concert(user_id=user_id, id=item.id)
            db.add(row)
            imported += 1
        else:
            existing += 1
        _apply(row, item)
    db.commit()
    return imported, existing


@router.get("", response_model=ConcertsResponse, summary="List this user's concerts")
def list_concerts(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    rows = (
        db.query(Concert)
        .filter(Concert.user_id == user.id)
        .order_by(Concert.date.asc(), Concert.artist.asc())
        .all()
    )
    return ConcertsResponse(total=len(rows), concerts=rows)


@router.post("", summary="Upsert a batch of concerts")
def upsert_concerts(
    body: ConcertUpsert,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    imported, existing = _upsert(db, user.id, body.items)
    return {"upserted": imported + existing, "imported": imported, "existing": existing}


@router.post("/import", summary="Import concerts (merge, or mirror with replace=true)")
def import_concerts(
    body: ConcertImport,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    imported, existing = _upsert(db, user.id, body.items)
    errors: list[str] = []
    removed = 0
    if body.replace:
        if imported + existing == 0:
            errors.append("Mirror skipped: no valid rows to keep — concerts left as is.")
        else:
            keep = [item.id for item in body.items]
            removed = (
                db.query(Concert)
                .filter(Concert.user_id == user.id, ~Concert.id.in_(keep))
                .delete(synchronize_session=False)
            )
            db.commit()
    return {
        "imported": imported,
        "existing": existing,
        "removed":  removed,
        "total":    imported + existing,
        "errors":   errors,
    }


@router.delete("/{concert_id}", summary="Delete one concert")
def delete_concert(
    concert_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    deleted = (
        db.query(Concert)
        .filter(Concert.user_id == user.id, Concert.id == concert_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}


@router.delete("", summary="Clear this user's concerts")
def clear_concerts(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    deleted = (
        db.query(Concert)
        .filter(Concert.user_id == user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}
