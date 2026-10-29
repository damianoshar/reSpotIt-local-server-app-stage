/**
 * Local-mode checks for the python frontend.
 *
 * Runs the real `src/services/localDatabase.js` under Node against
 * `fake-indexeddb` — no browser automation is available in this environment.
 * The files are ESM (`"type": "module"`), so they import directly with no
 * build/compile step.
 *
 * Run with: npm run verify:local
 */
import 'fake-indexeddb/auto'

let failures = 0
let checks = 0

function check(name, ok, detail = '') {
  checks++
  const suffix = detail ? ` -- ${detail}` : ''
  if (ok) {
    console.log(`PASS  ${name}${suffix}`)
  } else {
    console.log(`FAIL  ${name}${suffix}`)
    failures++
  }
}

// ---------------------------------------------------------------------------
// localStorage stub, installed before config/server.js is imported
// ---------------------------------------------------------------------------
const mem = new Map()
globalThis.localStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
}

const db = await import('../src/services/localDatabase.js')
const { normalizeServerUrl, loadDataSourceSettings, saveDataSourceSettings,
        DEFAULT_DATA_SOURCE, DATA_SOURCE_PREFS_KEY } = await import('../src/config/server.js')

// ---------------------------------------------------------------------------
// Fixtures — one server item (both halves) and one flat CSV-style item per year
// ---------------------------------------------------------------------------
const serverItem = {
  id: 'SP1', spotify_id: 'SP1',
  title: 'Alpha', name: 'Alpha',
  artist: 'The Beta Band', artists: [{ name: 'The Beta Band' }],
  year: 2001, release_date: '2001-05-01',
  genre: 'jazz', genres: ['jazz'],
  image_url: 'http://img/1.jpg', added_at: '2026-01-01',
  album_type: 'album', popularity: 60, total_tracks: 10,
  label: 'Alpha Rec', spotify_url: 'https://open.spotify.com/album/SP1',
}
const flatItems = [
  { id: 'SP2', title: 'Bravo', artist: 'Zeta', year: 1999, genre: 'rock',
    image_url: 'http://img/2.jpg', added_at: '2026-01-02' },
  { id: 'SP3', title: 'Charlie', artist: 'The Beta Band', year: 2005, genre: 'jazz; folk',
    image_url: 'http://img/3.jpg', added_at: '2026-01-03' },
]

// ---------------------------------------------------------------------------
// normalizeAlbum
// ---------------------------------------------------------------------------
const n1 = db.normalizeAlbum(serverItem)
check('normalizeAlbum keeps the flat twin',
  n1.id === 'SP1' && n1.title === 'Alpha' && n1.artist === 'The Beta Band' &&
  n1.year === 2001 && n1.genre === 'jazz' && n1.added_at === '2026-01-01',
  `id=${n1.id} title=${n1.title} year=${n1.year}`)
check('normalizeAlbum keeps the rich half the UI renders',
  n1.name === 'Alpha' && n1.artists[0]?.name === 'The Beta Band' && n1.genres[0] === 'jazz' &&
  n1.release_date === '2001-05-01' && n1.popularity === 60,
  `name=${n1.name} artists=${n1.artists.map(a => a.name).join('|')} pop=${n1.popularity}`)

const n2 = db.normalizeAlbum({ id: 'X', title: 'T', artist: 'A; B', year: '1980', genre: 'rock; pop' })
check('normalizeAlbum builds rich twins from a flat CSV row',
  n2.name === 'T' && n2.spotify_id === 'X' && n2.artists.length === 2 &&
  n2.artists[1].name === 'B' && n2.genres.length === 2 && n2.release_date === '1980-01-01',
  `artists=${n2.artists.map(a => a.name).join('|')} genres=${n2.genres.join('|')} release=${n2.release_date}`)

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------
await db.initDB()
check('library starts empty', (await db.countAlbums()) === 0)

// Replace-on-same-id, probed on a throwaway row so the shared fixtures below
// stay intact (a flat-only row would blank a rich row's rich half — writers
// pass complete items; see the note on normalizeAlbum).
await db.upsertAlbums([{ id: 'SP0', title: 'First', artist: 'Solo', year: 1990, genre: 'pop', added_at: '2025-12-31' }])
await db.upsertAlbums([{ id: 'SP0', title: 'Second', artist: 'Solo', year: 1990, genre: 'pop', added_at: '2025-12-31' }])
check('upsertAlbums replaces on the same id',
  (await db.countAlbums()) === 1 && (await db.queryAlbums({ search: 'second' })).total === 1,
  `count=${await db.countAlbums()}`)
await db.clearLibrary()

await db.upsertAlbums([serverItem, ...flatItems])
check('upsertAlbums stores all rows', (await db.countAlbums()) === 3)

