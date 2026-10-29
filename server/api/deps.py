"""deps.py — FastAPI JWT principal dependencies (Phase 2).

Every data route depends on ``get_current_user``; the returned ``User`` is the
single source of truth for ownership. Raw-SQL services receive ``str(user.id)``
and cast it with ``scoping.as_uuid``.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .services import user_auth_service


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        payload = user_auth_service.decode_token(token, "access")
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    user = user_auth_service.get_user_by_id(db, payload.get("sub"))
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> str:
    return str(user.id)
