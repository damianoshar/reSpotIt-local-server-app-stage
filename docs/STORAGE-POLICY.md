# Server / Client Storage Policy (canonical)

**Purpose:** Define which data lives where so that "when connected to a server all tools work and stored data syncs both ways."

---

## 1. Core rules

1. **Exactly one owner per datum** — every piece of stored data is either **Server-canonical** or **Device-only**. No datum is "sometimes local, sometimes server."
2. **No tool is mode-limited** — if a tool writes something canonical, it works in both modes; in remote mode it reads/writes the server.
3. **push/pull covers the whole canonical set** — not just albums.

---

## 2. Classification registry

| Datum | Owner | Local store today | Server today | Target |
|---|---|---|---|---|
| Albums / artists / tracks | **Server** | SQLite / Room | ✅ user-scoped tables | keep |
| Playlists + playlist tracks | **Server** (cache) | SQLite / Room | ✅ user-scoped cache of Spotify | push/pull cache |
| Playlist retention (expiry) | **Server** | `PlaylistRetentionService` | ✅ `/playlists/retention` | add to push/pull |
| **Concerts** | **Server** | SQLite / Room | ✅ `/concerts` | shipped (Phase B–D) |
| **Hidden duplicates** | **Server** | Preferences / `dedupe_prefs` | ✅ `/albums/hidden` | shipped (Phase B–D) |
| LLM chat sessions | **Server** | — | ✅ | keep |
| Server-side Spotify link / followed artists | **Server** | — | ✅ | keep |
| Queue playlist ref | **Device-only** | `QueuePlaylistStore` | — | never sync |
| Backup settings, server URL, mode, autohide, playback tuning, librespot keys | **Device-only** | Preferences / prefs | — | never sync |

> **Server-canonical = user-scoped.** Every row carries `user_id` (FK CASCADE to `users`), composite uniqueness `(user_id, spotify_id)` or `(user_id, id)`, and per-user indexes. The auth dependency (`get_current_user`) enforces isolation.

---

## 3. Sync semantics

| Operation | Semantics |
|---|---|
| **Push** (device → server) | Mirror the device's canonical data onto the signed-in server account using the canonical import endpoints with `replace=true`. The server becomes identical to the device. |
| **Pull** (server → device) | Mirror the server's canonical data onto the device's local store. Local SQLite/Preferences become identical to the server. |
| **Conflict resolution** | Server is authoritative for canonical data. Push always wins (replace). Device-only data is never touched. |
| **When** | Explicit user action only — no background/automatic sync. Both require: remote mode + signed-in server account. |

---

## 4. Feature/tool matrix (what works in remote mode)

| Tool | Local | Remote (target) | Notes |
|---|---|---|---|
| Library browse / stats / filters | ✅ | ✅ | `libraryRemote` |
| Playlist dashboard | ✅ | ✅ | `playlistRemote` |
| Playlist retention | ✅ | ✅ | `retentionRemote`; add to push/pull |
| AI album scan (URL/paste) | ✅ | ✅ | server LLM |
| Followed-artist correlation | ✅ | ✅ | `/spotify/resolve-artists` |
| **Concert scan + storage** | ✅ | ✅ | server table + CRUD/import (Phase B–D shipped) |
| **Duplicate finder** | ✅ | ✅ | remote album list + server blocklist (Phase B–D shipped) |
| Add-from-site | ✅ | ✅ | resolve only |
| CSV export | ✅ | ✅ | `/exports` |
| Queue playlist | ✅ | n/a | Device-only by design |

---

## 5. /api/v1 contract (additive only — no breaking changes)

### New migrations (idempotent, guarded)
- `012_concerts.sql`
- `013_hidden_albums.sql`

### New models (user-scoped, mirror `Album` pattern)
- `Concert`
- `HiddenAlbum`

### New routers (scoped via `get_current_user`)
| Router | Endpoints |
|---|---|
| `concerts.py` | `GET /api/v1/concerts`<br>`POST /api/v1/concerts` (upsert batch)<br>`DELETE /api/v1/concerts/{id}`<br>`DELETE /api/v1/concerts` (clear)<br>`POST /api/v1/concerts/import` (`{items, replace}`) |
| `hidden_albums.py` | `GET /api/v1/albums/hidden`<br>`POST /api/v1/albums/hidden` (hide)<br>`DELETE /api/v1/albums/hidden/{spotify_id}`<br>`DELETE /api/v1/albums/hidden` (restore all)<br>`POST /api/v1/albums/hidden/import` (`{items, replace}`) |

### Existing push/pull extended
- Push albums (existing `import_csv.py` `replace=true`) **+** concerts `import` **+** hidden `import`.
- Pull albums (existing paged fetch) **+** concerts list **+** hidden list.

---

## 6. Rollout & rollback

| Step | Action |
|---|---|
| 1 | Add migrations + models + routers + tests to `reSpotIt-local-server-app` |
| 2 | Add remote clients + storage facade + push/pull extension to `reSpotIt-react-version` |
| 3 | Add repository endpoints + ViewModel routing + push/pull extension to `reSpotIt-kotlin-version` |
| 4 | Verify each repo individually; round-trip test on device |
| 5 | (Optional) expose new tables via reSpotIt MCP |

**Rollback:** Deploy prior image. New tables are inert; old clients simply don't call the new routes. No destructive migration. `/api/v1` remains additive.

---

## 7. Device-only data (never synced)

| Key / Table | Reason |
|---|---|
| `QueuePlaylistStore` / `QueuePlaylistRef` | Playback state, not user data |
| `mode`, `server_url`, `autohide_nav`, `playback_tuning` | Per-device configuration |
| `librespot_credentials` / encryption keys | Security — never leave device |
| `backup_last_path`, `export_last_dir` | Filesystem references |

---

*Last updated: 2026-11-08*  
*See Kanso board 11, card 507 for implementation tracking.*