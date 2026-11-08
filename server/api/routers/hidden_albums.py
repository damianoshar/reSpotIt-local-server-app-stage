"""
routers/hidden_albums.py
------------------------
Server-canonical duplicate blocklist (docs/STORAGE-POLICY.md).

Endpoints (all user-scoped via ``get_current_user``):

  GET    /api/v1/albums/hidden               → {total, albums[]}
  POST   /api/v1/albums/hidden               → hide a batch of albums
  DELETE /api/v1/albums/hidden/{spotify_id}  → restore one album
  DELETE /api/v1/albums/hidden               → restore all
  POST   /api/v1/albums/hidden/import        → {items, replace} mirror/merge

Route-registration note: this router MUST be mounted before ``albums.py`` in
``main.py``. ``GET /api/v1/albums/hidden`` would otherwise match the album
router's ``GET /{spotify_id}`` with ``spotify_id="hidden"``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import HiddenAlbum, User
from ..schemas import (
    HiddenAlbumImport,
    HiddenAlbumsResponse,
    HiddenAlbumUpsert,
)

router = APIRouter(prefix="/api/v1/albums/hidden", tags=["hidden-albums"])

_FIELDS = ("title", "artist", "year", "genre", "album_type", "image_url", "added_at")


def _apply(row: HiddenAlbum, item) -> None:
    for field in _FIELDS:
        setattr(row, field, getattr(item, field))


def _upsert(db: Session, user_id, items) -> tuple[int, int]:
    imported = existing = 0
    for item in items:
        row = (
            db.query(HiddenAlbum)
            .filter(HiddenAlbum.user_id == user_id,
                    HiddenAlbum.spotify_id == item.spotify_id)
            .first()
        )
        if row is None:
            row = HiddenAlbum(user_id=user_id, spotify_id=item.spotify_id)
            db.add(row)
            imported += 1
        else:
            existing += 1
        _apply(row, item)
    db.commit()
    return imported, existing


@router.get("", response_model=HiddenAlbumsResponse,
            summary="List this user's hidden duplicate albums")
def list_hidden(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    rows = (
        db.query(HiddenAlbum)
        .filter(HiddenAlbum.user_id == user.id)
        .order_by(HiddenAlbum.artist.asc(), HiddenAlbum.title.asc())
        .all()
    )
    return HiddenAlbumsResponse(total=len(rows), albums=rows)


@router.post("", summary="Hide a batch of albums")
def hide_albums(
    body: HiddenAlbumUpsert,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    imported, existing = _upsert(db, user.id, body.items)
    return {"hidden": imported + existing, "imported": imported, "existing": existing}


@router.post("/import", summary="Import hidden albums (merge, or mirror with replace=true)")
def import_hidden(
    body: HiddenAlbumImport,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    imported, existing = _upsert(db, user.id, body.items)
    errors: list[str] = []
    removed = 0
    if body.replace:
        if imported + existing == 0:
            errors.append("Mirror skipped: no valid rows to keep — hidden albums left as is.")
        else:
            keep = [item.spotify_id for item in body.items]
            removed = (
                db.query(HiddenAlbum)
                .filter(HiddenAlbum.user_id == user.id,
                        ~HiddenAlbum.spotify_id.in_(keep))
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


@router.delete("/{spotify_id}", summary="Restore one hidden album")
def restore_album(
    spotify_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    deleted = (
        db.query(HiddenAlbum)
        .filter(HiddenAlbum.user_id == user.id,
                HiddenAlbum.spotify_id == spotify_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}


@router.delete("", summary="Restore all hidden albums")
def restore_all(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    deleted = (
        db.query(HiddenAlbum)
        .filter(HiddenAlbum.user_id == user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}
