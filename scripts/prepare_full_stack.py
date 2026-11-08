#!/usr/bin/env python3
"""Prepare the reSpotIt full stack before ``docker compose up``.

The one-click launcher must be safe to run more than once.  This script:

* keeps an existing ``.env`` (rotating DB passwords on every run breaks
  existing Postgres volumes);
* points the API's trusted-header exchange at the internal ``open-webui-2``
  instance, never the public one;
* makes ``OAUTH_CLIENT_SECRET`` / ``KEYCLOAK_CLIENT_SECRET`` match the
  Keycloak client secret (realm export, or the running Keycloak DB);
* removes the obsolete ``WEBUI_AUTH_TRUSTED_*`` variables from ``.env``;
* replaces the legacy nginx ``location /api/`` block with ``/respotit/`` so
  Open WebUI's own ``/api/config`` is not shadowed;
* appends the local mkcert root / Local CA to Open WebUI's CA bundle so the
  OIDC backchannel can verify ``https://localhost``.

It never prints secret values.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STACK = ROOT / "OpenWebUI-stack"
CERTS = ROOT / "certs"
ENV_FILE = ROOT / ".env"


def _find_backup() -> Path:
    """Support both the old sibling layout and the current backups/ layout."""
    candidates = (
        ROOT.parent / "reSpotIt-local-server-app-clean-backup-2",
        ROOT.parent / "backups" / "reSpotIt-local-server-app-clean-backup-2",
        ROOT.parent.parent / "backups" / "reSpotIt-local-server-app-clean-backup-2",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


BACKUP = _find_backup()

COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "docker-compose.full.yml",
]

DEFAULT_OAUTH_SECRET = "open-webui-secret"
MANAGED_MARKER = "# Managed by scripts/prepare_full_stack.py"


# ── small helpers ───────────────────────────────────────────────────────────
def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def newline_for(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def generate_hex() -> str:
    return secrets.token_hex(32)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def upsert_env(path: Path, updates: dict[str, str], remove: tuple[str, ...] = ()) -> None:
    """Update keys in place, preserving comments and unrelated values."""
    text = read_text(path)
    nl = newline_for(text)
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remove:
            continue
        if key in updates:
            if key in seen:
                continue
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(raw)

    missing = [key for key in updates if key not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append(MANAGED_MARKER)
        for key in missing:
            out.append(f"{key}={updates[key]}")

    write_text(path, nl.join(out) + (nl if out else ""))


# ── assets ──────────────────────────────────────────────────────────────────
def copy_missing_dir(src: Path, dst: Path, label: str) -> None:
    if dst.exists():
        return
    if not src.exists():
        print(f"[warn] {label}: {dst} is missing and backup {src} was not found")
        return
    shutil.copytree(src, dst)
    print(f"[ok] {label}: copied from backup")


REQUIRED_FILES = (
    "certs/ca/rootCA.pem",
    "certs/server.pem",
    "certs/server-key.pem",
    "OpenWebUI-stack/nginx/nginx.conf",
    "OpenWebUI-stack/nginx/index.html",
    "OpenWebUI-stack/ssl/server.crt",
    "OpenWebUI-stack/ssl/server.key",
    "OpenWebUI-stack/ssl/ca.crt",
    "OpenWebUI-stack/ssl/ca-bundle.crt",
    "OpenWebUI-stack/keycloak/realm-export.json",
    "OpenWebUI-stack/openwebui-entrypoint.sh",
    "OpenWebUI-stack/respotit-mcp/register_openwebui.py",
)


def ensure_required_files() -> None:
    """Restore individual files that are missing from an existing asset tree."""
    for rel in REQUIRED_FILES:
        dst = ROOT / rel
        if dst.exists():
            continue
        src = BACKUP / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"[ok] asset: restored {rel}")


def ensure_assets() -> None:
    copy_missing_dir(BACKUP / "OpenWebUI-stack", STACK, "OpenWebUI-stack")
    copy_missing_dir(BACKUP / "certs", CERTS, "certs")
    ensure_required_files()
    if not STACK.exists():
        print("[error] OpenWebUI-stack is required for the full stack.")
        print("        Place it next to docker-compose.full.yml, or keep the")
        print("        reSpotIt-local-server-app-clean-backup-2 workspace nearby.")
        sys.exit(1)


# ── nginx ───────────────────────────────────────────────────────────────────
NGINX_BLOCK = """        # reSpotIt API (HTTPS upstream; verification off because cert is for
        # localhost / LAN IP, not the "api" service name).
        # Do NOT mount this at /api/: Open WebUI's own backend uses /api/
        # (e.g. /api/config), and shadowing it breaks the UI with
        # "Backend Required". Use the /respotit/ prefix instead.
        location /respotit/ {
            proxy_pass         https://api:8000/;
            proxy_ssl_verify   off;
            proxy_set_header   Host              $host;
            proxy_set_header   X-Real-IP         $remote_addr;
            proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
        }"""


def patch_nginx() -> None:
    path = STACK / "nginx" / "nginx.conf"
    if not path.exists():
        print("[warn] nginx: nginx.conf is missing; skipping")
        return

    text = read_text(path)
    if "location /respotit/" in text:
        if "location /api/" not in text:
            print("[ok] nginx: /respotit/ already configured")
            return
        # Remove the legacy block but keep the fixed one.
        text, count = re.subn(
            r"(?ms)^[ \t]*location\s+/api/\s*\{.*?^[ \t]*\}",
            "",
            text,
            count=1,
        )
        if count:
            write_text(path, text)
            print("[ok] nginx: removed legacy /api/ block")
        else:
            print("[warn] nginx: found both /api/ and /respotit/ but could not remove /api/")
        return

    text, count = re.subn(
        r"(?ms)^[ \t]*location\s+/api/\s*\{.*?^[ \t]*\}",
        NGINX_BLOCK,
        text,
        count=1,
    )
    if not count:
        print("[warn] nginx: could not find the legacy /api/ block; check nginx.conf")
        return
    write_text(path, text)
    print("[ok] nginx: replaced /api/ with /respotit/")


# ── CA bundle ───────────────────────────────────────────────────────────────
def extract_pem(text: str) -> str:
    match = re.search(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        text,
        re.S,
    )
    return match.group(0).strip() if match else ""


def patch_ca_bundle() -> None:
    bundle = STACK / "ssl" / "ca-bundle.crt"
    if not bundle.exists():
        backup_bundle = BACKUP / "OpenWebUI-stack" / "ssl" / "ca-bundle.crt"
        if backup_bundle.exists():
            shutil.copy2(backup_bundle, bundle)
            print("[ok] ca-bundle: copied from backup")
        else:
            try:
                import certifi  # type: ignore

                text = Path(certifi.where()).read_text(encoding="utf-8")
            except Exception:
                text = ""
            write_text(bundle, text)
            print("[warn] ca-bundle: created from certifi; local CAs will be appended")

    text = read_text(bundle)
    added: list[str] = []
    for path in (CERTS / "ca" / "rootCA.pem", STACK / "ssl" / "ca.crt"):
        if not path.exists():
            continue
        pem = extract_pem(read_text(path))
        if not pem:
            continue
        body = pem.split("-----BEGIN CERTIFICATE-----", 1)[1]
        body = body.split("-----END CERTIFICATE-----", 1)[0].strip()
        if body in text:
            continue
        if not text.endswith("\n"):
            text += "\n"
        text += pem + "\n"
        added.append(path.name)

    if added:
        write_text(bundle, text)
        print(f"[ok] ca-bundle: added {', '.join(added)}")
    else:
        print("[ok] ca-bundle: local CAs present")


# ── OAuth client secret ─────────────────────────────────────────────────────
def realm_client_secret() -> str:
    path = STACK / "keycloak" / "realm-export.json"
    if not path.exists():
        return DEFAULT_OAUTH_SECRET
    try:
        data = json.loads(read_text(path))
    except (OSError, ValueError) as exc:
        print(f"[warn] Keycloak realm export could not be read: {exc}")
        return DEFAULT_OAUTH_SECRET
    for client in data.get("clients", []):
        if client.get("clientId") == "open-webui" and client.get("secret"):
            return str(client["secret"])
    return DEFAULT_OAUTH_SECRET


def running_keycloak_secret(values: dict[str, str]) -> str | None:
    """Read the live Keycloak client secret when the DB is already running."""
    ps = run(COMPOSE + ["ps", "-q", "keycloak-db"])
    if ps.returncode != 0 or not ps.stdout.strip():
        return None
    container = ps.stdout.strip().splitlines()[0].strip()
    user = values.get("KEYCLOAK_DB_USER", "keycloak")
    sql = (
        "select c.secret from client c join realm r on c.realm_id=r.id "
        "where r.name='open-webui' and c.client_id='open-webui';"
    )
    result = run(
        ["docker", "exec", "-i", container, "psql", "-U", user, "-d", "keycloak", "-tA", "-c", sql]
    )
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


def oauth_client_secret(values: dict[str, str]) -> str:
    live = running_keycloak_secret(values)
    if live:
        print("[ok] OAuth client secret: matched running Keycloak client")
        return live
    secret = realm_client_secret()
    print("[ok] OAuth client secret: matched Keycloak realm export")
    return secret


# ── .env ────────────────────────────────────────────────────────────────────
def render_env(values: dict[str, str]) -> str:
    def block(title: str, keys: list[str]) -> list[str]:
        lines = [f"# {title}"]
        for key in keys:
            lines.append(f"{key}={values.get(key, '')}")
        lines.append("")
        return lines

    lines: list[str] = [
        "# reSpotIt local server (auto-generated by scripts/prepare_full_stack.py)",
        "",
    ]
    lines += block("Core", [
        "REDIRECT_URI", "PUBLIC_BASE_URL", "SSL_ENABLED",
        "CORS_ALLOW_ORIGIN", "FORWARDED_ALLOW_IPS",
    ])
    lines += block("Spotify (fill in manually)", [
        "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
    ])
    lines += block("Keycloak / OpenWebUI OIDC", [
        "KEYCLOAK_REALM", "KEYCLOAK_ADMIN", "KEYCLOAK_ADMIN_PASSWORD",
        "KEYCLOAK_DB_USER", "KEYCLOAK_DB_PASSWORD", "KEYCLOAK_ENABLED",
        "KEYCLOAK_CLIENT_ID", "KEYCLOAK_CLIENT_SECRET", "KEYCLOAK_HOSTNAME",
        "OPENID_PROVIDER_URL", "OPENID_REDIRECT_URI", "OAUTH_PROVIDER_NAME",
        "OAUTH_SCOPES", "OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET",
        "OAUTH_AUTO_SIGNUP", "OAUTH_MERGE_ACCOUNTS_BY_EMAIL",
        "ENABLE_OAUTH_SIGNUP",
    ])
    lines += block("OpenWebUI database", [
        "OPENWEBUI_DB_USER", "OPENWEBUI_DB_PASSWORD", "OPENWEBUI_DB_NAME",
        "WEBUI_AUTH", "DEFAULT_USER_ROLE", "WEBUI_SECRET_KEY",
    ])
    lines += block("Spotify MCP", [
        "MCP_API_KEY",
    ])
    lines += block("reSpotIt MCP service account", [
        "RESPOTIT_MCP_EMAIL", "RESPOTIT_MCP_PASSWORD", "RESPOTIT_MCP_USER_ID",
        "RESPOTIT_MCP_API_URL", "RESPOTIT_MCP_API_VERIFY_TLS",
        "RESPOTIT_MCP_TOKEN", "RESPOTIT_MCP_URL",
    ])
    lines += block("OpenWebUI integration", [
        "OPENWEBUI_TRUSTED_AUTH", "OPENWEBUI_URL",
        "OPENWEBUI_TRUSTED_HEADER", "OPENWEBUI_TRUSTED_NAME_HEADER",
    ])
    lines += block("External model endpoint (llama-server)", [
        "OPENAI_API_BASE_URL", "OPENAI_API_KEY",
    ])
    lines += block("Telemetry", [
        "SCARF_NO_ANALYTICS", "DO_NOT_TRACK", "ANONYMIZED_TELEMETRY",
    ])
    return "\n".join(lines)


def fresh_env_values(secret: str) -> dict[str, str]:
    return {
        "REDIRECT_URI": "https://127.0.0.1:8000/api/v1/auth/callback",
        "PUBLIC_BASE_URL": "https://127.0.0.1:8000",
        "SSL_ENABLED": "true",
        "CORS_ALLOW_ORIGIN": "*",
        "FORWARDED_ALLOW_IPS": "*",
        "SPOTIFY_CLIENT_ID": "",
        "SPOTIFY_CLIENT_SECRET": "",
        "KEYCLOAK_REALM": "open-webui",
        "KEYCLOAK_ADMIN": "admin",
        "KEYCLOAK_ADMIN_PASSWORD": generate_token(),
        "KEYCLOAK_DB_USER": "keycloak",
        "KEYCLOAK_DB_PASSWORD": generate_token(),
        "KEYCLOAK_ENABLED": "true",
        "KEYCLOAK_CLIENT_ID": "open-webui",
        "KEYCLOAK_CLIENT_SECRET": secret,
        "KEYCLOAK_HOSTNAME": "https://localhost/authKeycloak",
        "OPENID_PROVIDER_URL": "https://localhost/authKeycloak/realms/open-webui/.well-known/openid-configuration",
        "OPENID_REDIRECT_URI": "https://localhost/oauth/oidc/callback",
        "OAUTH_PROVIDER_NAME": "Keycloak",
        "OAUTH_SCOPES": "openid email profile",
        "OAUTH_CLIENT_ID": "open-webui",
        "OAUTH_CLIENT_SECRET": secret,
        "OAUTH_AUTO_SIGNUP": "true",
        "OAUTH_MERGE_ACCOUNTS_BY_EMAIL": "true",
        "ENABLE_OAUTH_SIGNUP": "true",
        "OPENWEBUI_DB_USER": "openwebui",
        "OPENWEBUI_DB_PASSWORD": generate_token(),
        "OPENWEBUI_DB_NAME": "openwebui",
        "WEBUI_AUTH": "true",
        "DEFAULT_USER_ROLE": "user",
        "WEBUI_SECRET_KEY": generate_hex(),
        "MCP_API_KEY": generate_token(),
        "RESPOTIT_MCP_EMAIL": "mcp-service@respotit.local",
        "RESPOTIT_MCP_PASSWORD": generate_token(),
        "RESPOTIT_MCP_USER_ID": "",
        "RESPOTIT_MCP_API_URL": "https://api:8000",
        "RESPOTIT_MCP_API_VERIFY_TLS": "false",
        "RESPOTIT_MCP_TOKEN": generate_token(),
        "RESPOTIT_MCP_URL": "http://respotit-mcp:8000/mcp",
        "OPENWEBUI_TRUSTED_AUTH": "true",
        "OPENWEBUI_URL": "http://open-webui-2:8080",
        "OPENWEBUI_TRUSTED_HEADER": "X-OWUI-Trusted-Email",
        "OPENWEBUI_TRUSTED_NAME_HEADER": "X-OWUI-Trusted-Name",
        "OPENAI_API_BASE_URL": "http://host.docker.internal:8080/v1",
        "OPENAI_API_KEY": "local",
        "SCARF_NO_ANALYTICS": "true",
        "DO_NOT_TRACK": "true",
        "ANONYMIZED_TELEMETRY": "false",
    }


def ensure_env() -> None:
    if not ENV_FILE.exists():
        secret = realm_client_secret()
        write_text(ENV_FILE, render_env(fresh_env_values(secret)))
        print("[ok] .env: generated with random secrets")
        return

    values = parse_env(read_text(ENV_FILE))
    secret = oauth_client_secret(values)

    updates: dict[str, str] = {
        "OPENWEBUI_URL": "http://open-webui-2:8080",
        "OPENWEBUI_TRUSTED_AUTH": "true",
        "OPENWEBUI_TRUSTED_HEADER": values.get("OPENWEBUI_TRUSTED_HEADER", "X-OWUI-Trusted-Email"),
        "OPENWEBUI_TRUSTED_NAME_HEADER": values.get("OPENWEBUI_TRUSTED_NAME_HEADER", "X-OWUI-Trusted-Name"),
        "OAUTH_CLIENT_ID": values.get("OAUTH_CLIENT_ID", "open-webui"),
        "OAUTH_CLIENT_SECRET": secret,
        "KEYCLOAK_CLIENT_ID": values.get("KEYCLOAK_CLIENT_ID", "open-webui"),
        "KEYCLOAK_CLIENT_SECRET": secret,
        "KEYCLOAK_ENABLED": values.get("KEYCLOAK_ENABLED", "true"),
        "RESPOTIT_MCP_URL": values.get("RESPOTIT_MCP_URL", "http://respotit-mcp:8000/mcp"),
    }

    # Only fill values that are missing or still placeholders.  Never rotate
    # DB passwords on an existing .env: the Postgres volumes already hold them.
    for key, generator in (
        ("WEBUI_SECRET_KEY", generate_hex),
        ("MCP_API_KEY", generate_token),
        ("RESPOTIT_MCP_TOKEN", generate_token),
        ("RESPOTIT_MCP_PASSWORD", generate_token),
    ):
        current = values.get(key, "")
        if not current or current == "change-me":
            updates[key] = generator()

    # The backup workspace is the canonical source for the Spotify app id and
    # the local certs.  An older one-click generated an .env with empty
    # SPOTIFY_CLIENT_ID, which makes token refresh fail with HTTP 400.  Fill
    # only missing values; never overwrite what the user already set.
    backup_values = parse_env(read_text(BACKUP / ".env"))
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        if values.get(key, "").strip():
            continue
        inherited = backup_values.get(key, "").strip()
        if inherited:
            updates[key] = inherited
            print(f"[ok] .env: filled {key} from the backup workspace")

    upsert_env(
        ENV_FILE,
        updates,
        remove=("WEBUI_AUTH_TRUSTED_EMAIL_HEADER", "WEBUI_AUTH_TRUSTED_NAME_HEADER"),
    )
    print("[ok] .env: preserved existing secrets; updated OAuth/OpenWebUI settings")


def main() -> int:
    print("reSpotIt full-stack prepare")
    ensure_assets()
    patch_nginx()
    patch_ca_bundle()
    ensure_env()
    print("prepare: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
