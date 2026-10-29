"""routers/images.py — POST /images/sync: download missing cover art.

Python-only extension (contract §1 Images, the frozen path): `POST
/api/v1/images/sync` → job; read progress/results back through the generic job
API (GET /api/v1/jobs/{job_id}). No other backend implements it — the full sync
runs images as its second stage, and this endpoint exists so covers can be
refreshed without re-fetching the library.
"""
import os
from fastapi import APIRouter, BackgroundTasks, Depends

from ..deps import get_current_user
from ..job_store import create_job, update_job, is_cancelled
from ..models import User
from ..schemas import JobStarted
from ..scoping import user_csv_path
from ..services.image_service import run_image_download

router = APIRouter(prefix="/api/v1/images", tags=["images"])

IMAGES_DIR = os.getenv("IMAGES_DIR", "/data/images")


def _run(job_id: str, user_id: str):
    csv_path = user_csv_path(user_id)
    try:
        # stage is part of the job envelope; without it an images job reports
        # the envelope's default ("albums"), which is simply wrong.
        update_job(job_id, status="running", stage="images",
                   message="Starting downloads…",
                   done=0, total=0, downloaded=0, skipped=0, failed=0)

        def on_progress(done, total, pct, downloaded, skipped, failed, current_album, result):
            update_job(job_id, done=done, total=total, pct=pct, downloaded=downloaded,
                       skipped=skipped, failed=failed, current_album=current_album,
                       message=f"{done}/{total} — {downloaded} dl, {skipped} skip, {failed} fail")

        result = run_image_download(
            csv_path=csv_path, out_path=csv_path, images_dir=IMAGES_DIR,
            progress_cb=on_progress, cancel_check=lambda: is_cancelled(job_id),
        )

        if result.get("cancelled"):
            update_job(job_id, status="cancelled",
                       message=f"Cancelled. {result['downloaded']} downloaded so far.")
        else:
            update_job(job_id, status="done", pct=100,
                       message=f"Done. {result['downloaded']} downloaded, "
                               f"{result['skipped']} skipped, {result['failed']} failed.",
                       **result)
    except Exception as e:
        update_job(job_id, status="error", message=str(e))


@router.post("/sync", status_code=202, response_model=JobStarted,
             summary="Download album cover images")
def download_covers(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    user_id = str(user.id)
    job_id = create_job("images", user_id)
    background_tasks.add_task(_run, job_id, user_id)
    return JobStarted(job_id=job_id, message="Image download started.")