// ---------------------------------------------------------------------------
// Query envelope + filters (server semantics)
// ---------------------------------------------------------------------------
const page1 = await db.queryAlbums({ sort: 'added_at_desc' }, 1, 48)
check('query returns the server envelope',
  Array.isArray(page1.items) && page1.total === 3 && page1.page === 1 && page1.limit === 48,
  `total=${page1.total} page=${page1.page} limit=${page1.limit}`)

const bySearch = await db.queryAlbums({ search: 'brav' })
check('search matches album name only', bySearch.total === 1 && bySearch.items[0].id === 'SP2',
  `total=${bySearch.total}`)
const searchNoArtist = await db.queryAlbums({ search: 'zeta' })
check('search does not match artist (server semantics)', searchNoArtist.total === 0,
  `total=${searchNoArtist.total}`)

check('genre is a substring match on the joined list',
  (await db.queryAlbums({ genre: 'folk' })).total === 1)
check('artist is a substring match', (await db.queryAlbums({ artist: 'beta' })).total === 2)
check('album_type is an exact match',
  (await db.queryAlbums({ album_type: 'album' })).total === 1 &&
  (await db.queryAlbums({ album_type: 'single' })).total === 0)
check('year range is inclusive',
  (await db.queryAlbums({ year_from: 1999, year_to: 2001 })).total === 2)
check('min_pop > 0 drops rows with no popularity (SQL NULL semantics)',
  (await db.queryAlbums({ min_pop: 10 })).total === 1 &&
  (await db.queryAlbums({ min_pop: 0 })).total === 3)

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------
const nameAsc = await db.queryAlbums({ sort: 'name_asc' })
check('sort name_asc orders by title',
  nameAsc.items.map(a => a.name).join('|') === 'Alpha|Bravo|Charlie',
  nameAsc.items.map(a => a.name).join('|'))

const addedDesc = await db.queryAlbums({ sort: 'added_at_desc' })
check('sort added_at_desc is newest first',
  addedDesc.items.map(a => a.id).join('|') === 'SP3|SP2|SP1',
  addedDesc.items.map(a => a.id).join('|'))

const artistAsc = await db.queryAlbums({ sort: 'artist_asc' })
check('sort artist_asc ignores a leading "The "',
  artistAsc.items.map(a => a.artist).join('|') === 'The Beta Band|The Beta Band|Zeta',
  artistAsc.items.map(a => a.artist).join('|'))

const contractSort = await db.queryAlbums({ sort: 'title', order: 'desc' })
check('contract sort=title&order=desc is honoured',
  contractSort.items.map(a => a.name).join('|') === 'Charlie|Bravo|Alpha',
  contractSort.items.map(a => a.name).join('|'))

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------
const p1 = await db.queryAlbums({ sort: 'name_asc' }, 1, 2)
const p2 = await db.queryAlbums({ sort: 'name_asc' }, 2, 2)
const ids = [...p1.items, ...p2.items].map(a => a.id)
check('pagination slices without repeats or gaps',
  p1.items.length === 2 && p2.items.length === 1 && new Set(ids).size === 3 &&
  p1.total === 3 && p2.total === 3,
  `p1=${p1.items.length} p2=${p2.items.length} unique=${new Set(ids).size}`)

// ---------------------------------------------------------------------------
// Aggregates
// ---------------------------------------------------------------------------
const stats = await db.getStats()
check('stats has the backend keys',
  stats.totalAlbums === 3 && stats.totalArtists === 2 && stats.totalGenres === 3 &&
  stats.oldestYear === 1999 && stats.newestYear === 2005,
  `albums=${stats.totalAlbums} artists=${stats.totalArtists} genres=${stats.totalGenres} span=${stats.oldestYear}-${stats.newestYear}`)
check('stats breakdowns are shaped like the server payload',
  stats.topGenres.length === 3 && stats.topGenres[0].name === 'jazz' && stats.topGenres[0].count === 2 &&
  Array.isArray(stats.topArtists) && stats.topArtists[0].name === 'The Beta Band' &&
  stats.albumsByYear.map(y => y.year).join('|') === '1999|2001|2005',
  `topGenres=${stats.topGenres.map(g => `${g.name}:${g.count}`).join(',')} years=${stats.albumsByYear.map(y => y.year).join('|')}`)

const artists = await db.getArtistNames()
check('artist rows are {id,name} and sorted',
  artists.length === 2 && artists[0].name === 'The Beta Band' && artists[0].id === 'The Beta Band' &&
  artists[1].name === 'Zeta',
  artists.map(a => a.name).join('|'))

