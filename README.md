# Spotify Dashboard — Python Project

Self-contained project cut from the general Spotify Dashboard. Organised as:

```
server/        Python backend (FastAPI) + its web frontend + Docker
kotlin/        Kotlin/Compose Android client (source copy)
typescript/    Capacitor/TypeScript Android client (source copy)
data/          Local data (CSV, images) — gitignored-ish but tracked
```

## Server
```bash
# Run from the repo root: docker-compose.yml and .env live there.
cp .env.example .env           # fill in SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
docker compose up -d --build   # api :8000, frontend :8888, db :5433
```
See `server/README.md` for full setup.

## Clients
- `kotlin/` — native Android app (Gradle project under `kotlin/android/`); last synced to upstream `kotlin` `0a058e4` (queue features).
- `typescript/` — Capacitor app (npm project; run `npm run sync` before building the APK).

Both client folders are source copies of their upstream branches (`kotlin`, `android-ts` of `spotify-dashboard-android`). They are tracked here for self-containment but will drift from upstream; re-sync manually when needed.

## Notes
- `.env` lives at the repo root (referenced by `docker-compose.yml`).
- `data/` stays at the root and is mounted into the api container.
- Build artifacts (`node_modules/`, `dist/`, `build/`, `.gradle/`, `.vs/`) are gitignored.

## Deployment

### Option A — Docker
```bash
docker compose build
docker compose up -d
```
- Frontend: http://127.0.0.1:8888
- API: http://127.0.0.1:8000 (health: /api/v1/health)
- Data: `./data` + Postgres volume `pg_data` (back up both).
- Dev variant: `docker compose` with `Dockerfile.api.dev` for live reload.
- Update: `git pull && docker compose build && docker compose up -d`.

### Option B — Windows/Linux desktop app
Self-contained executable (PyInstaller) that runs the FastAPI backend (serving the
built frontend) and opens a native window.

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
- Default port 8888 (must match the Spotify OAuth redirect URI registered in
  your Spotify app: `http://127.0.0.1:8888/api/v1/auth/callback`). If 8888 is
  busy the app exits with a clear error; use `--port <n>` for testing (OAuth
  will not work on other ports).
- Requires a reachable Postgres (default `postgresql://spotify:spotify@127.0.0.1:5433/spotify`);
  override via `DATABASE_URL`. Embedded Postgres (B-DB-1) is a planned follow-up.
- Data/logs/images live under `%APPDATA%\reSpotIt\data` (Windows) or
  `~/.local/share/reSpotIt/data` (Linux).
- Browser playback in the Python frontend uses Spotify's official Web Playback SDK
  (`server/frontend/src/components/PlayerView.jsx`); it requires Premium and the
  `streaming` scope. The separate WASM librespot browser experiment is not used
  here and remains blocked at Spotify storage-resolve RBAC.
## Desktop env

The desktop app loads a .env file from the data directory (%APPDATA%\reSpotIt\data\.env) or next to the executable. Set DATABASE_URL, JWT_SECRET, SPOTIFY_CLIENT_ID, etc. there. Values already in the environment take precedence.

