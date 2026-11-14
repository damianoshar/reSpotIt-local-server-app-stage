#!/usr/bin/env python3
"""Post-start bootstrap for the reSpotIt full stack.

Run after ``docker compose ... up -d``.  It is idempotent and safe on every
start.  The one-click launchers call it automatically.

What it fixes / verifies
------------------------
* waits for api, Open WebUI, Keycloak, nginx and respotit-mcp;
* creates the reSpotIt MCP service account on first run;
* copies the owner's Spotify link to the service account when it has none
  (single-user local stack; the MCP README documents this limitation);
* ensures Open WebUI has an API key for the service account;
* registers/refreshes the reSpotIt MCP connection in Open WebUI and verifies
  the tool list through Open WebUI's own MCP client;
* starts a library sync when the service account has a Spotify token;
* checks the public routes, OIDC discovery, the Keycloak client secret and
  that trusted-header auth is disabled on the public Open WebUI instance.

It never prints secret values.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
STACK = ROOT / "OpenWebUI-stack"

COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "docker-compose.full.yml",
]

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ── helpers ─────────────────────────────────────────────────────────────────
def run(cmd: list[str], timeout: int = 60, input_text: str | None = None):
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        print(f"[error] {ENV_FILE} is missing; run scripts/prepare_full_stack.py first.")
        raise SystemExit(1)
    values: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
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


def json_or_text(raw: str):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def request(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    form: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
):
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
            return resp.status, json_or_text(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, json_or_text(exc.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - network errors are reported, not raised
        return None, str(exc)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def container_id(service: str) -> str | None:
    res = run(COMPOSE + ["ps", "-q", service], timeout=30)
    if res.returncode != 0 or not res.stdout.strip():
        return None
    return res.stdout.strip().splitlines()[0].strip()


def restart_nginx() -> None:
    """Re-resolve upstream container IPs after compose recreates services.

    nginx resolves ``upstream openwebui`` once at startup.  When compose
    recreates open-webui/open-webui-2, the old IP can be reassigned to the
    other instance, so nginx starts proxying /api/config to the internal
    trusted-header instance.  A restart refreshes the DNS cache.
    """
    res = run(COMPOSE + ["restart", "nginx-proxy"], timeout=90)
    if res.returncode == 0:
        print("[ok] nginx: restarted (refreshed upstream DNS)")
    else:
        print(f"[warn] nginx: restart failed ({(res.stderr or res.stdout)[:160]})")


# ── public origin (LAN IP) ─────────────────────────────────────────────────
def public_origin(values: dict[str, str]) -> str:
    return (values.get("PUBLIC_ORIGIN") or "https://localhost").rstrip("/")


def _admin_token(origin: str, values: dict[str, str]) -> str | None:
    user = values.get("KEYCLOAK_ADMIN", "admin").strip() or "admin"
    password = values.get("KEYCLOAK_ADMIN_PASSWORD", "").strip()
    if not password:
        print("[warn] Keycloak LAN redirects: KEYCLOAK_ADMIN_PASSWORD is not set")
        return None
    status, data = request(
        "POST",
        f"{origin}/authKeycloak/realms/master/protocol/openid-connect/token",
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": user,
            "password": password,
        },
    )
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        return str(data["access_token"])
    print(f"[warn] Keycloak LAN redirects: admin login failed ({status}: {str(data)[:120]})")
    return None


def ensure_keycloak_redirects(values: dict[str, str]) -> bool:
    """Add the LAN callback to the *live* realm (the export only helps fresh DBs)."""
    origin = public_origin(values)
    lan_ip = values.get("LAN_IP", "").strip()
    realm = values.get("KEYCLOAK_REALM", "open-webui").strip() or "open-webui"
    client_id = values.get("OAUTH_CLIENT_ID", "open-webui").strip() or "open-webui"

    token = _admin_token(origin, values)
    if not token:
        return False

    status, clients = request(
        "GET",
        f"{origin}/authKeycloak/admin/realms/{realm}/clients?clientId={client_id}",
        headers=auth(token),
    )
    if status != 200 or not isinstance(clients, list) or not clients:
        print(f"[warn] Keycloak LAN redirects: client {client_id} not found ({status})")
        return False
    client = clients[0]

    status, full = request(
        "GET",
        f"{origin}/authKeycloak/admin/realms/{realm}/clients/{client['id']}",
        headers=auth(token),
    )
    if status != 200 or not isinstance(full, dict):
        print(f"[warn] Keycloak LAN redirects: client read failed ({status})")
        return False

    redirects = list(full.get("redirectUris") or [])
    origins = list(full.get("webOrigins") or [])
    wanted_redirects = [f"{origin}/oauth/oidc/callback"]
    wanted_origins = [origin]
    if lan_ip:
        wanted_redirects += [
            f"http://{lan_ip}:8888/oauth/oidc/callback",
            f"http://{lan_ip}:8888/api/v1/auth/keycloak/callback",
        ]
        wanted_origins.append(f"http://{lan_ip}:8888")

    changed = False
    for url in wanted_redirects:
        if url not in redirects:
            redirects.append(url)
            changed = True
    for url in wanted_origins:
        if url not in origins:
            origins.append(url)
            changed = True

    if not changed:
        print(f"[ok] Keycloak redirects: {origin} already registered")
        return True

    full["redirectUris"] = redirects
    full["webOrigins"] = origins
    status, data = request(
        "PUT",
        f"{origin}/authKeycloak/admin/realms/{realm}/clients/{client['id']}",
        body=full,
        headers=auth(token),
    )
    if status in (200, 204):
        print(f"[ok] Keycloak redirects: added {origin}")
        return True
    print(f"[warn] Keycloak redirects: update failed ({status}: {str(data)[:160]})")
    return False


def ensure_webui_url(values: dict[str, str]) -> bool:
    """Point Open WebUI's stored ``webui.url`` at the LAN origin.

    Open WebUI persists this value in Postgres and reads it on every OAuth
    redirect, so an old ``https://localhost`` row keeps sending other devices
    to their own localhost even after the environment is fixed.
    """
    origin = public_origin(values)
    db = container_id("openwebui-db")
    if not db:
        print("[warn] Open WebUI URL: openwebui-db container not found")
        return False

    user = values.get("OPENWEBUI_DB_USER", "openwebui")
    name = values.get("OPENWEBUI_DB_NAME", "openwebui")
    select = "select value::text from config where key='webui.url';"

    res = run(["docker", "exec", "-i", db, "psql", "-U", user, "-d", name, "-tA", "-c", select], timeout=30)
    current = (res.stdout or "").strip()
    if res.returncode == 0 and current.strip('"') == origin:
        print(f"[ok] Open WebUI URL: {origin}")
        return True
    if res.returncode != 0:
        print(f"[warn] Open WebUI URL: config read failed ({(res.stderr or '').strip()[:160]})")
        return False

    escaped = origin.replace("'", "''")
    sql = (
        "insert into config (key, value, updated_at) "
        f"values ('webui.url', '\"{escaped}\"'::json, extract(epoch from now())::bigint) "
        "on conflict (key) do update set value=excluded.value, updated_at=excluded.updated_at;"
    )
    res = run(["docker", "exec", "-i", db, "psql", "-U", user, "-d", name, "-c", sql], timeout=30)
    if res.returncode != 0:
        print(f"[warn] Open WebUI URL: update failed ({(res.stderr or '').strip()[:160]})")
        return False

    res = run(["docker", "exec", "-i", db, "psql", "-U", user, "-d", name, "-tA", "-c", select], timeout=30)
    now = (res.stdout or "").strip().strip('"')
    if now == origin:
        print(f"[ok] Open WebUI URL: {origin}")
        return True
    print(f"[warn] Open WebUI URL: read-back mismatch ({now[:80]})")
    return False


def wait_container(service: str, timeout: int) -> str | None:
    deadline = time.time() + timeout
    last = "not created"
    while time.time() < deadline:
        cid = container_id(service)
        if cid:
            res = run(
                [
                    "docker", "inspect", "--format",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                    cid,
                ],
                timeout=15,
            )
            last = (res.stdout or res.stderr).strip() or last
            if last in {"healthy", "running"}:
                print(f"[ok] {service}: {last}")
                return cid
        time.sleep(3)
    print(f"[warn] {service}: not ready after {timeout}s ({last})")
    return None


def wait_http(label: str, url: str, timeout: int, accept: tuple[int, ...] = (200,)) -> bool:
    deadline = time.time() + timeout
    last = "no response"
    while time.time() < deadline:
        status, data = request("GET", url, timeout=10)
        if status in accept:
            print(f"[ok] {label}")
            return True
        last = str(status) if status is not None else str(data)[:120]
        time.sleep(3)
    print(f"[warn] {label}: not ready after {timeout}s (last: {last})")
    return False


def psql(container: str, sql: str) -> tuple[bool, str]:
    res = run(
        ["docker", "exec", "-i", container, "psql", "-U", "spotify", "-d", "spotify", "-tA", "-c", sql],
        timeout=30,
    )
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    return res.returncode == 0, out


def psql_rows(container: str, sql: str) -> list[str]:
    ok, out = psql(container, sql)
    if not ok:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


# ── service account + Spotify link ──────────────────────────────────────────
def login(api_base: str, email: str, password: str):
    status, data = request(
        "POST",
        f"{api_base}/api/v1/auth/login",
        body={"email": email, "password": password},
    )
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        return str(data["access_token"]), data
    return None, data


def ensure_service_account(api_base: str, values: dict[str, str]):
    email = values.get("RESPOTIT_MCP_EMAIL", "mcp-service@respotit.local").strip().lower()
    password = values.get("RESPOTIT_MCP_PASSWORD", "").strip()
    if not password or password == "change-me":
        print("[warn] reSpotIt MCP service account: RESPOTIT_MCP_PASSWORD is not set")
        return None, None

    token, data = login(api_base, email, password)
    if token:
        print("[ok] reSpotIt MCP service account: sign-in ok")
        return token, data

    status, data = request(
        "POST",
        f"{api_base}/api/v1/auth/register",
        body={"email": email, "password": password},
    )
    if status in (200, 201) and isinstance(data, dict) and data.get("access_token"):
        print("[ok] reSpotIt MCP service account: created")
        return str(data["access_token"]), data

    if status == 409:
        token, data = login(api_base, email, password)
        if token:
            print("[ok] reSpotIt MCP service account: sign-in ok after 409")
            return token, data

    print(
        "[warn] reSpotIt MCP service account: sign-in/register failed "
        f"({status}: {str(data)[:160]})"
    )
    print("       If the account already exists with another password, keep the old")
    print("       RESPOTIT_MCP_PASSWORD in .env or recreate the database volume.")
    return None, None


def copy_spotify_token(db: str, service_payload: dict) -> bool:
    uid = str(
        service_payload.get("user_id")
        or (service_payload.get("user") or {}).get("id")
        or ""
    )
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", uid):
        print("[warn] Spotify link: service-account id is missing")
        return False

    rows = psql_rows(
        db,
        "select u.id, u.email, (select count(*) from spotify_tokens t where t.user_id=u.id) "
        "from users u order by u.created_at;",
    )
    users: list[dict[str, object]] = []
    for line in rows:
        parts = line.split("|")
        if len(parts) >= 3:
            try:
                tokens = int(parts[2] or 0)
            except ValueError:
                tokens = 0
            users.append({"id": parts[0], "email": parts[1], "tokens": tokens})

    service = next((u for u in users if u["id"] == uid), None)
    if service and int(service["tokens"]) > 0:
        print("[ok] Spotify link: service account already connected")
        return True

    owners = [u for u in users if u["id"] != uid and int(u["tokens"]) > 0]
    if not owners:
        print("[warn] Spotify link: no account has connected Spotify yet")
        print("       Open http://localhost:8888, connect Spotify, then re-run this script.")
        return False

    owner = owners[0]
    owner_id = str(owner["id"])
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", owner_id):
        print("[warn] Spotify link: owner id has an unexpected shape; skipping copy")
        return False

    sql = (
        "INSERT INTO spotify_tokens "
        "(user_id, access_token, refresh_token, expires_at, created_at, updated_at) "
        f"SELECT '{uid}', access_token, refresh_token, expires_at, now(), now() "
        f"FROM spotify_tokens WHERE user_id = '{owner_id}' "
        "ON CONFLICT (user_id) DO NOTHING;"
    )
    ok, out = psql(db, sql)
    if not ok:
        print(f"[warn] Spotify link: copy failed ({out[:160]})")
        return False
    print("[ok] Spotify link: copied the owner's link to the service account")
    return True


# ── Open WebUI API key + MCP registration ───────────────────────────────────
def ensure_owui_key(api_container: str, service_email: str) -> bool:
    res = run(
        ["docker", "exec", api_container, "sh", "-c",
         "test -s /data/.owui_api_key && echo yes || echo no"],
        timeout=15,
    )
    if "yes" in res.stdout:
        print("[ok] Open WebUI API key: present")
        return True

    code = (
        "import os; os.chdir('/app'); "
        "from api.services import openwebui_service as s; "
        f"k=s.generate_api_key({service_email!r}); "
        "open('/data/.owui_api_key','w').write(k) if k else None; "
        "print('ok' if k else 'fail')"
    )
    res = run(["docker", "exec", api_container, "python", "-c", code], timeout=90)
    if "ok" in res.stdout:
        print("[ok] Open WebUI API key: generated")
        return True
    print("[warn] Open WebUI API key: could not generate (AI assistant stays disabled)")
    return False


def register_mcp(openwebui_container: str, values: dict[str, str]) -> int:
    script = STACK / "respotit-mcp" / "register_openwebui.py"
    if not script.exists():
        print(f"[warn] MCP registration: {script} is missing")
        return 0

    res = run(
        ["docker", "exec", "-i", openwebui_container, "sh", "-c",
         "cat > /tmp/register_openwebui.py"],
        timeout=30,
        input_text=script.read_text(encoding="utf-8"),
    )
    if res.returncode != 0:
        print(f"[warn] MCP registration: could not copy the script ({res.stderr[:160]})")
        return 0

    token = values.get("RESPOTIT_MCP_TOKEN", "").strip()
    if not token:
        print("[warn] MCP registration: RESPOTIT_MCP_TOKEN is empty")
        return 0
    url = values.get("RESPOTIT_MCP_URL", "http://respotit-mcp:8000/mcp").strip()

    # Do not override WEBUI_SECRET_KEY: the container already has it in its
    # environment.  Reading /app/backend/.webui_secret_key is not reliable
    # (the file only exists when the env var is absent).
    res = run(
        [
            "docker", "exec",
            "-w", "/app/backend",
            "-e", "PYTHONPATH=/app/backend",
            "-e", f"MCP_URL={url}",
            "-e", f"MCP_TOKEN={token}",
            openwebui_container,
            "python", "/tmp/register_openwebui.py", "--verify",
        ],
        timeout=120,
    )

    output = ((res.stdout or "") + (res.stderr or "")).strip()
    safe_lines: list[str] = []
    for line in output.splitlines():
        if token and token in line:
            continue
        if line.strip():
            safe_lines.append(line.strip())
    for line in safe_lines:
        print(f"    {line}")

    match = re.search(r"verify tools\s+(\d+)", output)
    count = int(match.group(1)) if match else 0
    if res.returncode == 0 and count > 0:
        print(f"[ok] MCP registration: {count} tools available in Open WebUI")
        return count
    print("[warn] MCP registration: verification did not list tools")
    return 0


# ── sync ────────────────────────────────────────────────────────────────────
def start_sync(api_base: str, token: str) -> bool:
    headers = auth(token)
    status, data = request("GET", f"{api_base}/api/v1/sync/history?limit=10", headers=headers)
    if status == 200 and isinstance(data, dict):
        running = [
            job for job in data.get("data", [])
            if isinstance(job, dict) and job.get("status") in {"pending", "running"}
        ]
        if running:
            print(f"[ok] Library sync: already {running[0].get('status')} ({running[0].get('id')})")
            return True

    status, data = request(
        "POST",
        f"{api_base}/api/v1/sync/albums",
        body={"clean": False, "download_images": False, "include_tracks": False},
        headers=headers,
    )
    if status == 202 and isinstance(data, dict) and data.get("job_id"):
        job_id = str(data["job_id"])
        print(f"[ok] Library sync: started ({job_id})")
        deadline = time.time() + 60
        while time.time() < deadline:
            st, job = request("GET", f"{api_base}/api/v1/jobs/{job_id}", headers=headers)
            if st == 200 and isinstance(job, dict):
                state = job.get("status")
                if state in {"done", "error", "cancelled"}:
                    message = str(job.get("message") or "")[:140]
                    print(f"[ok] Library sync: {state} {message}".rstrip())
                    return True
            time.sleep(5)
        print("[..] Library sync: still running in the background")
        return True

    if status == 422:
        print("[warn] Library sync: Spotify is not connected for the service account")
    else:
        print(f"[warn] Library sync: could not start ({status}: {str(data)[:160]})")
    return False


# ── verification ────────────────────────────────────────────────────────────
def verify(api_base: str, values: dict[str, str], service_token: str | None) -> bool:
    ok = True
    origin = public_origin(values)

    status, cfg = request("GET", f"{origin}/api/config")
    if status == 200 and isinstance(cfg, dict):
        features = cfg.get("features") or {}
        providers = (cfg.get("oauth") or {}).get("providers") or {}
        if features.get("auth_trusted_header"):
            print("[error] Open WebUI public instance still trusts header auth")
            ok = False
        else:
            print("[ok] Open WebUI public instance: trusted headers disabled")
        oidc = providers.get("oidc")
        if oidc:
            print(f"[ok] Open WebUI OIDC provider: {oidc}")
        else:
            print("[warn] Open WebUI OIDC provider is not configured")
            ok = False
    else:
        print(f"[error] Open WebUI /api/config failed ({status})")
        ok = False

    realm = values.get("KEYCLOAK_REALM", "open-webui")
    client_id = values.get("OAUTH_CLIENT_ID", "open-webui")
    secret = values.get("OAUTH_CLIENT_SECRET", "")
    redirect = values.get("OPENID_REDIRECT_URI", f"{origin}/oauth/oidc/callback")

    status, discovery = request(
        "GET",
        f"{origin}/authKeycloak/realms/{realm}/.well-known/openid-configuration",
    )
    if status == 200 and isinstance(discovery, dict):
        expected_issuer = f"{origin}/authKeycloak/realms/{realm}"
        issuer = discovery.get("issuer")
        if issuer == expected_issuer:
            print(f"[ok] Keycloak issuer: {issuer}")
        else:
            print(f"[error] Keycloak issuer is {issuer}, expected {expected_issuer}")
            ok = False
    else:
        print(f"[error] Keycloak discovery failed ({status})")
        ok = False

    if secret:
        status, data = request(
            "POST",
            f"{origin}/authKeycloak/realms/{realm}/protocol/openid-connect/token",
            form={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": secret,
                "code": "bootstrap-invalid-code",
                "redirect_uri": redirect,
            },
        )
        error = data.get("error") if isinstance(data, dict) else None
        if error == "invalid_grant":
            print("[ok] Keycloak client secret: accepted")
        elif error == "unauthorized_client":
            print("[error] Keycloak client secret: rejected (client secret mismatch)")
            ok = False
        else:
            print(f"[warn] Keycloak client secret: unexpected response ({error or status})")
            ok = False
    else:
        print("[warn] Keycloak client secret: OAUTH_CLIENT_SECRET is empty")
        ok = False

    status, _ = request("GET", f"{origin}/respotit/api/v1/health")
    if status == 200:
        print("[ok] nginx /respotit/ route: healthy")
    else:
        print(f"[error] nginx /respotit/ route failed ({status})")
        ok = False

    status, data = request("GET", "http://127.0.0.1:8091/health")
    if status == 200:
        print("[ok] respotit-mcp health: ok")
    else:
        print(f"[warn] respotit-mcp health failed ({status})")

    if service_token:
        status, data = request(
            "GET", f"{api_base}/api/v1/spotify/status", headers=auth(service_token)
        )
        if status == 200 and isinstance(data, dict):
            if data.get("connected"):
                name = data.get("display_name") or ""
                print(f"[ok] Spotify link: connected{(' as ' + name) if name else ''}")
            else:
                print("[warn] Spotify link: not connected")
        else:
            print(f"[warn] Spotify status check failed ({status})")

    return ok


# ── main ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the reSpotIt full stack.")
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for services")
    parser.add_argument("--no-sync", action="store_true", help="do not start a library sync")
    parser.add_argument("--no-verify", action="store_true", help="skip the final checks")
    args = parser.parse_args()

    values = read_env()
    ssl_enabled = values.get("SSL_ENABLED", "true").strip().lower() != "false"
    api_base = "https://127.0.0.1:8000" if ssl_enabled else "http://127.0.0.1:8000"
    origin = public_origin(values)

    print("reSpotIt full-stack bootstrap")
    restart_nginx()

    api_container = wait_container("api", args.timeout)
    openwebui_container = wait_container("open-webui", args.timeout)
    wait_container("open-webui-2", args.timeout)
    wait_container("keycloak", args.timeout)
    wait_container("nginx-proxy", args.timeout)
    wait_container("respotit-mcp", args.timeout)

    # The realm export only seeds a fresh database; patch the live realm and
    # Open WebUI's persisted URL so every exposed redirect names the LAN IP.
    ensure_keycloak_redirects(values)
    ensure_webui_url(values)

    core_ok = True
    core_ok &= wait_http("reSpotIt API", f"{api_base}/api/v1/health", args.timeout)
    core_ok &= wait_http("Open WebUI (public)", f"{origin}/api/config", args.timeout)
    core_ok &= wait_http(
        "Keycloak OIDC discovery",
        f"{origin}/authKeycloak/realms/{values.get('KEYCLOAK_REALM', 'open-webui')}"
        "/.well-known/openid-configuration",
        args.timeout,
    )
    core_ok &= wait_http("nginx /respotit/ route", f"{origin}/respotit/api/v1/health", args.timeout)
    wait_http("respotit-mcp health", "http://127.0.0.1:8091/health", args.timeout)

    if not core_ok or not api_container:
        print("[error] Core services are not ready; see the warnings above.")
        return 1

    service_token, service_payload = ensure_service_account(api_base, values)
    db = container_id("db")
    spotify_ready = False
    if service_token and service_payload and db:
        spotify_ready = copy_spotify_token(db, service_payload)
    elif not db:
        print("[warn] Spotify link: reSpotIt database container not found")

    if api_container:
        ensure_owui_key(api_container, values.get("RESPOTIT_MCP_EMAIL", "mcp-service@respotit.local"))

    if openwebui_container:
        register_mcp(openwebui_container, values)
    else:
        print("[warn] MCP registration: Open WebUI container not found")

    if not args.no_sync:
        if service_token and spotify_ready:
            start_sync(api_base, service_token)
        else:
            print("[warn] Library sync: skipped (no Spotify link for the service account)")

    if not args.no_verify:
        if not verify(api_base, values, service_token):
            print("[warn] One or more checks failed; see the messages above.")

    print("")
    print("Full stack ready")
    print(f"  reSpotIt UI:   http://{values.get('LAN_IP', 'localhost')}:8888")
    print(f"  reSpotIt API:  https://{values.get('LAN_IP', 'localhost')}:8000")
    print(f"  Open WebUI:    {origin}/")
    print(f"  Keycloak:      {origin}/authKeycloak/admin/")
    print("  MCP health:    http://127.0.0.1:8091/health")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
