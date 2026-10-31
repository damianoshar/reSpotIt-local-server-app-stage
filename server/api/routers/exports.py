"""
routers/exports.py
------------------
Export audit trail, mirroring the elixir backend:

  GET /api/v1/exports/history — the library's past CSV exports, newest first.
                              Shape: { data: [{filename, row_count, exported_at}] }

Entries are written by GET /api/v1/albums/export, which records the filename
and row count once the CSV has been built.
"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ..models import User
from ..services.export_log import list_recent_exports

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


@router.get("/history", summary="Past CSV exports (newest first)")
def history(user: User = Depends(get_current_user)):
    return {"data": list_recent_exports(20, str(user.id))}
