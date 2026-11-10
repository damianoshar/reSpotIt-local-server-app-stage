# Experimental Features — LLM-Enhanced reSpotIt

> Status: **Experimental / Work in progress.** Features may not work. Expect rough edges.

## Overview

reSpotIt can be enhanced with a local LLM (running on PC via Ollama / OpenWebUI) to provide
intelligent library management. The Android app (React or Kotlin) connects to the reSpotIt
backend in **remote mode** and calls new `/api/v1/llm/*` endpoints that proxy to the local LLM.

This is **not overkill**: it reuses the existing Python backend + Docker stack. The Android app
just calls new API endpoints — no on-device model needed.

## Architecture

```
Android (React/Kotlin)  →  reSpotIt Backend (FastAPI, Docker)  →  Ollama (LLM)
                                    ↓
                              OpenWebUI (optional, for chat UI)
```

- **PC:** Docker stack runs reSpotIt backend + Ollama + OpenWebUI.
- **Android:** Connects to backend via remote mode. Calls `/api/v1/llm/*` endpoints.
- **LLM:** Ollama serves models (e.g., Llama 3.1 8B, Mistral 7B). Configurable URL.

## Proposed Features (all kept)

### 1. Natural Language Playlist Creation
- **Input:** "Make a playlist of jazz albums I saved in 2023"
- **Flow:** LLM parses intent → backend filters library → creates playlist → returns result.
- **Endpoints:** `POST /api/v1/llm/playlist/create` (body: `{ prompt: string }`)
- **Effort:** Medium

### 2. Library Q&A / Natural Language Search
- **Input:** "What genres am I missing?" / "Which artists do I have the most albums from?"
- **Flow:** LLM translates query to filter/SQL → backend executes → returns results.
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
- **Flow:** LLM plans moves → backend executes with confirmation.
- **Endpoints:** `POST /api/v1/llm/reorganize` (body: `{ instruction: string }`)
- **Effort:** High

## Backend Changes (Python)

- Add `LLM_SERVICE_URL` env var (default: `http://ollama:11434` in Docker, `http://localhost:11434` locally).
- Add `server/api/services/llm_service.py` — proxies to Ollama's `/api/generate` endpoint.
- Add `server/api/routers/llm.py` — FastAPI router with the endpoints above.
- Register router in `main.py`.
- Add `ollama` service to `docker-compose.yml`.

## Android Changes (React + Kotlin)

- Add `LLMService.ts` / `LLMService.kt` — calls backend `/api/v1/llm/*` endpoints.
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

- [x] Backend LLM service + router
- [x] Docker compose update (Ollama + OpenWebUI)
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
- [x] LLM prompt/response visibility (llama-server verbose log + `LLM_TRACE`)
- [x] AI scan source persistence (`scan_sources`, migration 015)
- [x] Chunked map-reduce extraction (raised the 6k/20k caps)
- [x] Large-input file upload for scans
- [x] Open WebUI ↔ MinIO S3 wiring
- [x] Open WebUI ↔ Redis websocket wiring
- [ ] Optional RAG source library + Q&A

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

- [x] WebView page snapshot -> concert scan (Kotlin, 2026-11-09). The "Add from
      site" browser gained **Scan this page for concerts (AI)**: it evaluates
      `document.body.innerText` on the *rendered* page and uploads that text
      through the existing multipart path with a new optional `source_url` form
      field (`source_kind=page`). This is the only way to scan JS-rendered
      listings (Bandsintown etc.), which a server-side fetch sees as empty. The
      server never re-fetches `source_url`; it only labels the scan. The
      concerts dialog gained "Open in browser and scan the page", which hands
      its URL to the browser and returns to the review list after the snapshot.
      Live-verified: 4/4 events extracted from a snapshot, `kind=page`,
      `source_url` preserved.
      A Songkick city page (day-first dates) first returned 0 concerts:
      `_looks_like_events` only matched month-first dates (`Nov 13`), so the
      empty-answer retry never fired. The heuristic now also matches day-first
      (`04 December 2026`) and ISO dates (`bd12649`); the same snapshot went
      0 -> 38 concerts.
