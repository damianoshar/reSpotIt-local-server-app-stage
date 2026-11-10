# reSpotIt — Python Project

## About

reSpotIt was built to fill gaps in Spotify's library management. It is an album-centric tool that lets you organize your library and playlists using rich filters, add entire artist discographies to your library or turn them into playlists, import album links from any website, and build queues from albums you are listening to right now. This is a work in progress — expect rough edges and things that may not work yet.

### reSpotIt Project Structure

reSpotIt is a multi-component project with several variants:

- **Local Server (standalone)** (this repo) — Python/FastAPI backend + React web frontend + PostgreSQL. Runs entirely on your machine. No AI assistant. Full feature set: library management, playlists, sync, stats, CSV import/export.
- **Local Server + AI assistant** — Same server plus OpenWebUI, Keycloak, and MCP services for AI-powered library queries. Available as a full stack overlay in this repo (`docker-compose.full.yml`) or as a self-contained backup workspace (`reSpotIt-local-server-app-clean-backup-2`).
- **AI URL scan** — In media-server mode the Android apps can scan any web page for albums/concerts (even pages without Spotify links) via the local LLM: "Scan page with AI (albums)" and "Scan concerts (AI)" in the Tools tab. Results resolve to Spotify and save to the library or become a playlist. See `EXPERIMENTAL_FEATURES.md`.
- **Chat sync across AI features (planned)** — Currently only the AI Assistant has Open WebUI chat history. Planned: each scan (albums/concerts) and future features (duplicate explain, metadata enrich, playlist describe, reports, reorganize) become chat threads with list/resume/refine. See `EXPERIMENTAL_FEATURES.md`.
- **Kotlin client** — Native Android app (Kotlin + Jetpack Compose). Full feature parity with media-server mode. See `reSpotIt-kotlin-version`.
- **React clients** — Capacitor/TypeScript Android apps. Offer better compatibility on older Android models and low-RAM devices than the Kotlin client. Two variants:
  - **Standard** — Web Playback SDK for browser-based playback.
  - **Librespot** — Experimental on-device full-track playback via Rust/JNI. Only this variant supports on-device audio.

> **Note:** All Android clients work fully offline without any server. Media-server mode is optional — enable it in Settings to sync, push/pull, and use the AI assistant.

Self-contained project cut from the general reSpotIt. Organised as:

```
server/            Python backend (FastAPI) + React frontend (Vite) + Docker
certs/             mkcert CA + server cert (gitignored; pre-generated for full stack)
data/              Local data (CSV, images) — gitignored
desktop/           Standalone desktop app (PyInstaller)
docs/              Additional documentation
OpenWebUI-stack/   nginx, keycloak realm, MCP sources (gitignored; included for full stack)
scripts/           Utility scripts
.github/           GitHub Actions / CI config
```

**Repository:** https://github.com/damianoshar/reSpotIt-local-server-app-stage (branch: `main`)

**Android clients (current):**
- Kotlin/Compose: https://github.com/damianoshar/reSpotIt-kotlin-version-stage
- React/Capacitor: https://github.com/damianoshar/reSpotIt-react-version-stage (branch `main`)
- React/Capacitor + librespot: https://github.com/damianoshar/reSpotIt-react-version-stage (branch `feat/librespot-player`)

---

## 🚀 Quick Start — Solo (reSpotIt only)

### Option A: Docker (recommended)
```bash
# Run from the repo root: docker-compose.yml and .env live there.
cp .env.example .env           # fill in SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
docker compose up -d --build   # api :8000, frontend :8888, db :5433
```

**TLS certificates are auto-generated on first run** (self-signed, valid for localhost/api/127.0.0.1). No manual cert setup needed.

- **Frontend:** http://127.0.0.1:8888
- **API:** https://127.0.0.1:8000 (health: `/api/v1/health`)
- **API docs:** https://127.0.0.1:8000/docs

> **Note:** Browser will show a cert warning for self-signed certs. Accept it or use `SSL_ENABLED=false` in `.env` for HTTP.

### Option B: Desktop app (no Docker)
Self-contained executable (PyInstaller) that runs the FastAPI backend (serving the built frontend) and opens a native window.

```bash
cd desktop
pip install -r requirements.txt
python main.py --no-window   # backend only, for testing
python main.py               # backend + native window
# Build:
pyinstaller spotify-dashboard.spec --noconfirm
# -> desktop/dist/reSpotIt/reSpotIt.exe
```

