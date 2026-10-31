# reSpotIt — Python Project

## About

reSpotIt was built to fill gaps in Spotify's library management. It is an album-centric tool that lets you organize your library and playlists using rich filters, add entire artist discographies to your library or turn them into playlists, import album links from any website, and build queues from albums you are listening to right now. This is a work in progress — expect rough edges and things that may not work yet.

Self-contained project cut from the general reSpotIt. Organised as:

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
- `typescript/` — Capacitor app (npm project; run `` before building the APK).

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
- - No buffer/quality settings available in the Web Playback SDK.