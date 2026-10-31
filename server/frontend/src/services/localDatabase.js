/**
 * Local (on-device) library, IndexedDB-backed.
 *
 * This is the local-mode counterpart of `api/client.js`. It deliberately
 * answers the same questions in the same shapes as the server — `queryAlbums`
 * returns `{items,total,page,limit}`, `getStats` returns the backend's stats
 * payload, `getArtistNames` returns `{id,name}` rows — so the hooks and
 * components branch once and render identically in both modes.
 *
 * ── Why the stored album carries two shapes ────────────────────────────────
 * The contract freezes a flat item twin (`id,title,artist,year,genre,
 * image_url,added_at`) and lets backends add extra keys. This backend returns
 * BOTH halves in every item: the flat twin plus the rich half the UI actually
 * renders (`name`, `artists[]`, `genres[]`, `release_date`, `popularity`,
 * `total_tracks`, `label`, `spotify_url`, `album_type`). So a local album is
 * normalised to the union: CSV import/export and filtering use the flat fields,
 * the components read the rich ones. `normalizeAlbum` is the single adapter.
 */

const DB_NAME = 'reSpotIt_local_library';
const DB_VERSION = 1;
const STORE = 'albums';

export const CSV_COLUMNS = ['id', 'title', 'artist', 'year', 'genre', 'image_url', 'added_at'];

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('This browser has no IndexedDB, so local mode is unavailable.'));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (db.objectStoreNames.contains(STORE)) return;
      const store = db.createObjectStore(STORE, { keyPath: 'id' });
      store.createIndex('name', 'name');
      store.createIndex('artist', 'artist');
      store.createIndex('added_at', 'added_at');
      store.createIndex('year', 'year');
      store.createIndex('popularity', 'popularity');
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error('Could not open the local database.'));
  });

  return dbPromise;
}

function txDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('Local database write failed.'));
    tx.onabort = () => reject(tx.error ?? new Error('Local database write aborted.'));
  });
}

function reqDone(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error('Local database read failed.'));
  });
}

async function readAll() {
  const db = await openDb();
  const tx = db.transaction(STORE, 'readonly');
  return reqDone(tx.objectStore(STORE).getAll());
}

// ---------------------------------------------------------------------------
// Normalisation: flat twin <-> rich fields
// ---------------------------------------------------------------------------