Notes:
- Default port 8888 (must match the Spotify OAuth redirect URI registered in your Spotify app: `http://127.0.0.1:8888/api/v1/auth/callback`). If 8888 is busy the app exits with a clear error; use `--port <n>` for testing (OAuth will not work on other ports).
- Requires a reachable Postgres (default `postgresql://spotify:spotify@127.0.0.1:5433/spotify`); override via `DATABASE_URL`. Or use SQLite by setting `DATABASE_URL=sqlite:///path/to/db`.
- Data/logs/images live under `%APPDATA%\reSpotIt\data` (Windows) or `~/.local/share/reSpotIt/data` (Linux).
- Browser playback in the Python frontend uses Spotify's official Web Playback SDK (`server/frontend/src/components/PlayerView.jsx`); it requires Premium and the `streaming` scope.

See `server/README.md` for full setup details.

---

## 🤖 Full Stack — reSpotIt + OpenWebUI + Keycloak + MCP

### One-click (recommended)
```bash
./start-full-stack.sh          # Linux/macOS
start-full-stack.bat           # Windows
```

The launcher is **idempotent** — run it as often as you like. It:

1. creates `.env` on first run, then **preserves existing secrets** (rotating
   DB passwords would break existing Postgres volumes);
2. copies `certs/` and `OpenWebUI-stack/` from
   `../reSpotIt-local-server-app-clean-backup-2` when they are missing;
3. repairs the known full-stack hiccups before starting containers:
   - replaces the legacy nginx `location /api/` with `/respotit/` so Open
     WebUI's own `/api/config` is not shadowed (the "Backend Required" error);
   - keeps `WEBUI_AUTH_TRUSTED_*` off the public `open-webui` instance and
     points the API's trusted-header exchange at the internal `open-webui-2`;
   - makes `OAUTH_CLIENT_SECRET` / `KEYCLOAK_CLIENT_SECRET` match the running
     Keycloak client (or the realm export on first run);
   - appends the local mkcert root CA to Open WebUI's CA bundle so the OIDC
     backchannel can verify `https://localhost`;
4. starts the stack, then bootstraps it:
   - creates the reSpotIt MCP service account;
   - copies the owner's Spotify link to that account on a single-user stack;
   - generates the Open WebUI API key used by the AI assistant;
   - registers/refreshes the reSpotIt MCP connection (38 tools);
   - starts a library sync when a Spotify link is available;
   - verifies the public routes, OIDC discovery, Keycloak client secret and
     that public trusted-header auth is disabled.

Pass `--no-sync` to skip the initial library sync, or `--no-verify` to skip
the final checks.

### First run
1. Open **https://localhost/** and click Keycloak's **Register** link to create
   your account (the realm allows self-registration).
2. Open **http://localhost:8888**, sign in to reSpotIt, and connect Spotify.
3. Re-run the one-click launcher (or just
   `python scripts/bootstrap_full_stack.py`) to copy the Spotify link to the
   MCP service account and sync the library.

### Manual start
```bash
python scripts/prepare_full_stack.py
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --build
python scripts/bootstrap_full_stack.py
```

> **Note:** The full stack uses pre-generated mkcert certs for nginx/Keycloak/OpenWebUI trust. The reSpotIt API uses the same certs (mounted read-only).

This adds:
- OpenWebUI at https://localhost (via nginx proxy on 443)
- Keycloak at https://localhost/authKeycloak
- MinIO at :9000/:9001
- Redis + Redis Insight at :5540
- reSpotIt MCP at 127.0.0.1:8091
- Spotify MCP at 127.0.0.1:8090
- reSpotIt API through nginx at https://localhost/respotit/

> **MinIO / Redis:** both are wired to Open WebUI (restored 2026-11-08) — `STORAGE_PROVIDER=s3` with `S3_*` for file uploads and `WEBSOCKET_MANAGER=redis` for websockets, on both `open-webui` and `open-webui-2`. Credentials come from `MINIO_*` (defaults keep existing data readable). See `docs/AI-TEXT-PIPELINE-PLAN.md`.

### Full-stack troubleshooting

