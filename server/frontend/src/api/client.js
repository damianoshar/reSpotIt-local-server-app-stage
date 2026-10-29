/**
 * All API calls go through nginx on the same origin by default.
 * nginx proxies /api/* → FastAPI; vite does the same in dev.
 * Canonical paths: API-PARITY-PLAN §1 (/api/v1/...).
 *
 * The base is configurable because remote mode can point at another host's
 * backend. `null` means "this page's own origin" and is left as a relative URL.
 */

/** @type {string|null} */
let BASE = null

export function setApiBase(base) {
  BASE = base ? String(base).trim().replace(/\/+$/, '') : null
}

export function getApiBase() {
  return BASE
}

function url(path) {
  return `${BASE ?? ''}${path}`
}

/** @type {string|null} */ let accessToken  = null
/** @type {string|null} */ let refreshToken = null
/** JWT user cached from the last login ({id, email}) for the header chip. */
/** @type {{id: string, email: string}} */ let user = null

const STORAGE_KEY = 'reSpotIt_jwt_session'

function readStoredSession() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {} } catch { return {} }
}

function storeSession(session) {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else          localStorage.removeItem(STORAGE_KEY)
  } catch { /**/ }
}

const stored = readStoredSession()
accessToken  = stored.access_token  ?? null
refreshToken = stored.refresh_token ?? null
user         = stored.user          ?? null

function saveSession(body) {
  accessToken  = body.access_token ?? accessToken
  refreshToken = body.refresh_token ?? refreshToken
  const nextUser = body.user ?? user
  user = (typeof nextUser?.id === 'string')
    ? { id: nextUser.id, email: nextUser.email ?? nextUser?.email ?? user?.email }
    : user
  storeSession({
    access_token: accessToken, refresh_token: refreshToken, user,
  })
}

function clearSession() {
  accessToken = refreshToken = null
  user = null
  storeSession(null)
}

/**
 * Error carrying the contract's HTTP status and machine-readable code.
 *
 * This client used to throw `${status} ${rawBody}`, so callers could only
 * string-match the text — which is how `not_connected` and `no_albums` ended up
 * indistinguishable from every other failure. `errorCodes.js` maps the code to
 * canonical wording instead.
 */
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function parseError(res) {
  const payload = await res.json().catch(() => null)
  // FastAPI HTTPException errors arrive as {"detail": "..."}; contract-style
  // errors (and validation) as {"error": ...} / {"detail": [...]}, so read all
  // three shapes and use the first one that is actually text.
  const rawDetail = payload?.detail
  const detailText =
    typeof rawDetail === 'string' ? rawDetail :
    Array.isArray(rawDetail)
      ? rawDetail.map((d) => d?.msg ?? String(d)).join('; ')
      : null
  const err = payload?.error
  const code = err && typeof err === 'object' ? err.code : undefined
  const message =
    (err && typeof err === 'object' && typeof err.message === 'string' && err.message) ||
    (typeof err === 'string' ? err : null) ||
    (typeof payload?.message === 'string' ? payload.message : null) ||
    detailText ||
    (await res.text().catch(() => '')) ||
    res.statusText ||
    'Request failed'
  return new ApiError(res.status, typeof code === 'string' ? code : undefined, message)
}