// ---------------------------------------------------------------------------
// CSV round trip
// ---------------------------------------------------------------------------
const csv = [
  'id,title,artist,year,genre,image_url,added_at',
  'SP4,Delta,"Quoted, Artist",2010,ambient,http://img/4.jpg,2026-01-04',
  'SP5,Echo,Solo,2011,,,2026-01-05',
  ',Skipped,NoId,2012,,,',
].join('\n')

const imported = await db.importCsvText(csv)
check('CSV import counts imported and skipped rows',
  imported.imported === 2 && imported.skipped === 1 && imported.existing === 0,
  `imported=${imported.imported} skipped=${imported.skipped} errors=${imported.errors.length}`)
check('CSV import names each skipped row the way the server does',
  imported.errors.length === 1 &&
  imported.errors[0] === 'Line 4: skipped — missing id/title/artist',
  imported.errors.join(' | ') || 'no per-row error reported')

const manyBad = Array.from({ length: 30 }, (_, n) => `,Title ${n},Artist ${n},2000,,,`).join('\n')
const capped = await db.importCsvText(`id,title,artist,year,genre,image_url,added_at\n${manyBad}`)
check('CSV import caps the per-row error list like the server (20)',
  capped.skipped === 30 && capped.errors.length === 20 &&
  capped.errors[0].startsWith('Line 2:'),
  `skipped=${capped.skipped} errors=${capped.errors.length} first=${capped.errors[0]}`)

const again = await db.importCsvText(csv)
check('re-import reports rows as existing',
  again.imported === 0 && again.existing === 2 && again.skipped === 1,
  `imported=${again.imported} existing=${again.existing} skipped=${again.skipped}`)

const badHeader = await db.importCsvText('name,year\nA,2000')
check('CSV import refuses a header without the required columns',
  // 'name' is an accepted alias for title, so only id and artist are missing.
  badHeader.imported === 0 && badHeader.errors.length === 1 &&
  badHeader.errors[0].includes('id') && badHeader.errors[0].includes('artist') &&
  !badHeader.errors[0].includes('title'),
  badHeader.errors[0] || 'no error reported')

const quoted = await db.queryAlbums({ search: 'delta' })
check('CSV import keeps a quoted comma inside a field',
  quoted.total === 1 && quoted.items[0].artist === 'Quoted, Artist',
  `artist=${quoted.items[0]?.artist}`)

const blob = await db.exportCsvBlob(await (async () => {
  const all = (await db.queryAlbums({}, 1, 1000)).items
  return all
})())
const text = await blob.text()
const lines = text.split('\r\n').filter((l) => l.length > 0)
check('export header is the frozen column set',
  lines[0] === 'id,title,artist,year,genre,image_url,added_at',
  lines[0])
check('export has one row per album, CRLF-terminated',
  lines.length === 5 + 1 && text.endsWith('\r\n'),
  `lines=${lines.length} crlf=${text.endsWith('\r\n')}`)
check('export joins the one artist and keeps the flat columns',
  lines.includes('SP1,Alpha,The Beta Band,2001,jazz,http://img/1.jpg,2026-01-01'),
  lines.find((l) => l.startsWith('SP1')) || 'row missing')
check('export quotes a field containing a comma',
  lines.some((l) => l.includes('"Quoted, Artist"')),
  lines.find((l) => l.startsWith('SP4')) || 'row missing')

// ---------------------------------------------------------------------------
// Clear
// ---------------------------------------------------------------------------
await db.clearLibrary()
check('clearLibrary empties the store', (await db.countAlbums()) === 0)

// ---------------------------------------------------------------------------
// Data-source preference
// ---------------------------------------------------------------------------
check('default data source is remote (server-backed app)',
  DEFAULT_DATA_SOURCE.mode === 'remote' && DEFAULT_DATA_SOURCE.serverUrl === '')
check('missing preference falls back to remote',
  loadDataSourceSettings().mode === 'remote')
saveDataSourceSettings({ mode: 'local', serverUrl: 'http://127.0.0.1:8000/' })
const saved = loadDataSourceSettings()
check('mode + URL round-trip, trailing slash trimmed',
  saved.mode === 'local' && saved.serverUrl === 'http://127.0.0.1:8000',
  `${saved.mode} ${saved.serverUrl}`)
mem.set(DATA_SOURCE_PREFS_KEY, '{not json')
check('corrupt preference does not strand the app in local mode',
  loadDataSourceSettings().mode === 'remote')
check('normalizeServerUrl trims and strips slashes',
  normalizeServerUrl('  http://host:5000///  ') === 'http://host:5000',
  normalizeServerUrl('  http://host:5000///  '))

console.log('')
if (failures > 0) {
  console.log(`LOCAL-MODE FAILED: ${failures} of ${checks} checks`)
  process.exit(1)
}
console.log(`LOCAL-MODE OK - ${checks} checks (IndexedDB library, query semantics, CSV, data source)`)
process.exit(0)
