# Experimental Features β€” LLM-Enhanced reSpotIt

> Status: **Experimental / Work in progress.** Features may not work. Expect rough edges.

## Overview

reSpotIt can be enhanced with a local LLM (running on PC via Ollama / OpenWebUI) to provide
intelligent library management. The Android app (React or Kotlin) connects to the reSpotIt
backend in **remote mode** and calls new `/api/v1/llm/*` endpoints that proxy to the local LLM.

This is **not overkill**: it reuses the existing Python backend + Docker stack. The Android app
just calls new API endpoints β€” no on-device model needed.

## Architecture

```
Android (React/Kotlin)  β†’  reSpotIt Backend (FastAPI, Docker)  β†’  Ollama (LLM)
                                    β†‘
                              OpenWebUI (optional, for chat UI)
```

- **PC:** Docker stack runs reSpotIt backend + Ollama + OpenWebUI.
- **Android:** Connects to backend via remote mode. Calls `/api/v1/llm/*` endpoints.
- **LLM:** Ollama serves models (e.g., Llama 3.1 8B, Mistral 7B). Configurable URL.

## Proposed Features (all kept)

### 1. Natural Language Playlist Creation
- **Input:** "Make a playlist of jazz albums I saved in 2023"
- **Flow:** LLM parses intent β†’ backend filters library β†’ creates playlist β†’ returns result.
- **Endpoints:** `POST /api/v1/llm/playlist/create` (body: `{ prompt: string }`)
- **Effort:** Medium

### 2. Library Q&A / Natural Language Search
- **Input:** "What genres am I missing?" / "Which artists do I have the most albums from?"
- **Flow:** LLM translates query to filter/SQL β†’ backend executes β†’ returns results.
- **Endpoints:** `POST /api/v1/llm/query` (body: `{ question: string }`)
- **Effort:** Medium

### 3. Smart Duplicate Explanation
- **Input:** Duplicate groups detected by existing duplicate finder.
- **Flow:** LLM explains why albums are duplicates and recommends which to keep.
- **Endpoints:** `POST /api/v1/llm/duplicates/explain` (body: `{ groups: [...] }`)
- **Effort:** Low

### 4. Bulk Metadata Enrichment
- **Input:** All albums missing genre/mood data.
- **Flow:** Server-side batch job calls LLM for each album to fill gaps.
- **Endpoints:** `POST /api/v1/llm/enrich` (body: `{ album_ids: [...] }`)
- **Effort:** Medium

### 5. Playlist Description Generator
- **Input:** Playlist ID.
- **Flow:** LLM generates a short description from the playlist's tracks.
- **Endpoints:** `POST /api/v1/llm/playlist/describe` (body: `{ playlist_id: string }`)
- **Effort:** Low

### 6. Report Generation
- **Input:** "Generate a monthly listening report."
- **Flow:** LLM summarizes stats, genre trends, new additions.
- **Endpoints:** `POST /api/v1/llm/report` (body: `{ period: string }`)
- **Effort:** Medium

### 7. Batch Reorganization
- **Input:** "Reorganize all my playlists by decade."
- **Flow:** LLM plans moves β†’ backend executes with confirmation.
- **Endpoints:** `POST /api/v1/llm/reorganize` (body: `{ instruction: string }`)
- **Effort:** High

## Backend Changes (Python)

- Add `LLM_SERVICE_URL` env var (default: `http://ollama:11434` in Docker, `http://localhost:11434` locally).
- Add `server/api/services/llm_service.py` β€” proxies to Ollama's `/api/generate` endpoint.
- Add `server/api/routers/llm.py` β€” FastAPI router with the endpoints above.
- Register router in `main.py`.
- Add `ollama` service to `docker-compose.yml`.

## Android Changes (React + Kotlin)

- Add `LLMService.ts` / `LLMService.kt` β€” calls backend `/api/v1/llm/*` endpoints.
- Add UI: chat input / prompt dialog, result display.
- Settings: LLM endpoint URL (default: backend URL + /api/v1/llm).

## Docker Stack Update

Add to `docker-compose.yml`:
```yaml
ollama:
  image: ollama/ollama
  ports: ["11434:11434"]
  volumes: [ollama_data:/root/.ollama]
```

And optionally OpenWebUI:
```yaml
open-webui:
  image: ghcr.io/open-webui/open-webui:main
  ports: ["3000:8080"]
  environment:
    - OLLAMA_BASE_URL=http://ollama:11434
```

## Status

