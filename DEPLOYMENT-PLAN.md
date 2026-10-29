# Deployment Plan — Two Options

## Option A — Docker (as-is, production-ready)

**Goal:** ship the existing `docker-compose.yml` stack with reproducible builds, persistent data, and a simple update flow.

### Stack
- `db`: `postgres:16-alpine`, volume `pg_data`, host port `5433`.
- `api`: FastAPI (`server/Dockerfile.api`), mounts `./server/api`, `./server/migrations`, `./data`; port `8000`.
- `frontend`: Vite build served by nginx (`server/frontend/Dockerfile`); port `8888`.

### Phase A1 — Verify clean build (done)
1. `git checkout HEAD -- server/ typescript/` (no untracked tracked changes).
2. `docker compose build` → both images build; `docker compose up -d` → all healthy.
3. Smoke: `GET http://127.0.0.1:8888/` = 200; `GET /api/v1/health` = 200; `GET /api/v1/spotify/player-token` = 401 (not 404).

### Phase A2 — Hardening
1. Remove `--reload` from `Dockerfile.api` CMD for production image (keep a `Dockerfile.api.dev` with reload).
2. Pin base images by digest; add `.dockerignore` (already have `.gitignore`).
3. Add healthcheck to `api` service (`curl /api/v1/health`).
4. Run migrations automatically on api startup (currently triggered by import; add an `on_event("startup")` hook calling `run_migrations` against `DATABASE_URL`).
5. Back up `./data` + `pg_data` volume in a documented script (`scripts/backup.ps1` / `.sh`).
6. Document env vars and Spotify app registration (redirect URI `http://127.0.0.1:8888/api/v1/auth/callback`).

### Phase A3 — Update flow
1. `git pull` on the host.
2. `docker compose build && docker compose up -d` (recreates changed containers; data volume persists).
3. Verify with `docker compose ps` + smoke endpoints.

### Risks
- Postgres volume lives on host filesystem; must be backed up separately.
- Port `5433`/`8000`/`8888` collisions; document override via env.
- `./data` mount must exist and be writable.

---

## Option B — Windows/Linux desktop application

**Goal:** a single self-contained executable that runs the FastAPI backend, serves the built frontend, and opens a native window. No Docker, no separate Postgres install for end users.

### Key decision: database
The schema uses Postgres-specific types (`UUID`, `TEXT[]`, `TIMESTAMPTZ`, `pgcrypto`). Two viable paths:

- **B-DB-1 (recommended for v1): embed Postgres binaries.**
  - Ship `initdb`/`pg_ctl`/`postgres` for the target OS (EDB community builds, ~40 MB).
  - On first run: init a data directory under the user data dir, start Postgres on `127.0.0.1:5433`, run migrations, then start API.
  - Pro: zero code changes to models/migrations; identical behavior to Docker.
  - Con: large bundle, platform-specific binaries, code signing.

- **B-DB-2 (later): port to SQLite.**
  - Replace `postgresql.ARRAY`/`UUID` with `JSON`/`String(36)`, rewrite migrations, replace `gen_random_uuid()` with `uuid4()`.
  - Pro: single-file DB, tiny bundle.
  - Con: ~2–3 days of porting + test re-run; risk of SQL dialect drift.

Recommendation: ship B-DB-1 first, evaluate B-DB-2 if bundle size becomes a blocker.

### Phase B1 — Single-process backend
1. Serve the frontend from FastAPI using `StaticFiles`:
   - Mount `frontend/dist` at `/` (SPA fallback to `index.html`).
   - Keep `/api/v1/*` routes first.
2. Make the API port configurable via env `PORT` (default `8000`); bind `127.0.0.1` only.
3. Add a `--data-dir` argument (default: OS user data dir) for DB files, images, CSVs, logs.
4. Auto-run migrations on startup (startup event) against `DATABASE_URL`.

### Phase B2 — Desktop shell
1. Use `pywebview` (native webview on Windows/Linux/macOS) to open `http://127.0.0.1:<PORT>` in a window titled "reSpotIt".
   - Fallback: open the system browser if webview unavailable.
2. Process lifecycle: start Postgres (if B-DB-1) → start uvicorn in a background thread → open window → on window close, stop uvicorn and Postgres.
3. Single-instance lock (file lock / named mutex) to prevent two copies.

### Phase B3 — Packaging (PyInstaller)
1. Entry point: `desktop/main.py` that orchestrates DB + API + window.
2. PyInstaller spec (`spotify-dashboard.spec`) bundling:
   - Python deps from `requirements.api.txt` + `pywebview`.
   - `api/`, `migrations/`, `frontend/dist/`.
   - Postgres binaries (B-DB-1) under `postgres/`.
3. Build commands:
   - Windows: `pyinstaller --noconfirm spotify-dashboard.spec` → `dist/reSpotIt.exe`.
   - Linux: same on Ubuntu → `dist/reSpotIt`.
4. Code signing (Windows EV cert) + Linux AppImage/deb (optional).

### Phase B4 — OAuth for desktop
1. Spotify redirect URI must be registered as `http://127.0.0.1:<PORT>/api/v1/auth/callback`.
2. Use a fixed port (e.g. `8888`) to match the registered URI; fail fast with a clear error if the port is in use.
3. Document the Spotify dashboard setup in the README.

### Phase B5 — Data & updates
1. Data dir:
   - Windows: `%APPDATA%\reSpotIt\data`
   - Linux: `~/.local/share/reSpotIt/data`
2. Store `DATABASE_URL`, tokens, images, CSV there; never in the install dir.
3. Auto-update: optional; simplest is "download new installer" link. In-app update (e.g. `pyupdater`) is a later enhancement.
4. Logs to `data/logs/app.log` with rotation.

### Risks & mitigations
- **Bundle size** (~100 MB with Postgres) — acceptable for a desktop app; use onedir mode to keep startup fast.
- **Port conflicts** — fixed port; show a dialog if busy.
- **Antivirus false positives** on PyInstaller executables — mitigate with code signing.
- **Postgres init on first launch** takes a few seconds — show a splash screen.
- **Linux webview deps** (`python3-gi`, `gir1.2-webkit2-4.0`) — document in install instructions; fall back to browser.

---

## Recommended execution order
1. Finish Option A hardening (A2) — already 90% done; ship Docker first.
2. Implement Option B Phase B1 (serve frontend from FastAPI) — benefits both options and simplifies dev.
3. Prototype B-DB-1 + B2/B3 on Windows; validate size and startup time.
4. Decide B-DB-2 (SQLite) based on prototype feedback.

## Deliverables checklist
- [x] `api/main.py` startup hook runs migrations
- [x] FastAPI serves `frontend/dist` at `/`
- [x] `desktop/main.py` orchestrator + `spotify-dashboard.spec`
- [x] PyInstaller onedir build verified (Windows) - `desktop/dist/reSpotIt/reSpotIt.exe`
- [x] Models/dialect abstraction: UUID->String(36), ARRAY->JSON; scoping.as_uuid dialect-aware; database.py supports SQLite
- [x] Embedded DB: port raw-psycopg2 services (album_cache, auth_service, export_log) to SQLAlchemy
- [x] playlist_cache and retention_service degrade gracefully on SQLite (Postgres-only features)
- [x] import_csv degrades gracefully on SQLite
- [x] Desktop fully self-contained on SQLite (verified end-to-end)
- [x] Fixed-port OAuth (README documented)
- [x] README sections for both deployment modes
- [x] Stash dropped
