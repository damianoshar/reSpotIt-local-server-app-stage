"""
routers/jobs.py
---------------
Generic job endpoints shared by every pipeline (sync, images, load).

  GET  /api/v1/jobs/{job_id}        — canonical job envelope (any type)
  POST /api/v1/jobs/{job_id}/cancel — cancel a running job, partial data kept
"""
from fastapi import APIRouter, Depends, HTTPException

from ..contract import error_envelope, to_job_envelope
from ..deps import get_current_user
from ..job_store import cancel_job, get_job
from ..models import User

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", summary="Get any job (canonical envelope)")
def show(job_id: str, user: User = Depends(get_current_user)):
    job = get_job(job_id, str(user.id))
    if not job:
        # The HTTPException handler maps 404 → nested not_found envelope.
        raise HTTPException(status_code=404, detail="Job not found.")
    return to_job_envelope(job)


@router.post("/{job_id}/cancel", summary="Cancel a running job")
def cancel(job_id: str, user: User = Depends(get_current_user)):
    job = get_job(job_id, str(user.id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("status") != "running":
        raise HTTPException(status_code=409, detail="Job is not running.")
    cancel_job(job_id, str(user.id))
    return {"status": "cancelled"}
