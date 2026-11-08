# AI Text Pipeline — Source Persistence, Chunked Extraction, and Storage Wiring

**Status:** Phases 1–5 implemented (2026-11-08); Phase 6 (RAG Q&A) planned.
**Tracking:** Kanso board 11, card 565 (work), card 507 (LLM feature)
**Scope:** `reSpotIt-local-server-app` only. `/api/v1` stays additive.
**Last updated:** 2026-11-08

> **Implemented** in `841f356` (server: source archive + chunked extraction +
> upload) and `487fcb7` (compose: MinIO S3 + Redis websockets). Live-verified:
> migration `015` applied, a text scan persisted its 210-char source and
> returned 3 concerts, an HTML upload stored stripped text (`kind=file`) and
> returned 1 concert, the `openwebui` bucket exists in MinIO, and Redis holds
> `open-webui:*` keys. 134 server tests pass.

---

## 1. Why

The AI scan path currently throws away most of what it reads and caps what it accepts:

| Limit today | Where | Effect |
|---|---|---|
| URL text truncated to **6,000 chars** | `llm_service.fetch_page_text(..., max_chars=6000)` called from `concert_scan_service.run_scan` and `routers/llm.py` | Long pages lose every event after the first few screens |
| Pasted text capped at **20,000 chars** | `schemas.ConcertScanStart.text` | Large pastes rejected at the API boundary |
| Full source **discarded** | `concert_scan_service.create_scan` stores `source = text[:120]` | Scans cannot be re-run, audited, or searched |
| No file upload | `POST /api/v1/concert-scans` is JSON-only | Very large inputs hit the request-body limit |

The model context is large enough that these are configuration limits, not capacity limits. The fix is **chunked extraction plus a durable source archive** — *not* retrieval-augmented generation in front of the extractor.

### Why not RAG for extraction

RAG ranks chunks against a query and keeps the top-k. Extraction has no discriminating query ("find all concerts"), so top-k would silently drop real events. Retrieval is the wrong tool for exhaustive extraction. It is the right tool for a **separate** "ask across my saved sources" feature (Phase 6).

---

## 2. Phases

### Phase 1 — Source persistence (migration `015`)

Persist the full source so scans are re-runnable and auditable.

- New table `scan_sources` (user-scoped, `user_id` FK CASCADE):
  - `id` (uuid/text PK), `user_id`, `kind` (`text` | `url` | `file`),
  - `source_url`, `content` (full text), `sha256`, `chars`, `created_at`.
