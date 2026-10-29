"""routers/auth.py — Spotify OAuth flow."""
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import UserRegister, UserLogin, TokenRefresh
from ..services.auth_service import (
    build_auth_url, exchange_code, save_token, delete_token,
    get_valid_token, is_authenticated, validate_oauth_state,
)
from ..services import user_auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head><title>Spotify Auth</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0c0b09; color: #ede8df;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .card { background: #1b1916; border: 1px solid #2e2a22; border-radius: 10px;
          padding: 2.5rem 3rem; text-align: center; }
  h2 { margin: 1rem 0 0.5rem; } p { color: #9a9080; font-size: 0.9rem; }
</style></head>
<body><div class="card">
  <div style="font-size:2.5rem">✓</div>
  <h2>Signed in to Spotify</h2>
  <p>You can close this window.</p>
</div>
<script>
  if (window.opener) {
    window.opener.postMessage({ type: 'SPOTIFY_AUTH_SUCCESS' }, '*');
    setTimeout(() => window.close(), 1200);
  }
</script></body></html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html>
<head><title>Auth Error</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0c0b09; color: #ede8df;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
  .card {{ background: #1b1916; border: 1px solid #5a2a2a; border-radius: 10px;
          padding: 2.5rem 3rem; text-align: center; }}
  h2 {{ color: #c85a4a; }} p {{ color: #9a9080; font-size: 0.85rem; }}
</style></head>
<body><div class="card">
  <div style="font-size:2.5rem">✕</div>
  <h2>Authorization failed</h2>
  <p>{reason}</p>
</div></body></html>"""


@router.post("/register", summary="Register a user account")
def register(body: UserRegister, db: Session = Depends(get_db)):
    try:
        user = user_auth_service.register_user(db, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return user_auth_service.issue_tokens(user)


@router.post("/login", summary="Log in with email and password")
def login(body: UserLogin, db: Session = Depends(get_db)):
    user = user_auth_service.authenticate_user(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return user_auth_service.issue_tokens(user)


@router.post("/refresh", summary="Refresh an access token")
def refresh(body: TokenRefresh):
    try:
        payload = user_auth_service.decode_token(body.refresh_token, "refresh")
    except Exception:
        raise HTTPException(status_code=401, detail="invalid refresh token")
    access = user_auth_service.create_access_token(payload["sub"], payload["email"])
    return {"access_token": access, "token_type": "bearer"}


@router.get("/status", summary="Check user authentication status")
def status(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        return {"authenticated": False, "user_id": None, "email": None}
    token = authorization.split(" ", 1)[1]
    try:
        payload = user_auth_service.decode_token(token, "access")
    except Exception:
        return {"authenticated": False, "user_id": None, "email": None}
    user = user_auth_service.get_user_by_id(db, payload["sub"])
    if user is None:
        return {"authenticated": False, "user_id": None, "email": None}
    return {"authenticated": True, "user_id": str(user.id), "email": user.email}


@router.get("/me", summary="Current user")
def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email, "created_at": user.created_at.isoformat()}


@router.get("/callback", response_class=HTMLResponse, include_in_schema=False)
def callback(code: str = None, error: str = None, state: str = None):
    if error or not code:
        return HTMLResponse(_ERROR_HTML.format(reason=error or "no code received"), status_code=400)
    owner_id = validate_oauth_state(state)
    if not owner_id:
        return HTMLResponse(_ERROR_HTML.format(reason="invalid or expired state"), status_code=400)
    try:
        save_token(exchange_code(code), owner_id)
        return HTMLResponse(_SUCCESS_HTML)
    except Exception as e:
        return HTMLResponse(_ERROR_HTML.format(reason=str(e)), status_code=500)


def _unlink_spotify(user: User) -> dict:
    deleted = delete_token(str(user.id))
    return {"message": "Spotify unlinked." if deleted else "Spotify was not linked."}


@router.delete("/token", summary="Unlink Spotify")
def sign_out(user: User = Depends(get_current_user)):
    return _unlink_spotify(user)


@router.post("/logout", summary="Log out (client discards JWT)")
def logout(user: User = Depends(get_current_user)):
    # JWT logout is client-side; do not unlink this user's Spotify account.
    return {"message": "Logged out."}


@router.get("/login", summary="Get Spotify OAuth URL (legacy alias)")
def login_spotify_legacy(user: User = Depends(get_current_user)):
    # The old Python web UI used GET /auth/login for Spotify OAuth. Keep it
    # working while POST /auth/login is the multi-user JWT login.
    return {"auth_url": build_auth_url(str(user.id))}


@router.get("/spotify/login", summary="Get Spotify OAuth URL (client alias)")
def spotify_login(user: User = Depends(get_current_user)):
    return {"auth_url": build_auth_url(str(user.id))}


@router.delete("/spotify", summary="Unlink Spotify (client alias)")
def spotify_unlink(user: User = Depends(get_current_user)):
    return _unlink_spotify(user)