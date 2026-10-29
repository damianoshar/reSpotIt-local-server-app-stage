"""routers/sync.py — library sync.

  POST /albums {clean, download_images} — the FULL pipeline (fetch → images →
    load) as one job, canonical per API-PARITY-PLAN §1. This is the only way to
    start a sync: the old fetch-only POST /start is gone. Two endpoints that
    both fetch from Spotify is the exact kind of divergence the contract exists
    to remove, and no other backend ever had the second one.

  GET /history?limit=10 — past runs, newest first, as {data: [job envelope]} —
    the same endpoint, shape, default and 50-cap elixir and C# already serve.
    The panel's "last sync" line reads it, so a fresh browser shows when the
    library was last synced instead of an empty panel. This store is in-memory
    (see job_store.list_jobs), so unlike the other backends history does not
    survive a restart.

Progress, cancellation and results all go through the generic job API
(GET /api/v1/jobs/{job_id}, POST /api/v1/jobs/{job_id}/cancel). The envelope's
`stage` field (albums | images | saving) is what tells a client which of the
three stages is running.
"""
import os
from fastapi import APIRouter, BackgroundTasks, Depends

from ..contract import ContractError, to_job_envelope
from ..deps import get_current_user
from ..job_store import create_job, update_job, is_cancelled, list_jobs
from ..models import User
from ..schemas import SyncStartBody
from ..scoping import as_uuid, user_csv_path
from ..services.spotify_service import fetch_all_albums, save_albums_to_csv
from ..services.image_service import run_image_download
from ..services.db_service import load_csv_to_db
from ..services.auth_service import get_valid_token, is_authenticated

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])

IMAGES_DIR = os.getenv("IMAGES_DIR", "/data/images")
DATABASE_URL   = os.environ.get("DATABASE_URL", "")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/migrations")