- [ ] Backend LLM service + router
- [ ] Docker compose update (Ollama + OpenWebUI)
- [x] Android LLM service (React)
- [x] Android LLM service (Kotlin)
- [ ] Natural language playlist creation UI
- [ ] Library Q&A UI
- [ ] Smart duplicate explanation UI
- [ ] Bulk metadata enrichment
- [ ] Playlist description generator
- [ ] Report generation
- [ ] Batch reorganization
- [x] Keycloak OIDC login (Phase 3, opt-in)
- [x] Per-user Open WebUI identity (Phase 4, trusted header)
- [x] Chat history persistence + context (Phase 5/6, API)
- [x] Web AI chat UI: history sidebar, resume, new/delete (Phase 7)
- [x] Android AI chat UI (React and Kotlin clients)

## AI URL scan (Phases 0-4, 2026-11-07)

Scan a web page (or pasted text) for albums/concerts. AI extracts `{artist, album}` /
`{artist, date, venue, url}` pairs; backend resolves them to Spotify IDs; results can
be saved to the library or turned into a playlist. Works for pages with no Spotify links.

- [x] Phase 0 (backend): `POST /api/v1/llm/extract-albums`, `/extract-concerts`,
      `POST /api/v1/spotify/resolve-albums`, `/resolve-artists`, `GET /followed-artists`
      + tests (`f3cf98d`).
- [x] Phase 1 (React): `AiUrlScanDialog` (extract albums, save/playlist) (`a1aa24e`).
- [x] Phase 2 (React): concerts calendar (scan, storage, list dialog) (`c7e8107`).
- [x] Phase 3 (Kotlin): data layer, repository, ViewModel, Compose dialog
      (`f6c751d`, `d760241`, `895f7c0`, `5865509`, plus `49e28bf` for the
      "Scan page with AI (albums)" button).
- [x] Phase 4 (standalone fallback): manual paste without AI (`cfde65b`).

Entry points (React Settings/Tools): "Scan page with AI (albums)", "Scan concerts (AI)",
"View concerts calendar", "Add albums from a website" (native WebView, Spotify links only).
Kotlin: Tools tab -> "Scan page with AI (albums)", "Concerts calendar", "Add from site".

