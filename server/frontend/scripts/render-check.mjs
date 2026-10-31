/**
 * Render checks for the python frontend, run under Node.
 *
 * `vite build --ssr` compiles the real App and the data-source modal, then this
 * script renders them with react-dom/server and asserts on the markup. That
 * catches the class of bug a plain `vite build` cannot: props threaded to the
 * wrong component, mode branches that never fire, server-only controls leaking
 * into local mode.
 *
 * No browser and no jsdom: react-dom/server needs no DOM, and everything the app
 * touches on the way (localStorage, IndexedDB, fetch) is stubbed here first.
 *
 * Run via: npm run verify:local
 */
import { build } from 'vite'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')

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
// Stubs — installed before the bundle is imported
// ---------------------------------------------------------------------------
const mem = new Map()
globalThis.localStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
}

// Any network call during render is a bug: rendering must be side-effect free,
// and local mode must never reach for a server at all.
const fetches = []
globalThis.fetch = async (url, options = {}) => {
  fetches.push(`${options.method || 'GET'} ${url}`)
  throw new Error(`render check: unexpected fetch to ${url}`)
}

// ---------------------------------------------------------------------------
// Build the SSR bundle
// ---------------------------------------------------------------------------
console.log('building ssr bundle...')
await build({
  root,
  build: {
    ssr: 'scripts/render-entry.jsx',
    outDir: '.tmp-render',
    emptyOutDir: true,
    minify: false,
    write: true,
  },
  logLevel: 'error',
})

const entryPath = resolve(root, '.tmp-render/render-entry.js')
const { renderApp, renderModal, renderSyncPanel, renderSettings } = await import(pathToFileURL(entryPath).href)

// ---------------------------------------------------------------------------
// Local mode
// ---------------------------------------------------------------------------
localStorage.setItem('reSpotIt_data_source', JSON.stringify({ mode: 'local', serverUrl: '' }))

let localHtml = ''
try {
  localHtml = renderApp()
  check('local mode renders the app without throwing', localHtml.length > 0, `${localHtml.length} chars`)
} catch (e) {
  check('local mode renders the app without throwing', false, e?.message)
}

check('local mode shows the "This device" badge',
  localHtml.includes('This device'))

check('local mode hides the server-only header actions',
  !localHtml.includes('↓ Sync') && !localHtml.includes('Covers') &&
  !localHtml.includes('DB') && !localHtml.includes('☰ Playlists') &&
  !localHtml.includes('⌦ Clean'))

check('local mode keeps the browsing surfaces',
  localHtml.includes('Filters') && localHtml.includes('Search album'))

check('local mode renders the tab IA (no server-side Playlists tab)',
  localHtml.includes('bottom-tabs') &&
  localHtml.includes('>Library</button>') &&
  localHtml.includes('>Stats</button>') &&
  localHtml.includes('>Settings</button>') &&
  !localHtml.includes('>Playlists</button>'))

check('local mode hides playlists and the queue',
  !localHtml.includes('Add to Queue') && !localHtml.includes('Create Playlist'))

check('local mode does not touch the network while rendering',
  fetches.length === 0, fetches.join(', '))

// ---------------------------------------------------------------------------
// Remote mode
// ---------------------------------------------------------------------------
localStorage.removeItem('reSpotIt_data_source')
fetches.length = 0

let remoteHtml = ''
try {
  remoteHtml = renderApp()
  check('remote mode renders the app without throwing', remoteHtml.length > 0, `${remoteHtml.length} chars`)
} catch (e) {
  check('remote mode renders the app without throwing', false, e?.message)
}

// The auth check runs in an effect, so the first paint is the loading splash.
check('remote mode starts on the loading splash (auth not yet known)',
  remoteHtml.includes('reSpotIt') && !remoteHtml.includes('This device'))

check('remote mode does not touch the network while rendering',
  fetches.length === 0, fetches.join(', '))

// ---------------------------------------------------------------------------
// Data-source modal
// ---------------------------------------------------------------------------
const noop = () => {}
const localDs = {
  mode: 'local', serverUrl: '', isLocal: true,
  testing: false, testResult: null,
  setMode: noop, setServerUrl: noop, testConnection: noop, notifyLibraryChanged: noop,
}

