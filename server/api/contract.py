"""
contract.py
-----------
Canonical API-PARITY-PLAN §1 shapes shared by every backend.

- to_job_envelope(): maps the internal in-memory job dict onto the
  canonical {job_id, type, status, stage, fetched, total, result, error}
  envelope (status done/error mapping included).
- error_envelope(): nested {error: {code, message}} shape.
- STATUS_CODES: HTTP status → machine-readable code.
"""

_JOB_STATUS = {
    "done":      "done",
    "error":     "error",
    "cancelled": "cancelled",
    "pending":   "pending",
    "running":   "running",
}

STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable",
    502: "bad_gateway",
}


def error_envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


class ContractError(Exception):
    """Answer a request with an explicit contract error envelope.

    `HTTPException` derives `code` from the status code (see STATUS_CODES),
    which loses the semantic codes the contract uses for specific conditions --
    `not_connected` and `no_albums` in particular. Raising this instead keeps the
    machine-readable code stable across backends.
    """

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def to_job_envelope(job: dict) -> dict:
    status = _JOB_STATUS.get(job.get("status"), job.get("status"))

    result = None
    if status in ("done", "error", "cancelled"):
        stored_errors = job.get("errors") or []
        errors = list(stored_errors[:20])
        if status == "error" and not errors and job.get("message"):
            errors = [str(job.get("message"))]
        result = {
            "imported": job.get("inserted", job.get("fetched", 0)) or 0,
            "existing": job.get("updated", 0) or 0,
            "skipped":  job.get("skipped", job.get("failed", 0)) or 0,
            "errors":   errors,
        }

    return {
        "job_id":  job.get("id"),
        "type":    job.get("type"),
        "status":  status,
        "stage":   job.get("phase") or job.get("stage") or "albums",
        "fetched": job.get("fetched", job.get("done", 0)) or 0,
        "total":   job.get("total", 0) or 0,
        "result":  result,
        "error":   job.get("message") if status == "error" else None,
        # Optional extra, which §1 allows (backends MAY add keys; clients ignore
        # unknowns): the album being fetched right now, for a UI that wants to
        # show it. Elixir and C# do not send it, so no client may depend on it.
        "current_album": job.get("current_album"),
    }