- [x] WebView page snapshot -> concert scan (React main + librespot, 2026-11-09).
      Same flow in the Capacitor builds: the native `AddFromSite` plugin takes
      `mode: 'concerts'` (button reads **Scan concerts**, no Spotify-link
      detection, no auto-scan on page load) and resolves `{ids, url, text,
      cancelled}` after evaluating `document.body.innerText`. The JS bridge adds
      `openConcertPageSnapshot`; `ConcertsDialog` shows **Open in browser and
      scan** only in the native app, uploads the captured text through
      `uploadRemoteConcertScan(base, file, sourceUrl)` and returns to the
      pending-review list. `npm run build` + `cap sync android` +
      `compileDebugJavaWithJavac` pass in both repos; release APKs built,
      on-device tap-through not yet repeated on the React builds.
- [x] Recent searches + saved links (React main, React librespot, Kotlin,
      2026-11-09). Each page/URL entry point now keeps a device-local history:
      **Concerts** (scan concerts), **Albums** (scan page with AI and pasted
      Spotify links) and **Add from site**. Recent entries are recorded when a
      scan starts (newest first, de-duplicated, capped at 8) and can be
      re-applied with one tap; **Save link** pins a value to a 40-entry list
      with an inline remove control. Pasted text is stored as text and labelled
      by its first line, URLs by host + path. React stores in `localStorage`
      (`respotit.linkHistory.v1.<bucket>`, `src/services/linkHistory.ts`) with a
      pub/sub so an open dialog refreshes; Kotlin stores JSON in
      `SharedPreferences` (`link_history_v1`, `LinkHistoryStore`) with a Compose
      `LinkHistoryBus` write counter. Kotlin uses one `albums` bucket because
      its `AiUrlScanDialog` serves both the AI scan and the pasted-links mode.
      Unit tests cover de-duplication, caps, bucket isolation, corrupt storage
      and subscriber notification (12 tests).
- [x] WebView page snapshot -> **album** scan (Kotlin, 2026-11-10). The "Add from
      site" browser gained a second snapshot button, **Scan this page for albums
      (AI)**, next to the concert one. The album scan dialog gained **Open in
      browser and scan**: it hands its URL to the browser and returns to the
      dialog with the typed URL preserved (`albumScanUrl` hoisted in
      `DashboardScreen.kt`, `417fc2b`). The snapshot evaluates
      `document.body.innerText` on the *rendered* page and posts it to
      `POST /api/v1/llm/extract-albums` — the same path the concert scan uses,
      so JS-rendered charts work without a server-side fetch.
- [x] Same flow for the React clients (main + librespot, 2026-11-10). The native
      `AddFromSite` plugin takes `mode: 'page'`; `AiUrlScanDialog` calls
      `openAlbumPageSnapshot`. `tsc --noEmit` clean, 72 vitest tests green, debug +
      release APKs built in both repos.
- [x] Long album pages are chunked server-side (2026-11-10). `extract_albums`
      splits the page into 24,000-char chunks with 1,000-char overlap
      (`ALBUM_SCAN_CHUNK_CHARS` / `ALBUM_SCAN_CHUNK_OVERLAP`, env-overridable) and
      de-duplicates the pairs case-insensitively (`5faaebb`). The album prompt now
      ignores chart ranks, position text, scores and vote counts so titles stay
      clean (`6611f59`). Live check: a 24.5 k-char page -> 2 chunks -> 30 clean
      `(artist, album)` pairs. `/api/v1` unchanged — chunking and prompt wording
      are server internals, so every client inherits the fix.
- [x] On-device verification (Kotlin release APK, 2026-11-10). APK SHA-256
      `6C568E9EEED930C90146D3AABEF65A06202865D17F05D7DC7523E9648807B9B4`
      installed on the Xiaomi 2201117PG; the installed `base.apk` matches the
      built artifact byte-for-byte. Flow: Tools -> "Scan page with AI (albums)" ->
      recent URL -> "Open in browser and scan" -> "Scan this page for albums (AI)".
      Server side: `extract-albums` 200 -> `resolve-albums` 200 -> `import/csv`
      200, with the LLM returning 50 clean `(artist, album)` pairs for the
      Sputnikmusic 2026 chart; the dialog came back with the URL preserved.
      Kotlin LLM calls use a dedicated client with a 15-minute read timeout
      (`73fd8c6`) because the extraction is synchronous and chunked — the previous
      60 s timeout aborted the request. The library count did not grow on that
      run because those albums were already in the server library (12,488 albums),
      so `import/csv` upserted instead of inserting.

