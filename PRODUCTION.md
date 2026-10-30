# Production Readiness ��� reSpotIt Local Server App

Everything under this folder (`reSpotIt-local-server-app`) is considered **production**.

## Scope
- `server/` ��� FastAPI backend + React frontend + Postgres migrations + Dockerfiles.
- `desktop/` ��� self-contained Windows/Linux desktop app (PyInstaller, SQLite).
- `scripts/` ��� backup helpers.
- `docker-compose.yml` ��� full stack (db + api + frontend).

## Constraints
1. **No personal data in source.** No usernames, emails, absolute user paths, or secrets are committed. `.env` is gitignored; use `.env.example` as template.
2. **Secrets via environment only.** `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `JWT_SECRET`, `DATABASE_URL` must be provided via env / `.env`. Defaults are dev-only placeholders.
3. **Database portability.** Postgres for Docker (`DATABASE_URL=postgresql://...`); SQLite for desktop (`DATABASE_URL=sqlite:///...`). Playlist/retention features are Postgres-only on desktop (graceful degradation).
4. **Fixed OAuth port.** Desktop defaults to port 8888 to match the registered Spotify redirect URI `http://127.0.0.1:8888/api/v1/auth/callback`. Do not change without updating the Spotify app settings.
5. **No hardcoded paths.** `desktop/build.ps1` resolves Python via `PATH`. Migrations and frontend dist are located relative to the package (`sys._MEIPASS` / repo layout).
6. **Build artifacts are gitignored.** `node_modules/`, `dist/`, `build/`, `__pycache__/`, `.tmp-render/`, `data/images/`, `*.db` are never committed; CI/Docker rebuilds them.
7. **Tests must pass before release.** `cd server && pytest tests` (35 tests) and `npm run verify:local` (frontend) must be green.
8. **Docker smoke.** `docker compose up -d` ��� all containers healthy; `GET /api/v1/health` = 200; `GET /` = 200.
9. **Desktop smoke.** `reSpotIt.exe` starts, serves frontend + API on the configured port, opens native window; register/login/albums round-trip works on SQLite.
10. **No direct DB access from frontend.** All data goes through `/api/v1/*`.

## Verification (last run)
- Source tests: 35/35 pass.
- Frontend verify:local: OK.
- TypeScript build: OK.
- Docker: all containers healthy, smoke 200.
- Desktop exe: health 200, register/login/albums 200 on SQLite.
- History: no personal usernames or emails in any commit.

## Owner
Project maintainer (contact via GitHub).

## Version
v1.2 — Windows desktop (Python server + React frontend + SQLite). System tray + auto-port + main-thread window fix. Build date: 2026-10-30.
Download: reSpotIt-Windows-v1.2.zip (SHA256: CDEA1BF00B62E8C05D18748DBFF1390375C2FC6DEAC6FAFCB0DB5991D6CADED9)

