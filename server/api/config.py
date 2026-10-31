"""config.py - environment-backed settings for optional integrations.

Kept deliberately small and dependency-free (os.environ only) so it works in
the Docker image, the native dev server and the PyInstaller desktop build
without an extra settings library.

Keycloak has two base URLs on purpose:

* ``KEYCLOAK_INTERNAL_URL`` - what the API container uses for back-channel
  calls (token, JWKS, userinfo). In Docker that is
  ``http://host.docker.internal:8083/authKeycloak``.
* ``KEYCLOAK_PUBLIC_URL`` - what a browser/phone uses for the front channel
  (authorization + logout). In Docker that is the LAN address.

``KEYCLOAK_ISSUER`` must match the ``iss`` claim Keycloak actually emits. It
is derived from Keycloak's ``KC_HOSTNAME`` (``http://localhost:8083/...`` in
the bundled stack), not from the URL the browser used, so it stays stable for
both PC and phone clients.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # ── Keycloak ────────────────────────────────────────────────────────────
    keycloak_enabled: bool
    keycloak_realm: str
    keycloak_internal_url: str
    keycloak_public_url: str
    keycloak_issuer: str
    keycloak_client_id: str
    keycloak_client_secret: str
    keycloak_redirect_uri: str
    keycloak_verify_ssl: bool
    keycloak_jwks_ttl: float
    keycloak_allowed_redirects: tuple[str, ...]

    # ── Open WebUI per-user identity ────────────────────────────────────────
    openwebui_trusted_auth: bool
    openwebui_trusted_header: str
    openwebui_trusted_name_header: str

    # ── Helpers ─────────────────────────────────────────────────────────────
    @property
    def realm_url_internal(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.keycloak_realm}"

    @property
    def realm_url_public(self) -> str:
        return f"{self.keycloak_public_url}/realms/{self.keycloak_realm}"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.realm_url_public}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self.realm_url_internal}/protocol/openid-connect/token"

    @property
    def jwks_url(self) -> str:
        return f"{self.realm_url_internal}/protocol/openid-connect/certs"

    @property
    def userinfo_url(self) -> str:
        return f"{self.realm_url_internal}/protocol/openid-connect/userinfo"

    @property
    def end_session_endpoint(self) -> str:
        return f"{self.realm_url_public}/protocol/openid-connect/logout"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    realm = _env("KEYCLOAK_REALM", "open-webui")
    internal = _env("KEYCLOAK_INTERNAL_URL", "http://localhost:8083/authKeycloak").rstrip("/")
    public = _env("KEYCLOAK_PUBLIC_URL", internal).rstrip("/")
    issuer = _env("KEYCLOAK_ISSUER", f"{internal}/realms/{realm}").rstrip("/")

    client_id = _env("KEYCLOAK_CLIENT_ID", "open-webui")
    client_secret = _env("KEYCLOAK_CLIENT_SECRET", "")

    # Explicit opt-in keeps deployments without Keycloak on the old behaviour.
    enabled = _env_bool("KEYCLOAK_ENABLED", False)

    return Settings(
        keycloak_enabled=enabled,
        keycloak_realm=realm,
        keycloak_internal_url=internal,
        keycloak_public_url=public,
        keycloak_issuer=issuer,
        keycloak_client_id=client_id,
        keycloak_client_secret=client_secret,
        keycloak_redirect_uri=_env(
            "KEYCLOAK_REDIRECT_URI",
            "http://localhost:8000/api/v1/auth/keycloak/callback",
        ),
        keycloak_verify_ssl=_env_bool("KEYCLOAK_VERIFY_SSL", True),
        keycloak_jwks_ttl=_env_float("KEYCLOAK_JWKS_TTL", 300.0),
        keycloak_allowed_redirects=tuple(
            part.strip()
            for part in _env(
                "KEYCLOAK_ALLOWED_REDIRECTS",
                "http://localhost:8888,http://127.0.0.1:8888,"
                "http://localhost:3000,http://127.0.0.1:3000",
            ).split(",")
            if part.strip()
        ),
        openwebui_trusted_auth=_env_bool("OPENWEBUI_TRUSTED_AUTH", False),
        openwebui_trusted_header=_env(
            "OPENWEBUI_TRUSTED_HEADER", "X-OWUI-Trusted-Email"
        ),
        openwebui_trusted_name_header=_env(
            "OPENWEBUI_TRUSTED_NAME_HEADER", "X-OWUI-Trusted-Name"
        ),
    )


def reset_settings_cache() -> None:
    """Test helper: forget cached settings after monkeypatching env vars."""
    get_settings.cache_clear()