| Symptom | Cause | One-click fix |
| --- | --- | --- |
| Open WebUI says **Backend Required** | nginx `location /api/` shadows Open WebUI's own `/api/` | `prepare_full_stack.py` replaces it with `/respotit/` |
| **Your provider has not provided a trusted header** | `WEBUI_AUTH_TRUSTED_*` on the public instance | public instance has no trusted headers; API uses `open-webui-2` |
| **Sign-in with your identity provider failed** | `OAUTH_CLIENT_SECRET` / `KEYCLOAK_CLIENT_SECRET` mismatch | prepare syncs both with the live Keycloak client secret |
| OIDC callback cannot reach `https://localhost` | container does not trust the mkcert root | prepare appends `certs/ca/rootCA.pem` to the CA bundle |
| reSpotIt MCP has no tools in Open WebUI | connection not registered | bootstrap registers it and verifies 38 tools |
| AI assistant has no library data | service account has no Spotify link / no sync | bootstrap copies the owner's link and starts a sync |
| `.env` lost but Postgres volumes remain | new random DB passwords | restore the old `.env`; do not delete volumes |

#### Option 2: Self-contained backup workspace (recommended)
```bash
cd ../reSpotIt-local-server-app-clean-backup-2
docker compose up -d --build
```

The backup workspace has all required files (certs, OpenWebUI-stack, .env.example) pre-configured.

---

## 📦 Deployment

### Solo (Docker)
```bash
docker compose build
docker compose up -d
```

### Full Stack (Docker)
```bash
python scripts/prepare_full_stack.py
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d
python scripts/bootstrap_full_stack.py
```

- Data: everything now lives under `./docker-data/` (no named volumes). Back up `./data` and `./docker-data/`.
- Full stack bind-mounts: `./docker-data/postgres`, `./docker-data/minio`, `./docker-data/open-webui`, `./docker-data/redis`, `./docker-data/pipelines`, `./docker-data/keycloak-db`, `./docker-data/openwebui-db`

---

## 🔧 Server Details

- **Backend:** Python/FastAPI with SQLAlchemy + PostgreSQL
- **Frontend:** React/Vite (served via nginx in production)
- **Auth:** Spotify PKCE OAuth with token refresh + Keycloak OIDC (optional)
- **API contract:** Frozen `/api/v1` — additive changes only
- **HTTPS:** Auto-generated self-signed certs (solo) or mkcert (full stack)
- **AI assistant:** Open WebUI API key auto-generated on first deploy

### LAN / phone access

The Android clients reach the server over HTTPS on the LAN, so the cert must
cover the PC's LAN IP.

```bash
# Regenerate certs/server.pem with the current LAN IPs in the SAN list.
# Replace 192.168.1.11 with the PC's address (ipconfig / Get-NetIPAddress).
docker run --rm -v "$PWD/certs:/certs" alpine/openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout /certs/server-key.pem -out /certs/server.pem -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:api,IP:127.0.0.1,IP:192.168.1.11"
docker compose -f docker-compose.yml -f docker-compose.full.yml restart api
```

- **Cert trust:** the API cert is issued from the local development CA in
  `certs/ca/rootCA.pem` (mkcert or a self-created CA). The Android apps trust
  that CA:
  - *Personal builds* (gitignored `src/personal/res/` overlay) bundle the CA at
    `res/raw/respotit_ca.pem` -> zero-touch install.
  - *Public/CI builds* trust only system + user CAs; the user installs the CA
    once (Settings -> Security -> Install a certificate -> CA certificate, pick
    `rootCA.pem`). Because the CA is stable (10 years), this install survives
    every server cert reissue and every app update.
  - Reissue the leaf for a new LAN IP with `scripts/local-certs.sh <ip>` and
    restart the API container. No app rebuild needed.
- **Port:** use `https://<pc-ip>:8000`. If Docker Desktop on Windows publishes
  port 8000 to loopback only, forward it with `lan_proxy.py`
  (`0.0.0.0:8001 → 127.0.0.1:8000`, kept in
  `%LOCALAPPDATA%\reSpotIt\lan_proxy.py` and started from the user's Startup
  folder) and use `https://<pc-ip>:8001` instead.
- **Firewall:** allow inbound TCP on the chosen port for the Public profile
  (`netsh advfirewall firewall add rule name="reSpotIt API 8001" dir=in action=allow protocol=TCP localport=8001`).

---

## 🔑 Environment variables

`.env` lives at the repo root (`.env.example` documents every key — 56 in total). The most important ones:

