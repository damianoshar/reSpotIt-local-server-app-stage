# reSpotIt — Python Project

## About

reSpotIt was built to fill gaps in Spotify's library management. It is an album-centric tool that lets you organize your library and playlists using rich filters, add entire artist discographies to your library or turn them into playlists, import album links from any website, and build queues from albums you are listening to right now. This is a work in progress — expect rough edges and things that may not work yet.

### reSpotIt Project Structure

reSpotIt is a multi-component project with several variants:

- **Local Server (standalone)** (this repo) — Python/FastAPI backend + React web frontend + PostgreSQL. Runs entirely on your machine. No AI assistant. Full feature set: library management, playlists, sync, stats, CSV import/export.
- **Local Server + AI assistant** — Same server plus OpenWebUI, Keycloak, and MCP services for AI-powered library queries. Available as a full stack overlay in this repo (`docker-compose.full.yml`) or as a self-contained backup workspace (`reSpotIt-local-server-app-clean-backup-2`).
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

### Quick start (recommended)
```bash
# Generates secrets, configures .env, copies required files, and launches:
./start-full-stack.sh          # Linux/macOS
# or
start-full-stack.bat           # Windows
```

### Manual (two options)

#### Option 1: Overlay in this repo (self-contained)
```bash
# All required files (certs/, OpenWebUI-stack/) are now included.
# Just configure .env and launch:
cp .env.example .env   # fill in SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --build
```

> **Note:** The full stack uses pre-generated mkcert certs for nginx/Keycloak/OpenWebUI trust. The reSpotIt API uses the same certs (mounted read-only).

This adds:
- OpenWebUI at https://localhost (via nginx proxy on 443)
- Keycloak at https://localhost/authKeycloak
- MinIO at :9000/:9001
- Redis + Redis Insight at :5540
- reSpotIt MCP at 127.0.0.1:8091
- Spotify MCP at 127.0.0.1:8090

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
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d
```

- Data: `./data` + Postgres volume `pg_data` (back up both)
- Full stack adds: `minio-data`, `open-webui-data`, `redis-data`, `pipelines`, `keycloak-db-data`, `openwebui-db-data`

---

## 🔧 Server Details

- **Backend:** Python/FastAPI with SQLAlchemy + PostgreSQL
- **Frontend:** React/Vite (served via nginx in production)
- **Auth:** Spotify PKCE OAuth with token refresh + Keycloak OIDC (optional)
- **API contract:** Frozen `/api/v1` — additive changes only
- **HTTPS:** Auto-generated self-signed certs (solo) or mkcert (full stack)
- **AI assistant:** Open WebUI API key auto-generated on first deploy

---

## 📁 Project Layout

```
server/                ← Python backend (FastAPI) + React frontend (Vite) + Docker
├── app/              ← FastAPI application
│   ├── api/          ← /api/v1 routes (albums, playlists, sync, stats, MCP, LLM)
│   ├── core/         ← Config, security, database
│   ├── models/       ← SQLAlchemy models
│   ├── schemas/      ← Pydantic DTOs
│   └── services/     ← Business logic (Spotify, sync, CSV, images, LLM, Keycloak)
├── web/              ← React frontend (Vite)
├── docker-compose.yml
└── Dockerfile

.github/              ← GitHub Actions / CI config
certs/                ← mkcert CA + server cert (gitignored; pre-generated for full stack)
data/                 ← Local CSV/image cache (gitignored)
desktop/              ← Standalone desktop app (PyInstaller)
docs/                 ← Additional documentation
OpenWebUI-stack/      ← nginx, keycloak realm, MCP sources (gitignored; included for full stack)
scripts/              ← Utility scripts

docker-compose.yml         ← Solo stack (db, api, frontend)
docker-compose.full.yml    ← Full stack overlay (OpenWebUI, Keycloak, MCP, etc.)
.env.example               ← Template for all configs
.gitignore                 ← Ignores .env, certs/, OpenWebUI-stack/, data/, build artifacts
start-full-stack.sh/.bat  ← One-click deploy scripts
```

---

## 📋 Notes

- `.env` lives at the repo root (referenced by `docker-compose.yml`).
- `data/` stays at the root and is mounted into the api container.
- Build artifacts (`node_modules/`, `dist/`, `build/`, `.gradle/`, `.vs/`) are gitignored.
- The `kotlin/` and `typescript/` folders are legacy source copies; they may drift from upstream. Current clients are in separate repositories (see links above).
- Full stack files (`certs/`, `OpenWebUI-stack/`) are now included in this repo (gitignored). The start-full-stack script copies them from the backup workspace if missing.
- The Open WebUI API key is auto-generated on first deploy and persisted to `/data/.owui_api_key`. No manual key creation needed.