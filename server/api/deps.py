"""deps.py - FastAPI JWT principal dependencies (Phase 2 + Keycloak Phase 3).

Every data route depends on ``get_current_user``; the returned ``User`` is the
single source of truth for ownership. Raw-SQL services receive ``str(user.id)``
and cast it with ``scoping.as_uuid``.

Two bearer token formats are accepted:

1. The original server-issued HS256 JWT (``/api/v1/auth/login``). Tried first,
   so existing clients keep working untouched.
2. A Keycloak RS256 access token when ``KEYCLOAK_ENABLED=true``. The subject
   is mapped to a local ``users`` row through ``keycloak_identities``; the
   library data model is unchanged.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .services import keycloak_service, user_auth_service


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    token = _bearer_token(authorization)

    # 1. Server-issued JWT (no network call).
    try:
        payload = user_auth_service.decode_token(token, "access")
        user = user_auth_service.get_user_by_id(db, payload.get("sub"))
        if user is not None:
            return user
    except Exception:
        pass

    # 2. Keycloak access token (optional integration).
    if keycloak_service.is_enabled():
        try:
            claims = keycloak_service.validate_token(token)
            return keycloak_service.ensure_local_user(db, claims)
        except keycloak_service.KeycloakUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except keycloak_service.KeycloakAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    raise HTTPException(status_code=401, detail="invalid or expired token")


def get_current_user_id(user: User = Depends(get_current_user)) -> str:
    return str(user.id)


def get_optional_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User | None:
    """Like get_current_user but returns None instead of raising 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        return get_current_user(authorization=authorization, db=db)
    except HTTPException:
        return None