- Add `source_id` (nullable FK) and `chunk_count` (int) to `concert_scans`.
- `create_scan` writes `scan_sources` and keeps the existing 120-char `source` preview for UI compatibility.
- `run_scan` loads text from `scan_sources` (falls back to `source_text` param for old clients).
- Migration is **idempotent and guarded** (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`). Existing rows stay valid with `source_id = NULL`.
- Retention: sources follow the existing per-user retention sweep; add an explicit `DELETE /api/v1/concert-scans/{id}` cleanup of the linked source.

**Acceptance:** a 200 KB paste is stored byte-for-byte, hash matches, and a re-run produces the same output without the client resending text.

### Phase 2 — Chunked map-reduce extraction

- Split source into overlapping chunks (default 24,000 chars, 1,000-char overlap, configurable via env).
- **Map:** extract `{artist, date, venue, url}` per chunk with the existing `extract_concerts` prompt; keep the long background timeout (`SCAN_LLM_TIMEOUT = (5.0, 900.0)`).
- **Reduce:** merge and de-duplicate on a normalized `(artist, date, venue)` key; keep the first non-empty URL; count dropped duplicates.
- Progress: advance `stage` per chunk (`extracting 3/12`) so the Open WebUI chat and the scan row show real progress.
- Failure policy: a failed chunk is logged and skipped; the scan completes `ready` with a `message` noting N skipped chunks. Only a total failure marks `error`.
- Raise the caps: `ConcertScanStart.text` to a configurable large limit (or remove it in favour of file upload), and the URL `max_chars` to the full page (with a sane hard ceiling, e.g. 2 MB of text).

**Acceptance:** a page with events spread across 300 KB returns all events; a 12-chunk scan reports monotonic progress and finishes `ready`; a poisoned chunk does not fail the whole scan.

### Phase 3 — Large-input file upload

- Add `POST /api/v1/concert-scans/upload` (multipart `file`) that stores the file into `scan_sources` and starts the same scan. Accept `.txt`, `.md`, `.html`; extract text from HTML before storing.
- Keep JSON `POST /api/v1/concert-scans` for small pastes (backwards compatible).
- React + Kotlin: allow attaching a text/HTML file in the concerts scan dialog; show the stored size and chunk count.
- Keep the MCP/`api` container request-body limit in mind; uploads go through the API, not OpenWebUI.

**Acceptance:** a 1 MB HTML page uploads, stores, scans, and yields a pending review list; the phone never holds the full text after upload.

### Phase 4 — Restore MinIO S3 wiring (Open WebUI file storage)

The MinIO container exists but Open WebUI is **not** pointed at it. Restore the original wiring:

- `open-webui` and `open-webui-2`:
  - `STORAGE_PROVIDER: s3`
  - `S3_ACCESS_KEY_ID: ${MINIO_ROOT_USER}`
  - `S3_SECRET_ACCESS_KEY: ${MINIO_ROOT_PASSWORD}`
  - `S3_BUCKET_NAME: ${MINIO_BUCKET_NAME:-openwebui}`
  - `S3_ENDPOINT_URL: http://minio:9000`
  - `S3_REGION_NAME: ${MINIO_REGION:-us-east-1}`
  - `S3_ADDRESSING_STYLE: path`
- Replace hardcoded `minioadmin` in the `minio` / `create-bucket` services with `${MINIO_ROOT_USER:-minioadmin}` / `${MINIO_ROOT_PASSWORD:-minioadmin}` (keep defaults so existing local data still boots).
- Add `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET_NAME`, `MINIO_REGION` to `.env.example` (values empty/defaulted, **no real secrets**).
- Verify: upload a file in Open WebUI, confirm the object lands in the `openwebui` bucket.

**Acceptance:** Open WebUI uploads/downloads through MinIO; restarting the stack preserves the object; no credentials are committed.

### Phase 5 — Restore Redis websocket wiring

The `redis` (valkey) container exists but Open WebUI runs without a websocket manager. Restore:

- `open-webui` and `open-webui-2`:
  - `ENABLE_WEBSOCKET_SUPPORT: "true"`
  - `WEBSOCKET_MANAGER: redis`
  - `WEBSOCKET_REDIS_URL: redis://redis:6379/1`
  - `REDIS_KEY_PREFIX: open-webui`
- Keep Redis internal (no host port needed for the websocket path).
- Verify: two browser sessions see live updates; `redis-cli -n 1 KEYS 'open-webui*'` shows activity.

**Acceptance:** Open WebUI websockets are backed by Redis; no cross-instance session desync.

### Phase 6 — Optional: RAG source library + Q&A

Only after Phases 1–3 are stable. This is retrieval over the **archive**, not the extractor.

- Index `scan_sources.content` into the existing Chroma vector store
  (`docker-data/open-webui/vector_db/chroma.sqlite3`, `all-MiniLM-L6-v2` already cached).
- New endpoint `POST /api/v1/sources/ask` (`{question, source_ids?, top_k?}`) → retrieve chunks → answer with citations to `source_id` + offset.
- UI: "Ask my sources" in the AI assistant; results link back to the original scan.
- Guardrails: per-user collection, no cross-user retrieval, top-k surfaced in the response so truncation is visible.

**Acceptance:** a question about a pasted festival page returns an answer citing the correct source; no data crosses users.

---

## 3. Redis / MinIO gap report

Compared with the original stack at
`C:\Users\Damianos\Downloads\projects\githubs\harharidisdamianos-project-main\docker-compose.yaml`:

| Capability | Original stack | Current `docker-compose.full.yml` | Gap |
|---|---|---|---|
| MinIO service | ✅ `minio` + `create-bucket` | ✅ both present (bind-mounted `./docker-data/minio`) | none |
| Open WebUI file storage | `STORAGE_PROVIDER=s3` + full `S3_*` block on both `open-webui` and `open-webui-2` | ❌ no `STORAGE_PROVIDER` / `S3_*` | **not wired** — uploads use local disk |
| MinIO credentials | env-driven (`${MINIO_ROOT_USER}` / `${MINIO_ROOT_PASSWORD}`) | hardcoded `minioadmin` in `minio` + `create-bucket` | **hardcoded** |
| `.env.example` MinIO keys | present in original env | ❌ none | **missing** |
| Redis service | ✅ `redis` | ✅ `redis` (valkey) present | none |
| Open WebUI websockets | `ENABLE_WEBSOCKET_SUPPORT=true`, `WEBSOCKET_MANAGER=redis`, `WEBSOCKET_REDIS_URL=redis://redis:6379/1`, `REDIS_KEY_PREFIX=open-webui` | ❌ none | **not wired** — single-process websockets only |
| Redis Insight | ✅ | ✅ `redis-insight` :5540 | none |

**Net:** both containers run, but neither is connected to Open WebUI. Phase 4 and Phase 5 close the gap. This is a wiring/config change, not a new service.

---

## 4. Rollout

| Step | Change | Verification |
|---|---|---|
| 1 | Migration `015` + `scan_sources` model + `create_scan`/`run_scan` | server tests; 200 KB paste round-trip |
| 2 | Chunked map-reduce + progress | multi-chunk scan on a long page |
| 3 | Upload endpoint + React/Kotlin attach | 1 MB upload from phone |
| 4 | MinIO env restore | upload in Open WebUI, object in bucket |
| 5 | Redis websocket env restore | two sessions live-update |
| 6 | RAG Q&A (optional) | cited answer, per-user isolation |

**Rollback:** each phase is additive. Migration `015` creates new tables/columns only; old clients ignore them. Compose env changes are reverted by dropping the keys. No destructive migration.

---

## 5. Acceptance criteria (whole plan)

- [x] Full source text is persisted and hash-verifiable for text, URL, and file scans.
- [x] Extraction is exhaustive across long inputs (no silent 6k/20k truncation).
- [x] Scan progress is monotonic and visible in both the scan row and the Open WebUI chat.
- [x] JSON paste still works unchanged for small inputs (`POST /api/v1/concert-scans`).
- [x] Open WebUI file uploads land in MinIO; websockets use Redis.
- [x] No secrets, tokens, or signed URLs are committed; `docker-data/` stays gitignored.
- [x] `/api/v1` remains additive; existing clients keep working.

Phases 1-5 + client upload are shipped and verified. Phase 6 (optional RAG Q&A
over `scan_sources`) is the only open item.

---

## 6. Scan latency — measured budget and what to try

A 10,566-char Bandsintown page on the local model, measured from llama.cpp
timings in the API log (2026-11-09):

| Stage | Speed | Cost on an 80-concert page |
|---|---|---|
| Prompt eval | ~104 tok/s (4,437 tokens) | ~43 s |
| **Generation** | **~9.5 tok/s (2,677 tokens)** | **~282 s** |
| Total | | ~325 s (observed scans: 352 / 579 / 750 s) |

**Generation dominates.** Every saved output token is worth ~0.1 s. Rows used to
cost ~30 tokens each (four named keys, `"url"` always empty).

### Applied

| # | Change | Effect |
|---|---|---|
| 1 | Compact rows: `{"concerts": [["artist","date","venue"], ...]}` instead of objects, no `url` key | ~12 tokens/row instead of ~30 — roughly 2.5× faster generation |
| 2 | Legacy object rows still parse (mixed answers, older prompts) | no regression |
| 3 | Retry nudges appended to the **user** message, never the system prompt | llama.cpp reuses the prompt cache by prefix, so a retry no longer re-evaluates the whole page (was ~4,400 tokens ≈ 43 s + full generation) |
| 4 | Empty/undated answers retried once (`_looks_like_events` gate) | rescues "Found 0 concert(s)" on a page full of events; live-verified: retry turned `{"concerts": []}` into **87 concerts** |
| 5 | `fail_orphaned_scans()` at startup | a restart no longer leaves clients polling a scan that no worker will finish |

### Still on the table (not applied)

| # | Change | Expected | Notes |
|---|---|---|---|
| 6 | Grammar-constrained JSON (GBNF / `response_format` schema) | 10-20% + no invalid-JSON retries | forces the shape, drops rambling |
| 7 | `-np 2..4` on llama-server | ~2-3× wall time when several scans run | currently `-np 1`, so concurrent scans serialize (two scans took 306 s and 413 s back to back) |
| 8 | Smaller model (4B) or lighter quant for extraction | ~2-3× | GPU is a 6 GB RTX 3060 at 100%; current flags push MoE experts to CPU (`-ot blk.18..40 exps=CPU`) |
| 9 | Deterministic regex pre-parse for regular listings (Bandsintown pattern: artist / `Fri, Nov 13 • 9 PM` / venue) | ~100% for those pages | LLM only for messy pages or name normalisation |
| 10 | Trim nav/footer boilerplate before extraction | ~10-20 s prompt eval, fewer empty answers | the source includes "With over 100 million fans..." promo text |
| 11 | Cap `max_tokens` per chunk adaptively | small | 4,096 is generous but generation stops at end-of-answer anyway |
| 12 | Speculative decoding / draft model | 1.5-2× | needs a matching draft model |

Measure with `LLM_TRACE=1` in `.env` and the `tokens_predicted` /
`predicted_per_second` fields the llama.cpp server returns in each completion.

---

*See also: `docs/STORAGE-POLICY.md`, `EXPERIMENTAL_FEATURES.md`, Kanso board 11 cards 565 and 507.*