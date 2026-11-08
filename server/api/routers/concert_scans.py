"""
routers/concert_scans.py
------------------------
Click-and-forget AI concert scans (docs/STORAGE-POLICY.md).

  POST   /api/v1/concert-scans          -> start a scan (202, returns the row)
  GET    /api/v1/concert-scans/latest   -> {scan: <row|null>} (pending results)
  GET    /api/v1/concert-scans/{id}     -> one scan
  DELETE /api/v1/concert-scans/{id}     -> dismiss a scan after review

The scan runs in the background; the client can close immediately and read the
results later from ``/latest``. All user-scoped via ``get_current_user``.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..contract import ContractError
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import ConcertScanLatest, ConcertScanOut, ConcertScanStart
from ..services import concert_scan_service

router = APIRouter(prefix="/api/v1/concert-scans", tags=["concert-scans"])


@router.post("", response_model=ConcertScanOut, status_code=202,
             summary="Start a background concert scan")
def start_scan(
    body: ConcertScanStart,
    background: BackgroundTasks,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    if not (body.url or "").strip() and not (body.text or "").strip():
        raise ContractError(422, "llm_empty_input", "Provide url or text.")
    scan = concert_scan_service.create_scan(db, str(user.id), url=body.url, text=body.text)
    background.add_task(
        concert_scan_service.run_scan, scan.id, str(user.id), body.url, body.text,
    )
    return scan


# NOTE: declare /latest before /{scan_id} so the literal path is not shadowed.
@router.get("/latest", response_model=ConcertScanLatest,
            summary="The most recent scan (pending review results)")
def latest_scan(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    return ConcertScanLatest(scan=concert_scan_service.latest_scan(db, str(user.id)))


@router.get("/{scan_id}", response_model=ConcertScanOut, summary="One concert scan")
def get_scan(
    scan_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    scan = concert_scan_service.get_scan(db, str(user.id), scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found.")
    return scan


@router.delete("/{scan_id}", summary="Dismiss a concert scan")
def delete_scan(
    scan_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    deleted = concert_scan_service.delete_scan(db, str(user.id), scan_id)
    return {"deleted": deleted}