function splitList(value) {
  return String(value ?? '')
    .split(';')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Year from either the flat `year` or the rich `release_date`. */
function yearOf(raw) {
  const direct = Number(raw.year);
  if (raw.year !== '' && raw.year !== null && raw.year !== undefined && Number.isFinite(direct)) {
    return direct;
  }
  const match = /^(\d{4})/.exec(String(raw.release_date ?? ''));
  return match ? Number(match[1]) : 0;
}

/**
 * Canonical stored album: the union of the contract's flat twin and the rich
 * fields this app's components read. Safe to call on a server item (both halves
 * already present), a CSV row, or a hand-built object in a test.
 *
 * NOTE this is a FULL replacement for the row, not a merge: a field absent from
 * `raw` is written empty, so a flat-only object upserted over an existing rich
 * row would blank its rich half. Every writer here passes complete items (the
 * server returns both halves; CSV import refuses to touch existing ids), and a
 * future partial-update path would need a merge instead of this function.
 */
export function normalizeAlbum(raw = {}) {
  const id      = String(raw.id ?? raw.spotify_id ?? '').trim();
  const title   = String(raw.title ?? raw.name ?? '').trim();
  const year    = yearOf(raw);

  let artists = Array.isArray(raw.artists) && raw.artists.length
    ? raw.artists
        .map((a) => (typeof a === 'string' ? { name: a.trim() } : { name: String(a?.name ?? '').trim() }))
        .filter((a) => a.name)
    : splitList(raw.artist).map((name) => ({ name }));
  if (artists.length === 0 && raw.artist) artists = [{ name: String(raw.artist).trim() }];

  let genres = Array.isArray(raw.genres) ? raw.genres.map((g) => String(g).trim()).filter(Boolean) : [];
  if (genres.length === 0) genres = splitList(raw.genre);

  const artist = String(raw.artist ?? '').trim() || artists.map((a) => a.name).join('; ');
  const genre  = String(raw.genre ?? '').trim() || genres.join('; ');

  return {
    // Flat contract twin — filtering, sorting and CSV all use these.
    id,
    title,
    artist,
    year,
    genre,
    image_url: String(raw.image_url ?? ''),
    added_at: String(raw.added_at ?? ''),
    // Rich half — what AlbumCard / AlbumListRow / StatsPanel render.
    spotify_id: id,
    name: title,
    artists,
    genres,
    release_date: String(raw.release_date ?? '') || (year ? `${year}-01-01` : ''),
    album_type: String(raw.album_type ?? ''),
    popularity: raw.popularity === null || raw.popularity === undefined ? null : Number(raw.popularity),
    total_tracks: raw.total_tracks === null || raw.total_tracks === undefined ? null : Number(raw.total_tracks),
    label: String(raw.label ?? ''),
    spotify_url: String(raw.spotify_url ?? ''),
    image_file: raw.image_file ?? null,
  };
}

// ---------------------------------------------------------------------------
// Writes
// ---------------------------------------------------------------------------

export async function initDB() {
  await openDb();
}

export async function upsertAlbums(albums) {
  if (!albums || albums.length === 0) return;
  const db = await openDb();
  const tx = db.transaction(STORE, 'readwrite');
  const store = tx.objectStore(STORE);
  for (const album of albums) store.put(normalizeAlbum(album));
  await txDone(tx);
}

export async function upsertAlbum(album) {
  await upsertAlbums([album]);
}

export async function clearLibrary() {
  const db = await openDb();
  const tx = db.transaction(STORE, 'readwrite');
  tx.objectStore(STORE).clear();
  await txDone(tx);
}

export async function getExistingAlbumIds() {
  const db = await openDb();
  const tx = db.transaction(STORE, 'readonly');
  const keys = await reqDone(tx.objectStore(STORE).getAllKeys());
  return new Set(keys.map(String));
}

export async function countAlbums() {
  const db = await openDb();
  const tx = db.transaction(STORE, 'readonly');
  return reqDone(tx.objectStore(STORE).count());
}

// ---------------------------------------------------------------------------
// Query — same filter/sort semantics as api/routers/albums.py
// ---------------------------------------------------------------------------

const SORT_FIELDS = new Set(['name', 'title', 'artist', 'year', 'added_at', 'genre', 'popularity']);

/** Accepts contract `sort=title&order=asc` or the legacy combined `name_asc`. */
export function parseSort(sort = 'added_at_desc', order = '') {
  let field = 'added_at';
  let dir = 'desc';

  const raw = String(sort || '');
  const combined = /^(.*)_(asc|desc)$/.exec(raw);
  if (combined) {
    field = combined[1];
    dir = combined[2];
  } else if (raw) {
    field = raw;
    dir = String(order || '').toLowerCase() === 'asc' ? 'asc' : 'desc';
  }

  // `title` is the contract name for the column the server calls `name`.
  if (field === 'title') field = 'name';
  if (field === 'release_date') field = 'year';
  if (!SORT_FIELDS.has(field)) field = 'added_at';
  return { field, dir };
}

function sortValue(album, field) {
  switch (field) {
    case 'name':       return album.name || '';
    case 'artist':     return (album.artists?.[0]?.name ?? album.artist ?? '').replace(/^the\s+/i, '');
    case 'year':       return album.year || 0;
    case 'genre':      return (album.genres ?? []).join(',');
    case 'popularity': return album.popularity ?? null;
    case 'added_at':
    default:           return album.added_at || '';
  }
}

/**
 * Server semantics: `popularity >= min` excludes NULL popularity, but the
 * frontend omits min_pop=0 / max_pop=100 exactly like it omits them from the
 * query string, so an un-narrowed range keeps rows the server keeps.
 */
function matchesFilters(album, f) {
  if (f.search && !(album.name || '').toLowerCase().includes(f.search.toLowerCase())) return false;
  if (f.album_type && (album.album_type || '') !== f.album_type) return false;

  if (f.minPop > 0 && (album.popularity === null || album.popularity < f.minPop)) return false;
  if (f.maxPop < 100 && (album.popularity === null || album.popularity > f.maxPop)) return false;

  if (f.genre && !(album.genres ?? []).join(',').toLowerCase().includes(f.genre.toLowerCase())) return false;
  if (f.artist && !(album.artist || '').toLowerCase().includes(f.artist.toLowerCase())) return false;
  if (f.yearFrom && (album.year || 0) < f.yearFrom) return false;
  if (f.yearTo && (album.year || 0) > f.yearTo) return false;
  return true;
}

function compareValues(a, b, dir) {
  const sign = dir === 'asc' ? 1 : -1;
  // Nulls last when descending, first when ascending — Postgres NULLS LAST/FIRST.
  const aNull = a === null || a === undefined || a === '';
  const bNull = b === null || b === undefined || b === '';
  if (aNull && bNull) return 0;
  if (aNull) return dir === 'asc' ? -1 : 1;
  if (bNull) return dir === 'asc' ? 1 : -1;
  if (typeof a === 'number' && typeof b === 'number') return (a - b) * sign;
  return String(a).toLowerCase().localeCompare(String(b).toLowerCase()) * sign;
}

function toQueryArgs(params = {}) {
  const n = (v) => {
    const num = Number(v);
    return Number.isFinite(num) && v !== '' && v !== null && v !== undefined ? num : 0;
  };
  return {
    search:     String(params.search ?? '').trim(),
    album_type: String(params.album_type ?? '').trim(),
    genre:      String(params.genre ?? '').trim(),
    artist:     String(params.artist ?? '').trim(),
    yearFrom:   n(params.year_from),
    yearTo:     n(params.year_to),
    minPop:     params.min_pop === undefined || params.min_pop === '' ? 0 : n(params.min_pop),
    maxPop:     params.max_pop === undefined || params.max_pop === '' ? 100 : n(params.max_pop),
  };
}

/**
 * Returns the server's pagination envelope so `useAlbums` needs no special
 * case beyond picking the data source.
 */
export async function queryAlbums(params = {}, page = 1, limit = 48) {
  const filters = toQueryArgs(params);
  const all = await readAll();

  const filtered = all.filter((a) => matchesFilters(a, filters));
  const { field, dir } = parseSort(params.sort, params.order);
  const sorted = [...filtered].sort((a, b) =>
    compareValues(sortValue(a, field), sortValue(b, field), dir) ||
    // Stable tiebreak so paging never repeats or skips a row.
    compareValues(a.id, b.id, 'asc'),
  );

  const offset = Math.max(0, (page - 1) * limit);
  return { items: sorted.slice(offset, offset + limit), total: sorted.length, page, limit };
}

// ---------------------------------------------------------------------------
// Aggregates — same payload as GET /api/v1/albums/stats
// ---------------------------------------------------------------------------

function topCounts(pairs, limit = 10) {
  const counts = new Map();
  for (const [key] of pairs) {
    if (!key) continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, limit);
}

export async function getStats() {
  const all = await readAll();
  const years = all.map((a) => a.year).filter((y) => y > 0);

  const byYear = new Map();
  for (const y of years) byYear.set(y, (byYear.get(y) ?? 0) + 1);

  return {
    totalAlbums:  all.length,
    totalArtists: new Set(all.map((a) => a.artist).filter(Boolean)).size,
    totalGenres:  new Set(all.flatMap((a) => a.genres ?? []).filter(Boolean)).size,
    newestYear:   years.length ? Math.max(...years) : 0,
    oldestYear:   years.length ? Math.min(...years) : 0,
    topGenres:    topCounts(all.flatMap((a) => (a.genres ?? []).map((g) => [g]))),
    topArtists:   topCounts(all.flatMap((a) => (a.artists ?? []).map((ar) => [ar.name]))),
    albumsByYear: [...byYear.entries()]
      .map(([year, count]) => ({ year, count }))
      .sort((a, b) => a.year - b.year),
  };
}

/** Artist rows for the filter datalist — `{id,name}`, like GET /api/v1/artists. */
export async function getArtistNames() {
  const all = await readAll();
  const names = new Set();
  for (const album of all) {
    for (const artist of album.artists ?? []) if (artist.name) names.add(artist.name);
  }
  return [...names].sort((a, b) => a.localeCompare(b)).map((name) => ({ id: name, name }));
}

// ---------------------------------------------------------------------------
// CSV import (flat contract columns, tolerant headers)
// ---------------------------------------------------------------------------

const HEADER_ALIASES = {
  id: ['id', 'spotify_id', 'album_id'],
  title: ['title', 'album_title', 'album', 'name', 'album_name'],
  artist: ['artist', 'artists', 'artist_name'],
  year: ['year', 'release_year'],
  genre: ['genre', 'genres'],
  image_url: ['image_url', 'image', 'cover', 'cover_url', 'artwork_url'],
  added_at: ['added_at', 'date_added', 'added'],
};

/** RFC4180-ish split: honours quoted fields containing commas/quotes. */
function parseCsvLine(line) {
  const out = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; }
        else inQuotes = false;
      } else cur += ch;
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ',') {
      out.push(cur); cur = '';
    } else cur += ch;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