Known follow-ups:
- Kotlin `DashboardApiService` uses `@Body Map<String, Any>` for the extract/resolve
  routes, which Retrofit rejects ("parameter type must not include a type variable
  or wildcard"). Fix: concrete body DTOs. Blocks the Kotlin scan at runtime.
- Backend `extract_structured` calls the LLM once; plan edge case (retry once with
  stricter prompt on non-JSON) is not implemented. Causes "model did not return
  correct json" on some pages.
- Kotlin dialogs accept URL only; React also accepts pasted text. Add paste-text
  field to Kotlin `ConcertsDialog` and `AiUrlScanDialog`.

## Keycloak OIDC (Phase 3 + 4)

Keycloak is opt-in: `KEYCLOAK_ENABLED=false` (default) keeps email/password
login and the shared Open WebUI key exactly as before.

Flow:

1. Client opens `GET /api/v1/auth/keycloak/login?redirect_uri=<app-url>`.
2. The API redirects to Keycloak with a signed, 10-minute `state` carrying the
   final redirect (custom schemes `com.spotifydashboard.app://` and
   `com.spotifydashboard.app.ts://`, plus allowlisted http(s) hosts).
3. Keycloak returns `code` to `/api/v1/auth/keycloak/callback`. The API
   exchanges it server-side (the client secret never reaches the client), maps
   the Keycloak `sub` to a local `users` row through `keycloak_identities`, and
   redirects to the app with the local JWT pair (fragment for http(s), query
   for custom schemes).
4. `/api/v1/auth/keycloak/me` reports the linked identity, and every existing
   `/api/v1` route accepts the Keycloak access token directly.

Per-user Open WebUI (Phase 4): with `OPENWEBUI_TRUSTED_AUTH=true` the API
exchanges the signed-in email for a per-user Open WebUI JWT through
`POST /api/v1/auths/signin` with `X-OWUI-Trusted-Email`, caches it in memory,
and retries once after a 401. Chat history is therefore attributed to the
signed-in user instead of the shared service key.

Trusted-header auth must not be enabled on the browser-facing instance: Open
WebUI rejects password sign-in whenever `WEBUI_AUTH_TRUSTED_EMAIL_HEADER` is
set. The dev stack publishes `open-webui` for browser login and keeps
`open-webui-2` internal (no published port) for the API; both share the same
database and data volume, so users and chats stay common.

Local-dev caveat: Keycloak 26 marks its login cookies `Secure; SameSite=None`
unconditionally. The Vite dev proxy on :8888 strips those flags for the
plain-HTTP LAN origin. A real deployment must terminate TLS instead.

Configuration lives in `server/.env` (`KEYCLOAK_*`, `OPENWEBUI_TRUSTED_*`).
Regression tests: `server/tests/test_keycloak_auth.py` (16 tests).

## Chat history (Phase 5 + 6)

Open WebUI remains the system of record for chats. The API only stores the
pointer to the user's current chat in the additive `llm_chat_sessions` table
(migration `011_llm_chat_sessions.sql`), so the app can resume without listing
every chat on launch.

New endpoints (all require the same JWT as the rest of `/api/v1`):

- `GET /api/v1/llm/chats` - the signed-in user's chats.
- `GET /api/v1/llm/chats/current` - the stored current chat, or `null`.
- `DELETE /api/v1/llm/chats/current` - forget the pointer without deleting the chat.
- `POST /api/v1/llm/chats` - create a chat and make it current.
- `GET /api/v1/llm/chats/{id}` - one chat with its messages.
- `DELETE /api/v1/llm/chats/{id}` - delete a chat and clear the pointer.

`POST /api/v1/llm/chat` gains four optional fields:

- `chat_id` - continue an existing chat.
- `use_history` (default true) - prepend the chat's last turns.
- `history_limit` (default 20, max 40) - how many turns to prepend.
- `persist` (default true) - append the new exchange to the chat.

The response now includes `chat_id` (new or continued) and `persisted`. Both
the flat `messages` list and the `history.messages` tree are written, matching
the shape the Open WebUI frontend expects. Chat writes use the per-user Open
WebUI token from Phase 4; without `OPENWEBUI_TRUSTED_AUTH=true` the chat routes
return 503 and `/chat` still answers without storing anything.

Regression tests: `server/tests/test_llm_chats.py` (20 tests).

## Web AI chat UI (Phase 7)

The web frontend (`server/frontend`) has an **AI** tab, server mode only:

- the left sidebar lists the signed-in user's Open WebUI chats; selecting one
  loads its messages;
- the composer calls `POST /api/v1/llm/chat` with `chat_id`, `use_history` and
  `persist`, so the thread continues with context;
- **+ New chat** clears the current-chat pointer (the previous chat stays in
  the list);
- delete removes the chat from Open WebUI and clears the pointer when it was
  current;
- a "Spotify tools" toggle controls the MCP tool loop;
- if `OPENWEBUI_TRUSTED_AUTH` is off, or the per-user token cannot be obtained,
  the UI falls back to stateless answers and says they are not saved.

Verified with Playwright against the live stack: send -> answer -> reload
resumes the stored answer -> New chat clears the pointer -> delete empties the
list. Frontend build and the 39 render checks pass.

## Android AI chat (React + Kotlin)

Both Android clients use the same `/api/v1/llm/*` routes in media-server mode;
the Open WebUI credential never leaves the server.

React/Capacitor (`src/components/AIAssistantDialog.tsx`,
`src/services/LLMService.ts`):

- a Chats panel lists the user's stored chats, resumes one, starts a new chat
  (clears the pointer) and deletes with confirmation;
- with history on, only the new user turn is sent (`chat_id`, `use_history`,
  `persist`); the server prepends the stored context;
- if the server returns `llm_chat_unavailable`, the dialog retries once
  statelessly (`persist:false`, `use_history:false`) and says answers are not
  saved;
- verified with `npm test` (62 tests), `npm run build`, and a live Playwright
  flow on desktop and a 390 px mobile viewport.

Kotlin (`ui/AiAssistantDialog.kt`, `ui/MainViewModel.kt`,
`repository/DashboardRepository.kt`, `api/DashboardApiService.kt`):

- Tools tab -> **AI assistant**, enabled in media-server mode only;
- same list/resume/new/delete behavior, plus expandable reasoning and Spotify
  tool details;
- DTOs mirror the contract (`chat_history`, `chat_id`, `persisted`); contract
  error bodies are parsed so `llm_chat_unavailable` triggers the stateless
  fallback;
- verified with `gradlew :app:testDebugUnitTest` (109 tests) and
  `:app:assembleDebug` (debug APK builds);
- on-device smoke test passed on a Redmi 2201117PG (Android 13) against the
  live stack via the LAN dev proxy: install, live model status, send/receive,
  cold-relaunch resume, **+ New**, reopen from the chat list, and delete with
  confirmation.

## Notes

- This is experimental. Features may not work. Expect rough edges.
- The LLM is optional β€” the app works without it (endpoints return 503 if Ollama is unreachable).
- Model recommendation: Llama 3.1 8B (good balance of quality and speed on PC).
- On-device LLM (phone) is a separate, future effort (see Kanso audit).
