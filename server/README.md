# reSpotIt — Python Edition

reSpotIt-styled library manager: React frontend + FastAPI backend + PostgreSQL,
all in Docker. Syncs your Spotify library, downloads cover art, browses with
rich filters, queues/creates playlists.

## Quickstart

Run these from the **repo root** (`docker-compose.yml` and `.env` live there):

```bash
cp .env.example .env   # then fill in SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
docker compose up --build
```

- Frontend: http://127.0.0.1:8888
- API: https://127.0.0.1:8000 (`/docs` for Swagger; set `SSL_ENABLED=false` for HTTP)
- Postgres: 127.0.0.1:5433 (`spotify` / `spotify`, db `spotify`)
  (host 5433 — the elixir tree's Postgres owns host 5432; container-side is unchanged)

## HTTPS and Open WebUI

The API serves HTTPS by default (`SSL_ENABLED=true`). Put the mkcert server
certificate and key at `certs/server.pem` and `certs/server-key.pem` (mounted
read-only at `/app/certs`), or set `SSL_ENABLED=false` for plain HTTP.

The `api` service also joins the external `openwebui-stack_default` network so
it can reach the internal trusted-header `open-webui-2` instance. Start the
OpenWebUI stack first, or remove that external network and the `OPENWEBUI_*`
variables if you do not use the AI assistant.

## Spotify app setup

At https://developer.spotify.com/dashboard, add this exact Redirect URI:

```
http://127.0.0.1:8888/api/v1/auth/callback
```

(Use `127.0.0.1`, not `localhost` — Spotify only whitelists the IP loopback.)
It must match `REDIRECT_URI` in `.env`.

## How it works

```
Spotify Web API → sync job (fetch → covers → load, one job) → Postgres
                                                 ↓
                                     React UI (nginx → FastAPI)
```

- **Sync** fetches all saved albums (paginated, 429-aware) into `/data/spotify_albums.csv`.
- **Covers** downloads missing images into `/data/images` (8 workers, skips existing).
- **Load** upserts everything into Postgres (migrations run automatically).
- All three run inside **one cancellable background job** (`POST /api/v1/sync/albums`)
  whose `stage` field says which part is running; the UI follows them as three
  steps of that single job.

## API

Canonical paths under `/api/v1/*` (see API-PARITY-PLAN §1 in `latest-versions/`).
Interactive docs at `/docs` when the API runs. Notable endpoints:

| Method + path | Purpose |
|---|---|
| `GET /api/v1/auth/login` | Spotify authorize URL |
| `GET /api/v1/auth/callback` | OAuth return (HTML page) |
| `GET /api/v1/auth/status` | `{authenticated, display_name}` |
| `POST /api/v1/sync/albums` | Full pipeline sync job `{clean, download_images}` |
| `GET /api/v1/sync/history?limit=10` | Past runs, newest first: `{data: [job envelope]}` (max 50) |
| `GET /api/v1/jobs/{id}` (+ `POST …/cancel`) | Any job, canonical envelope |
| `GET /api/v1/albums` | Filter/sort/paginate (`sort`+`order` or legacy combined) |
| `GET /api/v1/albums/stats` · `/export` · `DELETE /api/v1/albums` | Stats, CSV download, wipe |
| `POST /api/v1/import/csv` | Inline CSV import with tolerant headers |
| `GET /api/v1/playlists` · `POST /api/v1/playlists` (optional `album_ids` and/or direct `uris`) · `POST /api/v1/playlists/{id}/tracks` · `POST /api/v1/playlists/{id}/items` | Spotify playlist ops (blocking, 5-album queue cap). The `/items` route appends up to 100 track/episode URIs per request and is additive for queue snapshots. |
| `POST /api/v1/queue` | Queue albums (blocking, 5-album cap — job version planned) |
| `GET /api/v1/meta/genres|artists|years` | Filter option lists |
| `GET /api/v1/llm/status` · `/models` · `POST /api/v1/llm/chat` | Optional local-LLM proxy through Open WebUI (see below) |

`POST /api/v1/sync/albums` is the only way to start a sync, and every job —
sync, covers, load — is polled and cancelled through the generic
`GET`/`POST /api/v1/jobs/{id}[/cancel]`. The old per-stage endpoints
(`/sync/start`, `/sync/cancel`, `/images/start`, `/images/cancel`, `/load/cancel`,
their `/jobs` listings) are gone: no other backend ever had them, and two routes
that both fetch from Spotify is exactly the divergence the contract exists to
remove.

Two python-only actions remain, because this backend stages through CSV and the
others do not: `POST /api/v1/images/sync` (refresh covers without a full sync —
the contract's optional images extension, at its frozen path) and
`POST /api/v1/load/start` (re-load the CSV into Postgres).

`GET /api/v1/sync/history` is the same endpoint, wrapper and 50-cap as elixir
and C#; the panel's "last sync" line reads it so a browser that has never seen a
run still says when the library was last synced. Unlike theirs it is **in-memory
only** — history lasts as long as the process — and it adds two optional
timestamps (`created_at`, `finished_at`) that clients must treat as extras.

## Local LLM (optional)

The AI assistant uses the same FastAPI process as a proxy:

```
Android / web UI -> FastAPI /api/v1/llm/* -> Open WebUI -> llama-server
```

Open WebUI owns the model connection, accounts and chat history; the phone never
holds the Open WebUI token. The backend only needs these variables on the `api`
service (or in the shell when running uvicorn natively):

| Variable | Default | Purpose |
|---|---|---|
| `OPENWEBUI_URL` | `http://localhost:3000` | Open WebUI base URL. In Docker, point this at the internal trusted-header instance (e.g. `http://open-webui-2:8080` on the shared `openwebui-stack_default` network), not at the browser-facing container. |
| `OPENWEBUI_API_KEY` | *(empty — disabled)* | Open WebUI personal access token (`sk-...`). Create it in Open WebUI: Settings -> Account -> API Keys. |
| `OPENWEBUI_MODEL` | first model Open WebUI lists | Optional model id override. |
| `OPENWEBUI_TRUSTED_AUTH` | `false` | Exchange the signed-in user's email for a per-user Open WebUI JWT (trusted-header sign-in). Required for chat history. |
| `OPENWEBUI_TRUSTED_HEADER` | `X-OWUI-Trusted-Email` | Header Open WebUI trusts for the email. Only enable on a private network. |
| `LLM_TIMEOUT` | `180` | Read timeout in seconds. Large local models are slow. |

Trusted-header auth must point at an instance that is **not** browser-facing:
Open WebUI rejects password sign-in whenever `WEBUI_AUTH_TRUSTED_EMAIL_HEADER`
is set. The dev stack therefore runs `open-webui` (browser login, published on
`:3000`) and `open-webui-2` (internal trusted header, no published port)
against the same database and data volume.

Endpoints (all require the normal server JWT):

- `GET /api/v1/llm/status` — `{configured, available, model, models, error}`.
- `GET /api/v1/llm/models` — models exposed by Open WebUI.
- `POST /api/v1/llm/chat` — `{messages, system?, model?, temperature?, max_tokens?, chat_id?, use_history?, history_limit?, persist?}`
  -> `{content, reasoning_content, finish_reason, model, usage, chat_id, persisted}`. Non-streaming.
- `GET /api/v1/llm/chats` — the signed-in user's Open WebUI chats.
- `GET /api/v1/llm/chats/current` — the chat stored in `llm_chat_sessions`, or `null`.
- `DELETE /api/v1/llm/chats/current` — forgets the pointer without deleting the chat.
- `POST /api/v1/llm/chats` — `{title?, model?}`; creates a chat and makes it current.
- `GET /api/v1/llm/chats/{id}` — one chat with its messages.
- `DELETE /api/v1/llm/chats/{id}` — deletes a chat and clears the pointer.

With `chat_id` the API prepends the chat's last `history_limit` turns (default
20) and, when `persist` is true (default), appends the new exchange to Open
WebUI. The chat routes need `OPENWEBUI_TRUSTED_AUTH=true`; otherwise they
answer `503 llm_chat_unavailable`.

The web frontend exposes these in the **AI** tab (server mode): a recent-chat
sidebar, resume-on-reload, a new-chat action that clears the pointer, and
delete. It falls back to stateless answers when history is unavailable.

If `OPENWEBUI_API_KEY` is unset, the routes answer `503 llm_not_configured` and
the rest of the app keeps working.

## Local mode (no server)

The UI can run against a library kept **in this browser** instead of the server:
click the badge in the header (`☁ Server` / `⌂ This device`).

- **Server** (default) — nginx → FastAPI; sync, cover downloads, playlists and
  the queue all run on the server.
- **This device** — IndexedDB only, nothing is sent anywhere. The Spotify
  pipeline, playlists and the queue are hidden, because they are server-side
  operations this app has no credentials for. Bring a library in with
  **Import CSV** and take it out with **Export CSV**, both in the frozen columns
  `id,title,artist,year,genre,image_url,added_at`.

The choice is remembered per browser. The contract is the same in both modes:
the local layer answers the same list/stats/CSV shapes as `/api/v1`, so filters,
sorting, pagination and the stats panel behave identically either way.

## Browser playback

The Player tab uses Spotify's official Web Playback SDK. It requires a Spotify
Premium account and an OAuth token with the `streaming` scope. The independent
WASM librespot browser experiment is not used here; it remains blocked at
Spotify storage-resolve RBAC and is kept separate/uncommitted.

## Dev notes

- API live-reloads (`./api` is mounted); frontend needs `docker compose build frontend` after JS changes.
- Data persists in the `pg_data` volume and `./data` (CSV, token, images).
- Standalone scripts (`spotify_albums.py`, `csv_to_postgres.py`, `image_downloader.py`)
  predate compose and are not used by it.
- Frontend checks: `npm run verify:local` in `frontend/` — the IndexedDB + CSV
  data layer, the sync-panel stage mapping (pure functions, plus a guard that no
  source references the removed per-stage routes), then an SSR render of the app
  in both modes. `fake-indexeddb`, no browser needed; all three suites also run
  from the repo-wide conformance runner.