/** One refresh attempt; returns true when a fresh access token is in place. */
async function rotateAccessToken() {
  if (!refreshToken) return false
  const res = await fetch(url('/api/v1/auth/refresh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!res.ok) return false
  const body = await res.json()
  if (!body?.access_token) return false
  saveSession(body)
  return true
}

async function req(path, options = {}) {
  const doFetch = () => {
    const headers = new Headers(options.headers || {})
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    return fetch(url(path), { ...options, headers })
  }

  let res = await doFetch()
  // One refresh-and-retry: a failed access token rotates on its way out,
  // instead of forcing a hard sign-out on every expiry.
  if (res.status === 401) {
    if (await rotateAccessToken()) res = await doFetch()
  }
  if (!res.ok) {
    const err = await parseError(res)
    if (res.status === 401) clearSession()
    throw err
  }
  return res.json()
}

/** CSV export as an authenticated download (no anchor-href target). */
async function exportApi(path) {
  const blob = await exportApiBlob(path)
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = '' // server supplies the Content-Disposition filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}

async function exportApiBlob(path) {
  const res = await fetch(url(path), {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
  })
  if (!res.ok) throw await parseError(res)
  return res.blob()
}

export const api = {
  // ── JWT user session ───────────────────────────────────────────────────────
  register: (email, password) => req('/api/v1/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }),
  login: (email, password) => req('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }),
  refreshTokens: rotateAccessToken,
  authStatus: () => req('/api/v1/auth/status'),
  me:         () => req('/api/v1/auth/me'),
  logoutJWT:  () => req('/api/v1/auth/logout', { method: 'POST' }),
  hasSession: () => Boolean(accessToken) || Boolean(refreshToken),
  clearSession,
  saveSession,

  // ── Auth ───────────────────────────────────────────────────────────────────
  // Spotify link state — not the JWT user session (that is /auth/status).
  spotifyStatus: () => req('/api/v1/spotify/status'),
  spotifyLogin:  () => req('/api/v1/auth/spotify/login'),
  getPlayerToken: () => req('/api/v1/spotify/player-token'),
  getPlayerState: () => req('/api/v1/spotify/player'),
  getPlayerQueue: () => req('/api/v1/spotify/player/queue'),

  // ── Jobs ───────────────────────────────────────────────────────────────────
  startFullSync: ({ clean = false, downloadImages = false } = {}) =>
    req('/api/v1/sync/albums', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clean, download_images: downloadImages }),
    }),
  getJob:    (id) => req(`/api/v1/jobs/${id}`),
  cancelJob: (id) => req(`/api/v1/jobs/${id}/cancel`, { method: 'POST' }),

  getSyncHistory: (limit = 10) => req(`/api/v1/sync/history?limit=${limit}`),

  startImages: () => req('/api/v1/images/sync', { method: 'POST' }),
  startLoad:   () => req('/api/v1/load/start',  { method: 'POST' }),

  // ── Albums ─────────────────────────────────────────────────────────────────
  getStats:  () => req('/api/v1/albums/stats'),

  // Authenticated Csv download of this user's library (the old plain link
  // could not carry an Authorization header once the route was gated).
  exportCsv: () => exportApi('/api/v1/albums/export'),
  exportCsvBlob: () => exportApiBlob('/api/v1/albums/export'),
  exportHistory: () => req('/api/v1/exports/history'),

  getAlbums: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v === null || v === undefined || v === '') return
      if (k === 'min_pop' && v === 0)   return
      if (k === 'max_pop' && v === 100) return
      qs.set(k, v)
    })
    return req(`/api/v1/albums?${qs}`)
  },

  // ── Artists ────────────────────────────────────────────────────────────────
  getArtists: (search = '') => {
    const p = new URLSearchParams({ limit: 500 })
    if (search) p.set('search', search)
    return req(`/api/v1/artists?${p}`)
  },

  // ── Spotify actions ────────────────────────────────────────────────────────
  getPlaylists: () => req('/api/v1/playlists'),

  createPlaylist: (name, description, albumIds) =>
    req('/api/v1/playlists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, album_ids: albumIds }),
    }),

  addToPlaylist: (playlistId, albumIds) =>
    req(`/api/v1/playlists/${playlistId}/tracks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ album_ids: albumIds }),
    }),

  getPlaylistAlbums: (playlistId, params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v === null || v === undefined || v === '') return
      qs.set(k, v)
    })
    return req(`/api/v1/playlists/${playlistId}/albums?${qs}`)
  },
  getPlaylistMeta:   (playlistId) => req(`/api/v1/playlists/${playlistId}/meta`),
  syncPlaylist:      (playlistId) =>
    req(`/api/v1/playlists/${playlistId}/sync`, { method: 'POST' }),
  deletePlaylist: (playlistId) =>
    req(`/api/v1/playlists/${playlistId}`, { method: 'DELETE' }),
  playlistExportCsv: (playlistId) => exportApi(`/api/v1/playlists/${playlistId}/export`),

  addToQueue: async (albumIds, onProgress) => {
    const started = await req('/api/v1/queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ album_ids: albumIds }),
    });
    if (!started?.job_id) throw new Error('Server did not return a queue job');
    for (;;) {
      const job = await req(`/api/v1/jobs/${started.job_id}`);
      if (job.status === 'done' || job.status === 'cancelled') {
        const r = job.result || {};
        return { queued: r.imported ?? 0, failed: r.skipped ?? 0 };
      }
      if (job.status === 'error') throw new Error(job.error || 'Queue failed');
      if (onProgress) onProgress(job);
      await new Promise((r) => setTimeout(r, 2000));
    }
  },

  // -- Parity: playlist metadata, retention, visibility -----------------------
  getPlaylistRetention: () => req('/api/v1/playlists/retention'),
  setPlaylistRetention: (playlistId, { hours = null, until = null } = {}) =>
    req(`/api/v1/playlists/${playlistId}/retention`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ retention_hours: hours, retention_until: until }),
    }),
  extendPlaylistRetention: (playlistId, hours) =>
    req(`/api/v1/playlists/${playlistId}/retention/extend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours }),
    }),
  keepPlaylistForever: (playlistId) =>
    req(`/api/v1/playlists/${playlistId}/retention`, { method: 'DELETE' }),
  deletePlaylistNow: (playlistId) =>
    req(`/api/v1/playlists/${playlistId}/retention/delete-now`, { method: 'POST' }),
  setPlaylistVisibility: (playlistId, isPublic) =>
    req(`/api/v1/playlists/${playlistId}/visibility?public=${isPublic ? 'true' : 'false'}`, {
      method: 'PUT',
    }),

  // -- Parity: album tracks and playlist removals -----------------------------
  getAlbumTracks: (albumId) => req(`/api/v1/albums/${albumId}/tracks`),
  removeAlbumsFromPlaylist: (playlistId, albumIds) =>
    req(`/api/v1/playlists/${playlistId}/albums`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ album_ids: albumIds }),
    }),
  removeTracksFromPlaylist: (playlistId, uris) =>
    req(`/api/v1/playlists/${playlistId}/tracks`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uris }),
    }),
  queueTrackUris: (uris) =>
    req('/api/v1/queue/tracks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uris }),
    }),

  // -- Parity: library clear and local-to-server push --------------------------
  clearLibrary: () => req('/api/v1/albums', { method: 'DELETE' }),
  importCsv: (csvContent, replace = false) =>
    req('/api/v1/import/csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv_content: csvContent, replace }),
    }),

  // -- Parity: Spotify account tools ------------------------------------------
  followArtistsFromLibrary: () =>
    req('/api/v1/spotify/follow-artists', { method: 'POST' }),
  removeSavedAlbums: (albumIds) =>
    req('/api/v1/spotify/albums', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ album_ids: albumIds }),
    }),
  saveSpotifyAlbums: (albumIds) =>
    req('/api/v1/spotify/albums/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ album_ids: albumIds }),
    }),
  searchSpotifyCatalog: (query, limit = 8) => {
    const qs = new URLSearchParams({ q: query, limit: String(limit) })
    return req(`/api/v1/spotify/catalog/search?${qs}`)
  },
  getArtistAlbums: (artistId) =>
    req(`/api/v1/spotify/artists/${encodeURIComponent(artistId)}/albums`),
  getSpotifyAlbums: (ids) =>
    req(`/api/v1/spotify/albums?ids=${encodeURIComponent(ids.join(','))}`),

  // -- Parity: direct item add ------------------------------------------------
  addItemsToPlaylist: (playlistId, uris) =>
    req(`/api/v1/playlists/${playlistId}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uris }),
    }),

  // JWT sign-out is client-side (the server keeps the Spotify link on the
  // account); the old /auth/token DELETE unlinked it, which is not what
  // "sign out" should do.
  signOut: () => req('/api/v1/auth/logout', { method: 'POST' }),
}