| Group | Keys |
|---|---|
| Spotify | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `REDIRECT_URI`, `PUBLIC_BASE_URL` |
| Server | `SSL_ENABLED`, `CORS_ALLOW_ORIGIN`, `FORWARDED_ALLOW_IPS` |
| Database | `DATABASE_URL` (default `postgresql://spotify:spotify@127.0.0.1:5433/spotify`) |
| Keycloak / OIDC | `KEYCLOAK_ENABLED`, `KEYCLOAK_REALM`, `KEYCLOAK_HOSTNAME`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_DB_USER`, `KEYCLOAK_DB_PASSWORD`, `OPENID_PROVIDER_URL`, `OPENID_REDIRECT_URI`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_SCOPES`, `OAUTH_PROVIDER_NAME`, `OAUTH_AUTO_SIGNUP`, `OAUTH_MERGE_ACCOUNTS_BY_EMAIL`, `ENABLE_OAUTH_SIGNUP` |
| Open WebUI | `WEBUI_AUTH`, `WEBUI_SECRET_KEY`, `DEFAULT_USER_ROLE`, `OPENWEBUI_DB_*`, `OPENWEBUI_URL`, `OPENWEBUI_TRUSTED_AUTH`, `OPENWEBUI_TRUSTED_HEADER`, `OPENWEBUI_TRUSTED_NAME_HEADER`, `OPENAI_API_BASE_URL`, `OPENAI_API_KEY` |
| MCP | `MCP_API_KEY`, `MCP_TOOLS`, `RESPOTIT_MCP_*`, `SPOTIFY_MCP_URL`, `SPOTIFY_MCP_TOKEN` |
| MinIO / Redis | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET_NAME`, `MINIO_REGION` |
| Telemetry | `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY` |

> **Secrets:** `.env`, `certs/`, `OpenWebUI-stack/` and `data/` are gitignored. Never commit DB passwords, Keycloak client secrets, the Open WebUI API key (`/data/.owui_api_key`) or MCP tokens. The one-click launcher deliberately **preserves** an existing `.env` — changing the DB password after the Postgres volume exists locks the stack out.

---

## 🧪 Tests & CI

```bash
# Backend (FastAPI, pytest)
cd server
pip install -r requirements.api.txt -r requirements-dev.txt
python -m pytest tests -q            # 13 test files

# Frontend (Vite + verification scripts)
cd server/frontend
npm ci
npm run build
npm run verify:local                 # local-mode + pipeline + render + CSS-build checks
```

Backend test files cover concerts and hidden albums, concert scans, CSV import (replace mode), Keycloak auth, LLM chats and the chunked LLM extraction service, the MCP service, the phase-0 endpoints, playlist actions, artist resolution, retention, Spotify token import and user auth.

CI (`.github/workflows/release.yml`, triggers on `v*` tags or manual dispatch):

| Step | What it does |
|---|---|
| Build frontend | `npm install` → `npm run build` → `npm run verify:local` in `server/frontend` |
| Install Python deps | `requirements.api.txt` + `requirements-dev.txt` + `desktop/requirements.txt` |
| Run tests | `python -m pytest tests -q` in `server` |
| Build desktop exe | `pyinstaller spotify-dashboard.spec --noconfirm` |
| Package release | `reSpotIt-Windows.zip` + `SHA256SUMS.txt` |
| Publish | GitHub release with the zip and the checksum file |

---

## 🩺 Solo-stack troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser shows a cert warning | Self-signed certificate (solo mode) | Accept it, or set `SSL_ENABLED=false` in `.env` for plain HTTP |
| Container exits at once | Port already in use (8000/8888/5433) | `docker compose ps`, then free the port or change the published port |
| "password authentication failed for user" | `.env` DB password changed after the volume was created | Restore the previous `.env`; do **not** delete `docker-data/postgres` |
| Library empty after a sync | Spotify account has no saved albums, or the job was cancelled | Open the sync panel for the stage log; `GET /api/v1/sync/history` |
| Android client cannot reach the API | Cert does not cover the LAN IP, or the port is not published | Reissue the leaf with the LAN IP in the SAN list; `scripts/lan-expose.ps1`; firewall rule |
| AI assistant disabled | No Open WebUI API key yet | The key is auto-generated on first deploy and stored at `/data/.owui_api_key`; re-run `scripts/bootstrap_full_stack.py` |
| Frontend builds but the API 404s | Wrong base URL / proxy prefix | Solo: the API is at `https://127.0.0.1:8000`; full stack: `/respotit/` (nginx) |
| Migration mismatch after pulling | New migration file not applied | Apply `server/migrations/*.sql` in order; the API runs them on start |

---

## 🏷️ Versioning & changelog

