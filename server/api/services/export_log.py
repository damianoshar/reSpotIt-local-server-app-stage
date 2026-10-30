"""
export_log.py
------------
Audit trail for CSV exports. Dialect-agnostic.
"""

import logging
import os

from sqlalchemy.orm import Session

from ..database import SessionLocal, is_sqlite
from ..models import ExportLog
from ..scoping import as_uuid
from .db_service import run_migrations, wait_for_db, MIGRATIONS_DIR

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 20


def _ensure_schema():
    wait_for_db(os.environ.get("DATABASE_URL", ""))
    if not is_sqlite():
        import psycopg2
        conn = psycopg2.connect(os.environ.get("DATABASE_URL", ""))
        conn.autocommit = True
        try:
            run_migrations(conn, MIGRATIONS_DIR)
        finally:
            conn.close()


def record_export(filename: str, row_count: int, user_id: str) -> None:
    if not os.environ.get("DATABASE_URL"):
        return
    try:
        _ensure_schema()
        with SessionLocal() as db:
            db.add(ExportLog(
                user_id=str(as_uuid(user_id)),
                filename=filename,
                row_count=row_count,
            ))
            db.commit()
    except Exception as exc:
        log.warning("export log write failed: %s", exc)


def list_recent_exports(limit: int = DEFAULT_LIMIT, user_id: str | None = None) -> list[dict]:
    if not os.environ.get("DATABASE_URL") or not user_id:
        return []
    try:
        _ensure_schema()
        with SessionLocal() as db:
            rows = db.query(ExportLog).filter(
                ExportLog.user_id == str(as_uuid(user_id)),
            ).order_by(ExportLog.created_at.desc()).limit(limit).all()
    except Exception as exc:
        log.warning("export history read failed: %s", exc)
        return []
    return [
        {
            "filename": r.filename,
            "row_count": int(r.row_count or 0),
            "exported_at": r.created_at.isoformat() if r.created_at is not None else None,
        }
        for r in rows
    ]