const modalLocal = renderModal(localDs)
check('modal (local) offers import, export and clear',
  modalLocal.includes('Import CSV') && modalLocal.includes('Export CSV') &&
  modalLocal.includes('Clear library'))
check('modal (local) states the frozen column set',
  modalLocal.includes('id,title,artist,year,genre,image_url,added_at'))
check('modal (local) says which Spotify features are unavailable',
  modalLocal.includes('Spotify sync, covers, playlists and the queue'))

const remoteDs = { ...localDs, mode: 'remote', isLocal: false, serverUrl: 'http://127.0.0.1:5000' }
const modalRemote = renderModal(remoteDs)
check('modal (remote) shows the server URL and a test button',
  modalRemote.includes('http://127.0.0.1:5000') && modalRemote.includes('Test'))
check('modal (remote) hides the local library actions',
  !modalRemote.includes('Clear library'))

// ---------------------------------------------------------------------------
// Settings tab (V-pass IA): Backup + Server sections
// ---------------------------------------------------------------------------
const settingsLocal = renderSettings(localDs)
check('settings (local): Backup section with export',
  settingsLocal.includes('Backup') && settingsLocal.includes('Export CSV'))
check('settings (local): Server section carries import, export and clear',
  settingsLocal.includes('Server') && settingsLocal.includes('Import CSV') &&
  settingsLocal.includes('Clear library'))
check('settings (local): frozen column set stated',
  settingsLocal.includes('id,title,artist,year,genre,image_url,added_at'))
check('settings (local): no server-jobs strip in local mode',
  !settingsLocal.includes('Server jobs'))

const settingsRemote = renderSettings(remoteDs, { autoExport: true })
check('settings (remote): server URL + test + auto-export + jobs',
  settingsRemote.includes('http://127.0.0.1:5000') && settingsRemote.includes('Test') &&
  settingsRemote.includes('Auto-export after sync') && settingsRemote.includes('Server jobs'))
check('settings (remote): local-only actions hidden',
  !settingsRemote.includes('Clear library') && !settingsRemote.includes('Import CSV'))

// ---------------------------------------------------------------------------
// Sync panel driven by a canonical job envelope
//
// The panel is the one component whose props come straight from the envelope
// mapping, so it is rendered here with real job states: a running job mid-stage,
// a finished one, a failed one, and the two quick rows. This is what catches a
// mapping that unit-checks fine but renders wrong (`steps[2].data.inserted`
// reading undefined, a status label that never fires).
// ---------------------------------------------------------------------------
const stages = await import('../src/pipelineStages.js')

const envelope = (patch) => ({
  job_id: 'J1', type: 'sync', status: 'running', stage: 'albums',
  fetched: 0, total: 0, result: null, error: null, ...patch,
})

/** The pipeline prop exactly as App builds it from one job. */
const pipelineFor = (job) => ({
  steps:      stages.stepsFromJob(job),
  isRunning:  job.status === 'running' || job.status === 'pending',
  isDone:     job.status === 'done',
  hasError:   job.status === 'error',
  isCancelled: job.status === 'cancelled',
  hasActivity: true,
  activeIdx:  stages.activeIndex(job),
  overallPct: stages.overallPct(job),
  start: noop, stop: noop, reset: noop,
})

const blankPipeline = { ...pipelineFor(envelope({})), hasActivity: false }

const countOf = (hay, needle) => hay.split(needle).length - 1

// React's SSR text-separator comments land between an interpolated value and the
// literal next to it ("7<!-- --> inserted"), so content assertions strip them.
const text = (html) => html.replace(/<!-- -->/g, '')

const midSyncHtml = renderSyncPanel({
  pipeline: pipelineFor(envelope({ stage: 'images', fetched: 5, total: 10 })),
})
check('panel: all three stage labels render',
  text(midSyncHtml).includes('Fetch Library') && text(midSyncHtml).includes('Download Covers') &&
  text(midSyncHtml).includes('Load to Database'))
check('panel: header shows the running job at 50%',
  text(midSyncHtml).includes('Syncing') && text(midSyncHtml).includes('50%'))
check('panel: active stage counts come from the envelope',
  text(midSyncHtml).includes('5/10'))
