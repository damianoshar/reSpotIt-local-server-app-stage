"""routers/load.py — POST /load/start: re-load the staged CSV into Postgres.

Python-only extension with no contract counterpart: this backend's pipeline is
CSV-staged (fetch writes /data/spotify_albums.csv, then the load upserts it), so
there is a "reload the database from the file on disk" action. The other
backends go straight from Spotify to their store and have no equivalent step.
Job progress/results come from the generic job API (GET /api/v1/jobs/{job_id}).
"""
import os
from fastapi import APIRouter, BackgroundTasks, Depends

from ..deps import get_current_user
from ..job_store import create_job, update_job
from ..models import User
from ..schemas import JobStarted
from ..scoping import user_csv_path
from ..services.db_service import load_csv_to_db

router = APIRouter(prefix="/api/v1/load", tags=["load"])

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")


def _run(job_id: str, user_id: str):
    csv_path = user_csv_path(user_id)
    try:
        # stage is part of the job envelope: a load job reports `saving`, which
        # is the same word the full sync uses for this step.
        update_job(job_id, status="running", stage="saving",
                   message="Connecting to Postgres…",
                   done=0, total=0, inserted=0, updated=0, skipped=0)

        def on_progress(done, total, inserted, updated, skipped, current_album):
            pct = int(done / total * 100) if total else 0
            update_job(job_id, done=done, total=total, pct=pct, inserted=inserted,
                       updated=updated, skipped=skipped, current_album=current_album,
                       message=f"{done}/{total} — {inserted} ins, {updated} upd")

        result = load_csv_to_db(dsn=DATABASE_URL, csv_path=csv_path,
                                migrations_dir=MIGRATIONS_DIR, progress_cb=on_progress,
                                user_id=user_id)
        update_job(job_id, status="done", pct=100,
                   message=f"Done. {result['inserted']} inserted, {result['updated']} updated.",
                   **result)
    except Exception as e:
        update_job(job_id, status="error", message=str(e))


@router.post("/start", status_code=202, response_model=JobStarted, summary="Load CSV into Postgres")
def start(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    if not DATABASE_URL:
        return {"error": "DATABASE_URL is not configured."}
    user_id = str(user.id)
    job_id = create_job("load", user_id)
    background_tasks.add_task(_run, job_id, user_id)
    return JobStarted(job_id=job_id, message="DB load started.")