Known follow-ups:
- Kotlin `DashboardApiService` uses `@Body Map<String, Any>` for the extract/resolve
  routes, which Retrofit rejects ("parameter type must not include a type variable
  or wildcard"). Fix: concrete body DTOs. Blocks the Kotlin scan at runtime.
- Backend `extract_structured` calls the LLM once; plan edge case (retry once with
  stricter prompt on non-JSON) is not implemented. Causes "model did not return
  correct json" on some pages.
- ~~Kotlin dialogs accept URL only; React also accepts pasted text.~~ Fixed: Kotlin
  `ConcertsDialog` now has a paste field (pasted text uploads as a `.txt` file)
  and an attach-file button; `AiUrlScanDialog` keeps URL-only.
- **Fixed 2026-11-09** (`462aeea` + Kotlin `85d9942`): scan correlation showed
  "0 followed" and no followed artists. `resolve_artists` paginated the whole
  followed library (~64 serial Spotify calls for 3,183 artists) and then
  searched the catalog for every non-followed name serially, so a 67-artist scan
  took 65 s; the Kotlin dialog's `withTimeoutOrNull(30_000)` silently discarded
  the result. Now followed status comes from the batched
  `/me/following/contains` call (50 ids per request), catalog searches run
  concurrently (8 workers), the followed list is used from a short-lived cache
  (a cold cache is warmed in the background), and the Kotlin cap is 120 s.
  Measured: same 4 followed of 67 in ~3.6 s cold / ~3.3 s warm.

## AI text pipeline: source archive + chunked extraction (planned)

Full plan: `docs/AI-TEXT-PIPELINE-PLAN.md` (Kanso card 565).

The scan path currently loses data: URL text is truncated to 6,000 chars, pasted
text is capped at 20,000, and `create_scan` keeps only `source[:120]`. Fix in
phases:

- [x] **Source persistence** — migration `015` + `scan_sources` (full text,
      `sha256`, `chars`, kind), `source_id`/`chunk_count` on `concert_scans`.
- [x] **Chunked map-reduce** — overlapping chunks, per-chunk extraction, merge +
      dedupe on `(artist, date, venue)`, per-chunk progress; raised caps.
- [x] **File upload** — `POST /api/v1/concert-scans/upload` (multipart), stores
      stripped text (`kind=file`). Attach-file button + paste-as-file in the
      React (main + librespot) and Kotlin clients.
- [x] **MinIO S3 wiring** — `STORAGE_PROVIDER=s3` + `S3_*` on both Open WebUI
      services; env-driven MinIO credentials (`MINIO_*`).
- [x] **Redis websocket wiring** — `WEBSOCKET_MANAGER=redis` +
      `WEBSOCKET_REDIS_URL` on both Open WebUI services.
- [ ] **Optional RAG Q&A** — index `scan_sources` into the existing Chroma
      (`all-MiniLM-L6-v2`) for a cross-source "ask my sources" feature with
      citations. Retrieval is only for Q&A, *not* for extraction.
- [x] **Album extraction chunking** — `extract_albums` chunks long pages
      (24,000 chars / 1,000 overlap, env-overridable) and de-duplicates the pairs
      case-insensitively (`5faaebb`, 2026-11-10). The `scan_sources` archive and
      the per-chunk progress UI are still **concert-only**; an album scan is one
      synchronous request whose result arrives with the whole page.

RAG is deliberately not used for extraction: top-k retrieval drops events when
the query is generic. Chunked extraction preserves recall.

**Scan latency:** generation (~9.5 tok/s on the local 9B) was ~80% of a scan, not
parsing. Two independent causes, both fixed:

1. **Output tokens.** Rows were cut to compact `[artist, date, venue]` arrays (no
   `url`), and retry nudges moved to the user message so the llama.cpp prompt
   cache survives.
2. **VRAM spill (the bigger one).** The model has **no MoE experts**
   (`n_expert=0`), so the old `-ot ...exps=CPU` flag matched nothing. The server
   was really demanding ~8.9 GB (model 4.5 + KV 3.3 + compute 1.0) on a 6 GB GPU,
   spilling ~3.7 GB to host RAM every token. `-c 16384 --flash-attn on` cut the
   KV cache to ~300 MiB and the compute buffer to 144 MiB; everything now fits
   with ~930 MiB free.

Measured on the same source: prompt eval 104 → **1,733 tok/s**, generation
9.5 → **53.4 tok/s**, scan wall time 259 s → **37 s** (all rows dated).

Remaining options (grammar-constrained JSON, `-np`, smaller model, regex
pre-parse, boilerplate trimming, real `-ot` block offload) are in
`docs/AI-TEXT-PIPELINE-PLAN.md` §6.

### LLM prompt/response visibility (implemented)

- **Route A — model server:** `llama-server.exe --verbose --log-prefix
  --log-timestamps --log-file D:\huggingface\hub\llama-server.log` logs the
  rendered prompt and raw output.
- **Route B — app:** `LLM_TRACE=1` on the `api` service logs the exact
  `messages` array and response (`llm_service._trace`). Committed `586035c`.
- Both contain user text: keep local, don't commit, disable when done.

## Chat sync across all AI features (implemented)

Chat sync is now implemented across all AI features. Each scan/assistant action creates a chat
in Open WebUI that can be listed, resumed, and deleted.

- **AI Assistant**: full chat history (list/resume/new/delete) — already done.
- **Scan albums** (`extract_albums`): each scan = a chat; list recent, resume/refine.
- **Scan concerts** (`extract_concerts`): same; re-resolve followed status.
- **Future features** (duplicate explain, metadata enrich, playlist describe, reports, reorganize): each action = a chat thread.

Implementation:
1. Backend: reuse `/api/v1/llm/chat` with `chat_id`/`persist`/`use_history`. Added `chat_type` field (`assistant`, `extract_albums`, `extract_concerts`, `duplicate_explain`, etc.) for filtering.
2. React: `AiUrlScanDialog`/`ConcertsDialog` track `chat_id`, send `persist:true`, add "Recent scans" sidebar filtered by `chat_type`.
3. Kotlin: same + filter toggle in `AiAssistantDialog` history panel.
4. Open WebUI: chats appear in same list; type tag in title/metadata for filtering.

Scope: core extract→resolve→save unchanged; just adds resumable/refinable history.

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
- The LLM is optional — the app works without it (endpoints return 503 if Ollama is unreachable).
- Model recommendation: Llama 3.1 8B (good balance of quality and speed on PC).
- On-device LLM (phone) is a separate, future effort (see Kanso audit).

## Chat sync across all AI features (implemented)

Chat sync is now implemented across all AI features. Each scan/assistant action creates a chat
in Open WebUI that can be listed, resumed, and deleted.

- **AI Assistant**: full chat history (list/resume/new/delete) — already done.
- **Scan albums** (`extract_albums`): each scan = a chat; list recent, resume/refine.
- **Scan concerts** (`extract_concerts`): same; re-resolve followed status.
- **Future features** (duplicate explain, metadata enrich, playlist describe, reports, reorganize): each action = a chat thread.

Implementation:
1. Backend: reuse `/api/v1/llm/chat` with `chat_id`/`persist`/`use_history`. Added `chat_type` field (`assistant`, `extract_albums`, `extract_concerts`, `duplicate_explain`, etc.) for filtering.
2. React: `AiUrlScanDialog`/`ConcertsDialog` track `chat_id`, send `persist:true`, add "Recent scans" sidebar filtered by `chat_type`.
3. Kotlin: same + filter toggle in `AiAssistantDialog` history panel.
4. Open WebUI: chats appear in same list; type tag in title/metadata for filtering.

Scope: core extract→resolve→save unchanged; just adds resumable/refinable history.