- Release tags in this repo: `v0.1`, `v0.1.1`, `v1.0`, `v1.1`, `v1.2`, `v1.3`, `v1.4`.
- Tagging `v*` runs the release workflow and publishes `reSpotIt-Windows.zip` + `SHA256SUMS.txt`.
- Per-feature notes live in the commit history (`git log --oneline`); AI feature status is tracked in `EXPERIMENTAL_FEATURES.md`.

---

## 📁 Project Layout

```
server/                ← Python backend (FastAPI) + React frontend (Vite) + Docker
├── api/              ← FastAPI application
│   ├── main.py       ← App factory, router registration, Open WebUI key bootstrap
│   ├── config.py     ← Settings (env-driven)
│   ├── database.py   ← SQLAlchemy engine/session
│   ├── models.py     ← SQLAlchemy models
│   ├── schemas.py    ← Pydantic DTOs
│   ├── contract.py   ← Frozen /api/v1 contract helpers
│   ├── scoping.py    ← Per-user data scoping
│   ├── job_store.py  ← In-memory job registry
│   ├── routers/      ← /api/v1 routes (16 routers, see below)
│   └── services/     ← Business logic (Spotify, sync, CSV, images, LLM, MCP, Keycloak)
├── frontend/         ← React/Vite frontend (PlayerView.jsx = Web Playback SDK)
│   ├── src/          ← React sources
│   └── scripts/      ← verify-local-mode / verify-pipeline / render-check / css-build
├── migrations/       ← 001..015 SQL migrations (concerts, hidden albums, LLM chats, …)
├── tests/            ← pytest suite (13 test files)
├── scripts/          ← smoke-python.ps1
├── Dockerfile.api / Dockerfile.api.dev
├── entrypoint.sh     ← TLS cert generation + uvicorn start
├── requirements.txt / requirements.api.txt / requirements-dev.txt
└── README.md         ← API reference, local LLM, Spotify setup

.github/              ← GitHub Actions / CI config (release.yml)
certs/                ← mkcert CA + server cert (gitignored; pre-generated for full stack)
data/                 ← Local CSV/image cache (gitignored)
desktop/              ← Standalone desktop app (PyInstaller)
docs/                 ← Additional documentation (STORAGE-POLICY.md, AI-TEXT-PIPELINE-PLAN.md)
OpenWebUI-stack/      ← nginx, keycloak realm, MCP sources (gitignored; included for full stack)
scripts/              ← Utility scripts
├── prepare_full_stack.py  ← idempotent pre-start repair (nginx, CA, .env)
├── bootstrap_full_stack.py ← post-start bootstrap (MCP, sync, verification)
├── local-certs.sh    ← Reissue the leaf cert for a new LAN IP
├── lan-expose.ps1    ← Publish the API on the LAN (portproxy + firewall)
└── backup.ps1 / backup.sh ← Dump ./data + Postgres into ./backups/<timestamp>/

docker-compose.yml         ← Solo stack (db, api, frontend) — repo root
docker-compose.full.yml    ← Full stack overlay (OpenWebUI, Keycloak, MCP, etc.)
.env.example               ← Template for all configs (56 keys)
.gitignore                 ← Ignores .env, certs/, OpenWebUI-stack/, data/, build artifacts
start-full-stack.sh/.bat  ← One-click deploy scripts
```

### API routers (`/api/v1`)

`albums` · `artists` · `auth` · `concerts` · `concert-scans` · `exports` · `hidden-albums`
· `images` · `import` · `jobs` · `keycloak-auth` · `llm` · `load` · `meta` · `spotify` · `sync`

The contract is **frozen**: additive changes only. Endpoint-level detail lives in
`server/README.md` ("API" section) and in the interactive docs at `/docs`.

---

## 📋 Notes

- `.env` lives at the repo root (referenced by `docker-compose.yml`).
- `data/` stays at the root and is mounted into the api container.
- Build artifacts (`node_modules/`, `dist/`, `build/`, `.gradle/`, `.vs/`) are gitignored.
- The Android clients live in **separate repositories** (see the links at the top): `reSpotIt-kotlin-version`, `reSpotIt-react-version` (branch `main`) and `reSpotIt-react-version` (branch `feat/librespot-player`). This repository contains no client sources.
- Full stack files (`certs/`, `OpenWebUI-stack/`) are now included in this repo (gitignored). The start-full-stack script copies them from the backup workspace if missing.
- The Open WebUI API key is auto-generated on first deploy and persisted to `/data/.owui_api_key`. No manual key creation needed.
- The one-click launcher preserves an existing `.env`; it only fills missing or placeholder secrets. This is deliberate: changing DB passwords after the Postgres volumes exist locks the stack out.