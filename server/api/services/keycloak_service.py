"""services/keycloak_service.py - Keycloak OIDC for the local API (Phase 3).

Responsibilities
----------------
* Validate Keycloak access tokens (RS256, JWKS cached with a TTL).
* Exchange authorization codes / refresh tokens against the token endpoint.
* Map a Keycloak ``sub`` to the local ``users`` row that owns the library, so
  every existing /api/v1 route keeps working with a Keycloak bearer token.
* Persist the user's Keycloak tokens server-side for Phase 4 (Open WebUI
  on-behalf-of calls). Tokens are never logged or returned to clients.

Synchronous on purpose: FastAPI runs sync dependencies in its threadpool and
the rest of this codebase already uses ``requests``.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import jwt
import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import KeycloakIdentity, KeycloakToken, User
from . import user_auth_service

logger = logging.getLogger("keycloak")

CLOCK_SKEW_SECONDS = 30
HTTP_TIMEOUT = 10.0
STATE_TTL_SECONDS = 600

# Custom-scheme callbacks used by the mobile builds. Everything else must be
# an http(s) URL on an allowlisted host.
_CUSTOM_SCHEME_PREFIXES = (
    "com.spotifydashboard.app://",
    "com.spotifydashboard.app.ts://",
)


class KeycloakAuthError(Exception):
    """Keycloak authentication error (turned into a 401 by deps/routers)."""

    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


class KeycloakUnavailable(KeycloakAuthError):
    """Keycloak could not be reached or answered unexpectedly."""

    def __init__(self, message: str):
        super().__init__(message, status_code=503)


# ── JWKS cache ──────────────────────────────────────────────────────────────
_jwks_lock = threading.Lock()
_jwks_cache: dict[str, Any] = {"keys": [], "fetched_at": 0.0}


def _settings() -> Settings:
    return get_settings()


def is_enabled() -> bool:
    s = _settings()
    return bool(s.keycloak_enabled and s.keycloak_client_id)


def _verify_ssl() -> bool:
    return _settings().keycloak_verify_ssl


def _fetch_jwks(force: bool = False) -> dict[str, Any]:
    s = _settings()
    now = time.monotonic()
    with _jwks_lock:
        fresh = (now - _jwks_cache["fetched_at"]) < s.keycloak_jwks_ttl
        if not force and _jwks_cache["keys"] and fresh:
            return _jwks_cache
        try:
            resp = requests.get(s.jwks_url, timeout=HTTP_TIMEOUT, verify=_verify_ssl())
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            # Serve stale keys if Keycloak is briefly unreachable.
            if _jwks_cache["keys"]:
                logger.warning("JWKS refresh failed, using cached keys: %s", exc)
                return _jwks_cache
            raise KeycloakUnavailable(f"Cannot fetch Keycloak JWKS: {exc}") from exc
        keys = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(keys, list) or not keys:
            raise KeycloakUnavailable("Keycloak JWKS response has no keys.")
        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = now
        return _jwks_cache


def _select_key(keys: list[dict[str, Any]], kid: str) -> Optional[dict[str, Any]]:
    for key in keys:
        if key.get("kid") == kid:
            return key
    return None


def validate_token(token: str) -> dict[str, Any]:
    """Validate a Keycloak access token and return its claims."""
    s = _settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise KeycloakAuthError("Malformed bearer token.") from exc

    kid = header.get("kid")
    if not kid:
        raise KeycloakAuthError("Token has no 'kid' header.")
    if header.get("alg") not in {"RS256", "RS384", "RS512"}:
        raise KeycloakAuthError("Unsupported token algorithm.")

    jwks = _fetch_jwks()
    jwk = _select_key(jwks["keys"], kid)
    if jwk is None:
        # Key rotation: refetch once before rejecting.
        jwks = _fetch_jwks(force=True)
        jwk = _select_key(jwks["keys"], kid)
    if jwk is None:
        raise KeycloakAuthError("No matching Keycloak signing key.")

    try:
        claims = jwt.decode(
            token,
            jwt.PyJWK(jwk).key,
            algorithms=[header["alg"]],
            issuer=s.keycloak_issuer,
            options={
                "verify_aud": False,  # Keycloak puts the client in azp, not aud
                "verify_exp": True,
                "verify_iss": True,
                "leeway": CLOCK_SKEW_SECONDS,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise KeycloakAuthError("Keycloak token expired.") from exc
    except jwt.PyJWTError as exc:
        raise KeycloakAuthError(f"Keycloak token rejected: {exc}") from exc

    authorized_party = claims.get("azp")
    audience = claims.get("aud")
    audience_list = audience if isinstance(audience, list) else [audience]
    if authorized_party != s.keycloak_client_id and s.keycloak_client_id not in audience_list:
        raise KeycloakAuthError("Token was issued for a different client.")

    if not claims.get("sub"):
        raise KeycloakAuthError("Token has no subject.")
    return claims


# ── Token endpoint ──────────────────────────────────────────────────────────
def _token_request(payload: dict[str, str]) -> dict[str, Any]:
    s = _settings()
    body = {
        "client_id": s.keycloak_client_id,
        **payload,
    }
    if s.keycloak_client_secret:
        body["client_secret"] = s.keycloak_client_secret
    try:
        resp = requests.post(
            s.token_endpoint,
            data=body,
            timeout=HTTP_TIMEOUT,
            verify=_verify_ssl(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except requests.RequestException as exc:
        raise KeycloakUnavailable(f"Cannot reach Keycloak token endpoint: {exc}") from exc

    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        detail = ""
        if isinstance(data, dict):
            detail = data.get("error_description") or data.get("error") or ""
        raise KeycloakAuthError(
            f"Keycloak token request failed ({resp.status_code})"
            + (f": {detail}" if detail else "")
        )
    if not isinstance(data, dict) or not data.get("access_token"):
        raise KeycloakAuthError("Keycloak returned no access token.")
    return data


def exchange_code(code: str, redirect_uri: str, code_verifier: str | None = None) -> dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier
    return _token_request(payload)


def refresh(refresh_token: str) -> dict[str, Any]:
    return _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


def userinfo(access_token: str) -> dict[str, Any]:
    s = _settings()
    try:
        resp = requests.get(
            s.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT,
            verify=_verify_ssl(),
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise KeycloakUnavailable(f"Cannot fetch Keycloak userinfo: {exc}") from exc
    return data if isinstance(data, dict) else {}


# ── Front-channel URLs ──────────────────────────────────────────────────────
def auth_url(redirect_uri: str, state: str) -> str:
    s = _settings()
    query = urlencode(
        {
            "client_id": s.keycloak_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
    )
    return f"{s.authorization_endpoint}?{query}"


def logout_url(post_logout_redirect_uri: str | None = None) -> str:
    s = _settings()
    if not post_logout_redirect_uri:
        return s.end_session_endpoint
    query = urlencode(
        {
            "client_id": s.keycloak_client_id,
            "post_logout_redirect_uri": post_logout_redirect_uri,
        }
    )
    return f"{s.end_session_endpoint}?{query}"


# ── State (stateless, signed, short-lived) ──────────────────────────────────
def build_state(redirect_uri: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "type": "kc_state",
        "redirect_uri": redirect_uri,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=STATE_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, user_auth_service.JWT_SECRET,
                      algorithm=user_auth_service.JWT_ALGORITHM)


def parse_state(state: str) -> str:
    try:
        payload = jwt.decode(
            state,
            user_auth_service.JWT_SECRET,
            algorithms=[user_auth_service.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise KeycloakAuthError("Invalid or expired login state.") from exc
    if payload.get("type") != "kc_state":
        raise KeycloakAuthError("Invalid login state.")
    redirect_uri = payload.get("redirect_uri")
    if not isinstance(redirect_uri, str) or not redirect_uri:
        raise KeycloakAuthError("Login state has no redirect target.")
    return redirect_uri


def is_allowed_redirect(uri: str) -> bool:
    """Only our own apps may receive tokens from the callback."""
    if not uri:
        return False
    if any(uri.startswith(prefix) for prefix in _CUSTOM_SCHEME_PREFIXES):
        return True
    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    s = _settings()
    allowed = {
        (urlparse(url).hostname or "").lower()
        for url in s.keycloak_allowed_redirects
        if url
    }
    return host in allowed


# ── Local user mapping ──────────────────────────────────────────────────────
def _identity_email(claims: dict[str, Any]) -> str:
    email = claims.get("email") or claims.get("preferred_username")
    if not email or not isinstance(email, str):
        raise KeycloakAuthError("Keycloak token has no email claim.")
    return email.strip().lower()


def ensure_local_user(db: Session, claims: dict[str, Any]) -> User:
    """Find or create the local library owner for a Keycloak subject."""
    sub = str(claims["sub"])
    email = _identity_email(claims)
    now = datetime.now(timezone.utc)

    identity = db.get(KeycloakIdentity, sub)
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is not None:
            if identity.email != email:
                identity.email = email
            identity.last_login_at = now
            db.commit()
            return user
        # Stale mapping (user deleted): drop it and re-link below.
        db.delete(identity)
        db.commit()

    user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )
    if user is None:
        user = User(
            email=email,
            # Unusable local password: this account signs in via Keycloak only.
            password_hash=user_auth_service.hash_password(
                secrets.token_urlsafe(32)
            ),
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                raise KeycloakAuthError("Could not provision the local user.")

    db.add(KeycloakIdentity(
        sub=sub,
        user_id=user.id,
        email=email,
        last_login_at=now,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(KeycloakIdentity, sub)
        if existing is None:
            raise KeycloakAuthError("Could not link the Keycloak identity.")
        user = db.get(User, existing.user_id)
        if user is None:
            raise KeycloakAuthError("Linked user no longer exists.")
    return user


# ── Token storage (Phase 4) ─────────────────────────────────────────────────
def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def save_tokens(db: Session, user_id: str, token_response: dict[str, Any]) -> None:
    access = token_response.get("access_token")
    if not access:
        return
    expires_in = token_response.get("expires_in")
    expires_at = None
    if expires_in:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            expires_at = None

    row = db.get(KeycloakToken, user_id)
    if row is None:
        row = KeycloakToken(user_id=user_id, access_token=access)
        db.add(row)
    row.access_token = access
    if token_response.get("refresh_token"):
        row.refresh_token = token_response["refresh_token"]
    row.expires_at = expires_at
    row.scope = token_response.get("scope")
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


def get_valid_access_token(db: Session, user_id: str) -> str | None:
    """Return a non-expired Keycloak access token, refreshing when needed."""
    row = db.get(KeycloakToken, user_id)
    if row is None:
        return None
    expires_at = _as_utc(row.expires_at)
    if expires_at is None or expires_at > datetime.now(timezone.utc) + timedelta(seconds=30):
        return row.access_token
    if not row.refresh_token:
        return None
    try:
        refreshed = refresh(row.refresh_token)
    except KeycloakAuthError as exc:
        logger.info("Keycloak refresh failed for user %s: %s", user_id, exc)
        return None
    save_tokens(db, user_id, refreshed)
    return refreshed.get("access_token")


def delete_tokens(db: Session, user_id: str) -> None:
    row = db.get(KeycloakToken, user_id)
    if row is not None:
        db.delete(row)
        db.commit()