check('panel: one done row, one running row, one idle row',
  countOf(midSyncHtml, 'step-dot-done') === 1 &&
  countOf(midSyncHtml, 'step-dot-running') === 1 &&
  countOf(midSyncHtml, 'step-dot-idle') === 1,
  `done=${countOf(midSyncHtml, 'step-dot-done')} running=${countOf(midSyncHtml, 'step-dot-running')} idle=${countOf(midSyncHtml, 'step-dot-idle')}`)

const doneSyncHtml = renderSyncPanel({
  pipeline: pipelineFor(envelope({
    status: 'done', stage: 'saving', fetched: 6, total: 6,
    result: { imported: 7, existing: 3, skipped: 1, errors: [] },
  })),
})
check('panel: finished sync says so and offers Re-sync',
  text(doneSyncHtml).includes('Sync complete') && text(doneSyncHtml).includes('Re-sync'))
check('panel: summary reads result.imported/existing as inserted/updated',
  text(doneSyncHtml).includes('7 inserted') && text(doneSyncHtml).includes('3 updated'))

const failedHtml = renderSyncPanel({
  pipeline: pipelineFor(envelope({
    status: 'error', stage: 'images', fetched: 2, total: 8, error: 'Spotify said no.',
  })),
})
check('panel: failure shows the envelope error on the failing stage',
  text(failedHtml).includes('Sync failed') && text(failedHtml).includes('Spotify said no.'))

const coversRow = {
  job: { job_id: 'Q1', status: 'running', stage: 'images', fetched: 3, total: 12, pct: 25 },
  isRunning: true, cancel: noop, dismiss: noop,
}
const quickHtml = renderSyncPanel({ pipeline: blankPipeline, imagesJob: coversRow })
check('quick row: renders from the canonical envelope (counts + stage)',
  text(quickHtml).includes('Refresh Covers') && text(quickHtml).includes('3/12') &&
  text(quickHtml).includes('images'))
check('quick row: no pipeline section when only a quick job ran',
  !text(quickHtml).includes('Fetch Library'))

const failedQuick = {
  job: { job_id: 'Q2', status: 'error', message: 'No CSV to read.' },
  isRunning: false, cancel: noop, dismiss: noop,
}
const quickErrHtml = renderSyncPanel({ pipeline: blankPipeline, loadJob: failedQuick })
check('quick row: shows why it stopped',
  text(quickErrHtml).includes('Reload Database') && text(quickErrHtml).includes('No CSV to read.'))

// ── Server-side "last sync" line ─────────────────────────────────────────────
// A brand-new browser has no saved job, so the panel's only content is what
// GET /api/v1/sync/history says about the server's most recent run.
const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()
const lastSync = {
  job_id: 'H1', type: 'sync', status: 'done', stage: 'saving',
  fetched: 6, total: 6,
  result: { imported: 12, existing: 3, skipped: 0, errors: [] },
  created_at: twoHoursAgo, finished_at: twoHoursAgo,
}

const historyHtml = renderSyncPanel({
  pipeline: { ...blankPipeline, lastSync },
})
check('history: an idle browser shows the server\'s last sync',
  text(historyHtml).includes('Last sync') && text(historyHtml).includes('12 inserted'))
check('history: the line carries the age and a Re-sync button',
  text(historyHtml).includes('2 hours ago') && text(historyHtml).includes('Re-sync'))
check('history: no stage rows without a job of this browser\'s own',
  !text(historyHtml).includes('Fetch Library'))

const historyFailed = renderSyncPanel({
  pipeline: { ...blankPipeline, lastSync: { ...lastSync, status: 'error', error: 'Spotify said no.' } },
})
check('history: a failed last run says why, not fake counts',
  text(historyFailed).includes('Spotify said no.') && !text(historyFailed).includes('inserted'))

// The live job always wins: history must not add a second, stale line under it.
const doneWithHistory = renderSyncPanel({
  pipeline: { ...pipelineFor(envelope({
    status: 'done', stage: 'saving', fetched: 6, total: 6,
    result: { imported: 1, existing: 0, skipped: 0, errors: [] },
  })), lastSync },
})
check('history: hidden while a job of this browser is displayed',
  !text(doneWithHistory).includes('Last sync'))

console.log('')
if (failures > 0) {
  console.log(`RENDER FAILED: ${failures} of ${checks} checks`)
  process.exit(1)
}
console.log(`RENDER OK - ${checks} checks (local + remote chrome, data-source modal, sync panel)`)
process.exit(0)
