"""scoping.py — per-user data paths and UUID adaptation.

Kept separate from routers/services so both can import it without cycles.
"""

import os
import uuid

import psycopg2.extras

# Adapt uuid.UUID values to the Postgres uuid type on every connection.
psycopg2.extras.register_uuid()


def _is_sqlite() -> bool:
    try:
        from .database import is_sqlite
        return is_sqlite()
    except Exception:
        return False


def as_uuid(value):
    """Return a value usable as a user_id in SQL params.

    Postgres columns are UUID-typed (psycopg2 adapts uuid.UUID); SQLite
    columns are TEXT, so a plain string is correct there.
    """
    if isinstance(value, uuid.UUID):
        if _is_sqlite():
            return str(value)
        return value
    s = str(value)
    if _is_sqlite():
        return s
    try:
        return uuid.UUID(s)
    except (ValueError, AttributeError):
        return s


def user_data_dir(user_id) -> str:
    """Per-user staging directory under the mounted data volume."""
    root = os.getenv("DATA_DIR", "/data")
    path = os.path.join(root, "users", str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def user_csv_path(user_id, name: str = "spotify_albums.csv") -> str:
    return os.path.join(user_data_dir(user_id), name)
