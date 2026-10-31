"""routers/keycloak.py - Keycloak OIDC login for the local API (Phase 3).

Additive routes under /api/v1/auth/keycloak. Existing email/password login and
the Spotify OAuth flow are untouched.

Flow (web and mobile):

    client -> GET /login?redirect_uri=<app-url>
    API    -> 302 Keycloak (state = signed, short-lived redirect target)
    Keycloak -> 302 GET /callback?code&state   (confidential client)
    API    -> exchange code, map sub -> local user, mint local JWT pair
    API    -> 302 <app-url>#access_token=...&refresh_token=...

The client secret never leaves the server. Mobile apps use their custom scheme
as ``redirect_uri``; the API redirects back to it with the local tokens.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user, get_optional_user
from ..models import KeycloakIdentity, User
from ..schemas import KeycloakExchange, KeycloakRefresh
from ..services import keycloak_service, user_auth_service

logger = logging.getLogger("keycloak")

router = APIRouter(prefix="/api/v1/auth/keycloak", tags=["keycloak-auth"])

DEFAULT_APP_REDIRECT = "com.spotifydashboard.app://callback"


def _settings():
    return get_settings()


def _issue_local_tokens(user: User) -> dict:
    return user_auth_service.issue_tokens(user)


def _redirect_with_tokens(target: str, tokens: dict) -> RedirectResponse:
    """Put tokens in the fragment for http(s), query for custom schemes."""
    params = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens.get("token_type", "bearer"),
        "email": tokens.get("email", ""),
        "user_id": tokens.get("user_id", ""),
    }
    encoded = urlencode(params)
    if target.startswith("http://") or target.startswith("https://"):
        base = target.split("#", 1)[0]
        sep = "&" if "?" in base else "#"
        return RedirectResponse(f"{base}{sep}{encoded}", status_code=302)
    sep = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{sep}{encoded}", status_code=302)


def _complete_login(db: Session, token_response: dict) -> tuple[User, dict]:
    access_token = token_response.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Keycloak returned no access token.")
    claims = keycloak_service.validate_token(access_token)
    user = keycloak_service.ensure_local_user(db, claims)
    keycloak_service.save_tokens(db, str(user.id), token_response)
    return user, _issue_local_tokens(user)


@router.get("/status", summary="Keycloak availability and login URL")
def status():
    s = _settings()
    return {
        "enabled": keycloak_service.is_enabled(),
        "issuer": s.keycloak_issuer,
        "client_id": s.keycloak_client_id,
        "redirect_uri": s.keycloak_redirect_uri,
        "login_url": "/api/v1/auth/keycloak/login",
    }


@router.get("/login", summary="Start the Keycloak login redirect")
def login(
    redirect_uri: str | None = Query(default=None, max_length=2048),
):
    if not keycloak_service.is_enabled():
        raise HTTPException(status_code=503, detail="Keycloak is not enabled.")

    target = (redirect_uri or DEFAULT_APP_REDIRECT).strip()
    if not keycloak_service.is_allowed_redirect(target):
        raise HTTPException(status_code=400, detail="redirect_uri is not allowed.")

    state = keycloak_service.build_state(target)
    return RedirectResponse(
        keycloak_service.auth_url(_settings().keycloak_redirect_uri, state),
        status_code=302,
    )


@router.get("/callback", summary="Keycloak authorization-code callback")
def callback(
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=512),
    error_description: str | None = Query(default=None, max_length=1024),
    db: Session = Depends(get_db),
):
    if error:
        detail = error_description or error
        raise HTTPException(status_code=401, detail=f"Keycloak login failed: {detail}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state.")

    target = keycloak_service.parse_state(state)
    token_response = keycloak_service.exchange_code(
        code, _settings().keycloak_redirect_uri
    )
    _user, tokens = _complete_login(db, token_response)
    return _redirect_with_tokens(target, tokens)


@router.post("/exchange", summary="Exchange a Keycloak code from a native app")
def exchange(body: KeycloakExchange, db: Session = Depends(get_db)):
    if not keycloak_service.is_enabled():
        raise HTTPException(status_code=503, detail="Keycloak is not enabled.")
    token_response = keycloak_service.exchange_code(
        body.code, body.redirect_uri, body.code_verifier
    )
    _user, tokens = _complete_login(db, token_response)
    return tokens


@router.post("/refresh", summary="Refresh a Keycloak session and re-mint local tokens")
def refresh_tokens(body: KeycloakRefresh, db: Session = Depends(get_db)):
    if not keycloak_service.is_enabled():
        raise HTTPException(status_code=503, detail="Keycloak is not enabled.")
    token_response = keycloak_service.refresh(body.refresh_token)
    _user, tokens = _complete_login(db, token_response)
    return tokens


@router.get("/me", summary="Current identity (local JWT or Keycloak token)")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    identity = (
        db.query(KeycloakIdentity)
        .filter(KeycloakIdentity.user_id == str(user.id))
        .first()
    )
    return {
        "user_id": str(user.id),
        "email": user.email,
        "keycloak": identity is not None,
        "keycloak_sub": identity.sub if identity is not None else None,
    }


@router.get("/logout", summary="Keycloak single sign-out redirect")
def logout(
    redirect_uri: str | None = Query(default=None, max_length=2048),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    if user is not None:
        keycloak_service.delete_tokens(db, str(user.id))
    target = (redirect_uri or DEFAULT_APP_REDIRECT).strip()
    if not keycloak_service.is_allowed_redirect(target):
        raise HTTPException(status_code=400, detail="redirect_uri is not allowed.")
    return RedirectResponse(keycloak_service.logout_url(target), status_code=302)