def _wipe_library(user_id: str):
    """Delete only this user's library rows (clean sync). FK cascades clear joins."""
    from ..database import SessionLocal
    from ..models import Album, Artist
    if not SessionLocal:
        raise RuntimeError("DATABASE_URL is not configured.")
    owner = as_uuid(user_id)
    db = SessionLocal()
    try:
        db.query(Album).filter(Album.user_id == owner).delete(synchronize_session=False)
        db.query(Artist).filter(Artist.user_id == owner).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _run_full(job_id: str, user_id: str, clean: bool, download_images: bool, include_tracks: bool = False):
    """Full pipeline as ONE job: fetch → (images) → load, with stages."""
    csv_path = user_csv_path(user_id)
    try:
        if clean:
            update_job(job_id, status="running", stage="albums",
                       message="Clearing library…")
            _wipe_library(user_id)

        update_job(job_id, status="running", message="Refreshing token…")
        token = get_valid_token(user_id)

        # ── Stage 1: fetch ──────────────────────────────────────────────
        def on_fetch(fetched, total, page, current_album, phase="albums"):
            if not is_cancelled(job_id):
                label = "Fetching albums" if phase == "albums" else "Fetching genres"
                update_job(job_id, stage="albums", fetched=fetched, total=total,
                           current_album=current_album,
                           message=f"{label}… {fetched}/{total or '?'}")

        albums = fetch_all_albums(token, progress_cb=on_fetch)

        if is_cancelled(job_id):
            update_job(job_id, status="cancelled", message="Cancelled by user.")
            return

        save_albums_to_csv(albums, csv_path)

        # ── Stage 2: images (optional) ──────────────────────────────────
        if download_images:
            def on_images(done, total, pct, downloaded, skipped, failed,
                          current_album, result):
                if not is_cancelled(job_id):
                    update_job(job_id, stage="images", fetched=done, total=total,
                               current_album=current_album,
                               message=f"Downloading images… {done}/{total}")

            img = run_image_download(
                csv_path=csv_path, out_path=csv_path, images_dir=IMAGES_DIR,
                progress_cb=on_images, cancel_check=lambda: is_cancelled(job_id),
            )
            if img.get("cancelled") or is_cancelled(job_id):
                update_job(job_id, status="cancelled", message="Cancelled by user.")
                return

        # ── Stage 3: load ───────────────────────────────────────────────
        def on_load(done, total, inserted, updated, skipped, current_album):
            if not is_cancelled(job_id):
                update_job(job_id, stage="saving", fetched=done, total=total,
                           inserted=inserted, updated=updated, skipped=skipped,
                           current_album=current_album,
                           message=f"Saving to library… {done}/{total}")

        result = load_csv_to_db(dsn=DATABASE_URL, csv_path=csv_path,
                                migrations_dir=MIGRATIONS_DIR, progress_cb=on_load,
                                user_id=user_id)

        if is_cancelled(job_id):
            update_job(job_id, status="cancelled", message="Cancelled by user.")
            return

        # ── Stage 4: optional album track lists ─────────────────────────
        if include_tracks:
            from ..services import album_cache
            from ..services.spotify_actions import get_album_details

            album_ids = [a.get("album_id") for a in albums if a.get("album_id")]
            already = album_cache.cached_album_ids(album_ids, user_id)
            pending = [i for i in album_ids if i not in already]
            update_job(job_id, stage="tracks", fetched=0, total=len(pending),
                       message=f"Caching track lists… 0/{len(pending)}")
            for idx, album_id in enumerate(pending, 1):
                if is_cancelled(job_id):
                    update_job(job_id, status="cancelled", message="Cancelled by user.")
                    return
                try:
                    tracks = get_album_details(token, album_id)
                    album_cache.replace_album_tracks(album_id, tracks, user_id)
                except Exception:
                    pass  # one bad album must not fail the whole sync
                update_job(job_id, stage="tracks", fetched=idx, total=len(pending),
                           message=f"Caching track lists… {idx}/{len(pending)}")

        if is_cancelled(job_id):
            update_job(job_id, status="cancelled", message="Cancelled by user.")
            return

        update_job(job_id, status="done", fetched=result["total"], total=result["total"],
                   inserted=result["inserted"], updated=result.get("updated", 0),
                   skipped=result["skipped"],
                   message=f"Done. {result['inserted']} added.")
    except Exception as e:
        update_job(job_id, status="error", message=str(e))


def _history_item(job: dict) -> dict:
    """Canonical envelope plus the timestamps a "last synced 2h ago" line needs.

    §1 allows backend-added keys (clients ignore unknowns), and the plan calls
    this endpoint "past runs (counts, timestamps)" — but it is the envelope plus
    two extras, not a new shape. Elixir and C# send the bare eight keys for now,
    so no client may require these.
    """
    item = to_job_envelope(job)
    item["created_at"]  = job.get("created_at")
    item["finished_at"] = (job.get("updated_at")
                           if item["status"] in ("done", "error", "cancelled")
                           else None)
    return item


@router.get("/history", summary="Past jobs, newest first (canonical)")
def history(limit: int = 10, user: User = Depends(get_current_user)):
    # Lenient like elixir and C#: a silly limit clamps (0 → empty, 200 → 50)
    # instead of erroring, so a shared client sees one behaviour everywhere.
    jobs = list_jobs(min(max(limit, 0), 50), str(user.id))
    return {"data": [_history_item(j) for j in jobs]}


@router.post("/albums", status_code=202, summary="Full library sync (canonical)")
def start_full(
    body: SyncStartBody,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    # Fail fast when Spotify is not linked: the other backends answer
    # 422 not_connected here instead of handing back a job that immediately
    # errors, so a shared frontend sees one code for this condition.
    if not is_authenticated(str(user.id)):
        raise ContractError(422, "not_connected", "Spotify account is not connected.")

    job_id = create_job("sync", str(user.id))
    background_tasks.add_task(_run_full, job_id, str(user.id), body.clean,
                              body.download_images, body.include_tracks)
    return {"job_id": job_id}
