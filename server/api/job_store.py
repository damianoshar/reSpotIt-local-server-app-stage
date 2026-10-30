"""
job_store.py
------------
Thread-safe in-memory job store with cancellation support.

Just the store and its primitives: a router creates a job, a worker updates it,
and the generic job API (routers/jobs.py) reads and cancels it. The old
attach_job_routes() helper — which stamped /cancel, /jobs and /jobs/{id} onto
each pipeline router — is gone: /api/v1/jobs/{job_id} and
/api/v1/jobs/{job_id}/cancel serve every job type, which is all a contract
client needs and all the other backends offer.
"""

import threading
import uuid
from datetime import datetime, timezone

_jobs:         dict[str, dict]             = {}
_cancel_flags: dict[str, threading.Event] = {}
_lock = threading.Lock()


# ── Core store ────────────────────────────────────────────────────────────────

def create_job(job_type: str, user_id: str) -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "id":         job_id,
            "user_id":    str(user_id),
            "type":       job_type,
            "status":     "pending",
            "message":    "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": None,
        }
        _cancel_flags[job_id] = threading.Event()
    return job_id


def update_job(job_id: str, **kwargs) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)
            _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()


def get_job(job_id: str, user_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("user_id") != str(user_id):
            return None
        return dict(job)


def list_jobs(limit: int, user_id: str) -> list[dict]:
    """Newest-first snapshot of this user's jobs, backing GET /api/v1/sync/history.

    Elixir and C# serve the same endpoint from their persisted job tables (all
    types, newest first, capped at 50). This store is in-memory, so history is
    per-process: a restart starts it over. That is the one behavioural
    difference and the README says so.
    """
    owner = str(user_id)
    with _lock:
        jobs = [dict(j) for j in _jobs.values() if j.get("user_id") == owner]
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return jobs[:max(0, limit)]


def cancel_job(job_id: str, user_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("user_id") != str(user_id):
            return False
        _cancel_flags[job_id].set()
        if _jobs[job_id]["status"] == "running":
            _jobs[job_id]["status"]     = "cancelled"
            _jobs[job_id]["message"]    = "Cancelled by user."
            _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    return True


def is_cancelled(job_id: str) -> bool:
    with _lock:
        flag = _cancel_flags.get(job_id)
    return flag.is_set() if flag else False