/**
 * Import contract CSV text into the local library, returning the same counters
 * the other frontends' import paths report so the toast reads the same.
 *
 * Bad rows are counted as `skipped` and reported per row exactly the way the
 * server's POST /api/v1/import/csv reports them — `Line N: skipped — missing
 * id/title/artist`, capped at 20 like `routers/import_csv.py` — so the same
 * file produces the same report through either path.
 */
const MAX_ERRORS = 20;

export async function importCsvText(csvText) {
  const result = { imported: 0, existing: 0, skipped: 0, errors: [] };
  const lines = String(csvText ?? '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .filter((l) => l.trim().length > 0);

  if (lines.length === 0) {
    result.errors.push('CSV file is empty');
    return result;
  }

  const header = parseCsvLine(lines[0]).map((h) => h.toLowerCase().replace(/\s+/g, '_'));
  const index = {};
  for (const [field, aliases] of Object.entries(HEADER_ALIASES)) {
    const at = header.findIndex((h) => aliases.includes(h));
    if (at >= 0 && index[field] === undefined) index[field] = at;
  }

  const missing = ['id', 'title', 'artist'].filter((f) => index[f] === undefined);
  if (missing.length > 0) {
    result.errors.push(`Missing required column(s): ${missing.join(', ')}`);
    return result;
  }

  const existingIds = await getExistingAlbumIds();
  const toWrite = [];

  for (let i = 1; i < lines.length; i++) {
    const cells = parseCsvLine(lines[i]);
    const cell = (field) => {
      const at = index[field];
      return at === undefined ? '' : String(cells[at] ?? '').trim();
    };

    const id = cell('id');
    const title = cell('title');
    const artist = cell('artist');
    if (!id || !title || !artist) {
      result.skipped++;
      // Physical line number (header is line 1), same as the server's report.
      if (result.errors.length < MAX_ERRORS) {
        result.errors.push(`Line ${i + 1}: skipped — missing id/title/artist`);
      }
      continue;
    }
    if (existingIds.has(id)) {
      result.existing++;
      continue;
    }

    toWrite.push(
      normalizeAlbum({
        id,
        title,
        artist,
        year: cell('year'),
        genre: cell('genre'),
        image_url: cell('image_url'),
        added_at: cell('added_at') || new Date().toISOString().slice(0, 10),
      }),
    );
    existingIds.add(id);
  }

  await upsertAlbums(toWrite);
  result.imported = toWrite.length;
  return result;
}

// ---------------------------------------------------------------------------
// CSV export — byte-compatible with GET /api/v1/albums/export
// ---------------------------------------------------------------------------

function csvField(value) {
  const s = value === null || value === undefined ? '' : String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Python's csv.writer joins rows with \r\n and quotes minimally. */
export function exportCsvBlob(albums) {
  const rows = [...albums].sort((a, b) =>
    String(a.name ?? '').toLowerCase().localeCompare(String(b.name ?? '').toLowerCase()),
  );

  const lines = [CSV_COLUMNS.join(',')];
  for (const a of rows) {
    const artists = [...new Set((a.artists ?? []).map((ar) => ar.name).filter(Boolean))].sort();
    lines.push(
      [
        csvField(a.spotify_id || a.id),
        csvField(a.name || a.title),
        csvField(artists.join('; ')),
        csvField(a.year ? String(a.year) : ''),
        csvField((a.genres ?? []).join('; ')),
        csvField(a.image_url),
        csvField(a.added_at ? String(a.added_at).slice(0, 10) : ''),
      ].join(','),
    );
  }

  return new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv' });
}

/** Export the whole local library. */
export async function exportLibraryCsv() {
  return exportCsvBlob(await readAll());
}
