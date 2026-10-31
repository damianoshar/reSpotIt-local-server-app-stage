/**
 * Pipeline-mapping checks for the python frontend.
 *
 * The sync panel's rows are derived from ONE canonical job envelope
 * (`src/pipelineStages.js`). Those functions are pure, so they are asserted here
 * directly under Node — the imports are real source files, no browser and no
 * build step (`"type": "module"`).
 *
 * The last block is a source-level guard: the client must not drift back to the
 * per-stage routes that the contract does not have.
 *
 * Run with: npm run verify:local (chained), or node scripts/verify-pipeline.mjs
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  STEP_DEFS, TERMINAL, isTerminal, stageRow, jobPct,
  blankSteps, stepsFromJob, overallPct, activeIndex,
  pickLastSync, recentSyncs, relativeTime,
} from '../src/pipelineStages.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')

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
// Helpers to inspect a row set
// ---------------------------------------------------------------------------
const statuses = (job) => stepsFromJob(job).map(s => s.status)

/** A running envelope with only the frozen keys set. */
const job = (patch) => ({
  job_id: 'J1', type: 'sync', status: 'running', stage: 'albums',
  fetched: 0, total: 0, result: null, error: null, ...patch,
})

// ---------------------------------------------------------------------------
// Idle + stage mapping
// ---------------------------------------------------------------------------
check('no job -> three idle rows', statuses(null).join(',') === 'idle,idle,idle')
check('blank steps carry the three labels',
  blankSteps().map(s => s.label).join('|') === 'Fetch Library|Download Covers|Load to Database')
check('blank steps have no data', blankSteps().every(s => s.data === null))

check('stage albums -> row 0', stageRow('albums') === 0)
check('stage images -> row 1', stageRow('images') === 1)
check('stage saving -> row 2', stageRow('saving') === 2)
check('stage mapping ignores case and padding', stageRow('  Saving ') === 2)
check('unknown stage falls back to row 0', stageRow('something-new') === 0)
check('missing stage falls back to row 0', stageRow(null) === 0)

// ---------------------------------------------------------------------------
// Percentage (the envelope has none of its own)
// ---------------------------------------------------------------------------
check('pct 0/0 is 0', jobPct({ fetched: 0, total: 0 }) === 0)
check('pct of 5/10 is 50', jobPct({ fetched: 5, total: 10 }) === 50)
check('pct of 0/10 is 0', jobPct({ fetched: 0, total: 10 }) === 0)
check('pct clamps to 100 when fetched overshoots', jobPct({ fetched: 25, total: 10 }) === 100)
check('pct is neutral for a null job', jobPct(null) === 0)

check('terminal statuses', TERMINAL.join(',') === 'done,error,cancelled')
check('pending is not terminal', !isTerminal('pending') && !isTerminal('running'))

// ---------------------------------------------------------------------------
// A running job, stage by stage
// ---------------------------------------------------------------------------
const fetching = job({ stage: 'albums', fetched: 3, total: 10 })
check('fetch stage: row 0 running, rest idle',
  statuses(fetching).join(',') === 'running,idle,idle')
check('fetch stage: active index 0', activeIndex(fetching) === 0)
check('fetch stage: row 0 carries fetched/total/pct',
  stepsFromJob(fetching)[0].data.fetched === 3 &&
  stepsFromJob(fetching)[0].data.total === 10 &&
  stepsFromJob(fetching)[0].data.pct === 30)
check('fetch stage: overall progress is one third of the row',
  overallPct(fetching) === 10, `overall=${overallPct(fetching)}`)

const covers = job({ stage: 'images', fetched: 5, total: 10 })
check('images stage: row 0 done, row 1 running, row 2 idle',
  statuses(covers).join(',') === 'done,running,idle')
check('images stage: active index 1', activeIndex(covers) === 1)
check('images stage: row 0 is a full bar', stepsFromJob(covers)[0].data.pct === 100)
check('images stage: overall counts the finished stage',
  overallPct(covers) === 50, `overall=${overallPct(covers)}`)

const saving = job({ stage: 'saving', fetched: 1, total: 4 })
check('saving stage: two done rows, last running',
  statuses(saving).join(',') === 'done,done,running')
check('saving stage: active index 2', activeIndex(saving) === 2)

// ---------------------------------------------------------------------------
// Terminal states
// ---------------------------------------------------------------------------
const done = job({
  status: 'done', stage: 'saving', fetched: 4, total: 4,
  result: { imported: 5, existing: 2, skipped: 1, errors: [] },
})
check('done: every row done', statuses(done).join(',') === 'done,done,done')
check('done: overall is 100', overallPct(done) === 100)
check('done: no active row', activeIndex(done) === -1)
check('done: summary lands on the load row',
  stepsFromJob(done)[2].data.inserted === 5 &&
  stepsFromJob(done)[2].data.updated === 2 &&
  stepsFromJob(done)[2].data.skipped === 1)
check('done: load row bar is full', stepsFromJob(done)[2].data.pct === 100)

const failed = job({
  status: 'error', stage: 'images', fetched: 5, total: 10, error: 'Spotify said no.',
})
check('error: the failing stage is the error row',
  statuses(failed).join(',') === 'done,error,idle')
check('error: message comes from the envelope',
  stepsFromJob(failed)[1].data.message === 'Spotify said no.')
check('error: earlier stages stay done', stepsFromJob(failed)[0].status === 'done')
check('error: overall keeps the progress so far',
  overallPct(failed) === 50, `overall=${overallPct(failed)}`)
check('error: no row is highlighted as active', activeIndex(failed) === -1)

const cancelled = job({ status: 'cancelled', stage: 'saving', fetched: 1, total: 4 })
check('cancelled: the stage it stopped in is the cancelled row',
  statuses(cancelled).join(',') === 'done,done,cancelled')
check('cancelled: client-side wording, no server text needed',
  stepsFromJob(cancelled)[2].data.message === 'Cancelled.')

const pending = job({ status: 'pending', stage: 'albums' })
check('pending: shown as running (the worker is about to start)',
  statuses(pending)[0] === 'running' && activeIndex(pending) === 0)

// ---------------------------------------------------------------------------
// Optional envelope extra
// ---------------------------------------------------------------------------
const withAlbum = job({ stage: 'albums', fetched: 1, total: 2, current_album: 'Kind of Blue' })
check('optional current_album is passed through',
  stepsFromJob(withAlbum)[0].data.current_album === 'Kind of Blue')
check('a job without current_album does not invent one',
  !('current_album' in stepsFromJob(fetching)[0].data))

// ---------------------------------------------------------------------------
// "Last sync" from the server's job history (GET /api/v1/sync/history)
// ---------------------------------------------------------------------------
const at = Date.parse('2026-10-17T12:00:00Z')
const recent = {
  job_id: 'H1', type: 'sync', status: 'done', stage: 'saving',
  fetched: 6, total: 6, result: { imported: 7, existing: 3, skipped: 0, errors: [] },
  created_at: '2026-10-17T11:58:00Z', finished_at: '2026-10-17T12:00:00Z',
}

check('history: the newest finished sync is picked', pickLastSync([recent])?.job_id === 'H1')
check('history: a finished queue job is not a "last sync"',
  pickLastSync([{ job_id: 'Q1', type: 'queue', status: 'done' }, recent])?.job_id === 'H1')
check('history: a still-running sync is not a finished run',
  pickLastSync([job({ status: 'running' }), recent])?.job_id === 'H1')
check('history: no finished sync -> null', pickLastSync([job({ status: 'running' })]) === null)
check('history: empty or absent payloads -> null',
  pickLastSync([]) === null && pickLastSync(undefined) === null)
check('history: never invents a run from a malformed item',
  pickLastSync([null, 'nope', {}]) === null)

// The panel now shows up to two runs *behind* the newest (C5); same filter,
// list instead of head — and `pickLastSync` must stay the head of it.
const older = { ...recent, job_id: 'H2', finished_at: '2026-10-17T10:00:00Z',
                created_at: '2026-10-17T09:58:00Z' }
const runsFrom = recentSyncs([recent, older, { job_id: 'Q2', type: 'queue', status: 'done' }], 3)
check('history: recentSyncs keeps finished syncs in order',
  runsFrom.map(r => r.job_id).join(',') === 'H1,H2', runsFrom.map(r => r.job_id).join(','))
check('history: recentSyncs respects the cap',
  recentSyncs([recent, older], 1).length === 1 &&
  recentSyncs([recent, older], 0).length === 0)
check('history: recentSyncs filters everything pickLastSync rejects',
  recentSyncs(undefined).length === 0 && recentSyncs([null, 'x']).length === 0)
check('history: pickLastSync is the head of recentSyncs',
  pickLastSync([older, recent])?.job_id === recentSyncs([older, recent])[0]?.job_id)

check('age: under a minute is "just now"', relativeTime('2026-10-17T11:59:30Z', at) === 'just now')
check('age: minutes', relativeTime('2026-10-17T11:55:00Z', at) === '5 min ago')
check('age: one hour is singular', relativeTime('2026-10-17T10:59:00Z', at) === '1 hour ago')
check('age: hours', relativeTime('2026-10-17T10:00:00Z', at) === '2 hours ago')
check('age: days', relativeTime('2026-10-14T12:00:00Z', at) === '3 days ago')
check('age: a month-old run falls back to a date, not a day count',
  relativeTime('2026-01-01T00:00:00Z', at) !== '' &&
  !relativeTime('2026-01-01T00:00:00Z', at).includes('ago'))
check('age: an unparseable timestamp says nothing',
  relativeTime(null, at) === '' && relativeTime('later', at) === '')

// ---------------------------------------------------------------------------
// Source-level guards: one start call, one job API
// ---------------------------------------------------------------------------
const read = (p) => readFileSync(p, 'utf8')

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.jsx?$/.test(name)) out.push(p)
  }
  return out
}

const allSrc = walk(SRC).map(p => ({ path: p, text: read(p) }))
const client  = allSrc.find(f => f.path.endsWith(join('api', 'client.js')))

check('client starts the sync through /api/v1/sync/albums',
  client.text.includes('/api/v1/sync/albums'))
check('client polls and cancels through the generic job routes',
  client.text.includes('/api/v1/jobs/${id}') && client.text.includes('/api/v1/jobs/${id}/cancel'))
check('client keeps the images extension at its frozen path',
  client.text.includes('/api/v1/images/sync'))

const removedRoutes = [
  '/api/v1/sync/start', '/api/v1/sync/cancel', '/api/v1/sync/jobs',
  '/api/v1/images/start', '/api/v1/images/cancel', '/api/v1/images/jobs',
  '/api/v1/load/cancel', '/api/v1/load/jobs',
]
for (const route of removedRoutes) {
  const hit = allSrc.find(f => f.text.includes(route))
  check(`no source references the removed route ${route}`, !hit, hit ? hit.path : '')
}

const pipeline = allSrc.find(f => f.path.endsWith(join('hooks', 'usePipeline.js')))
check('the pipeline uses exactly one start call',
  pipeline.text.includes('startFullSync') && !pipeline.text.includes('startImages') &&
  !pipeline.text.includes('startLoad'))
check('the pipeline owns no per-stage job ids',
  !pipeline.text.includes('STEP_DEFS[') && !pipeline.text.includes('STARTERS'))

const panel = allSrc.find(f => f.path.endsWith(join('components', 'SyncPanel.jsx')))
check('client reads the sync history endpoint',
  client.text.includes('/api/v1/sync/history'))
check('the pipeline asks the server for the last run, defensively',
  pipeline.text.includes('api.getSyncHistory') && pipeline.text.includes('recentSyncs') &&
  pipeline.text.includes('.catch(() =>'))
check('the panel renders the history lines (newest + earlier runs)',
  panel.text.includes('historySummary') && panel.text.includes('Last sync') &&
  panel.text.includes('relativeTime') && panel.text.includes('recentRuns'))

const app = allSrc.find(f => f.path.endsWith('App.jsx'))
check('local mode drops the server-side last-sync line',
  app.text.includes('lastSync: null'))

console.log('')
if (failures > 0) {
  console.log(`PIPELINE-MAPPING FAILED: ${failures} of ${checks} checks`)
  process.exit(1)
}
console.log(`PIPELINE-MAPPING OK - ${checks} checks (stage mapping, progress, terminal states, history, route guards)`)
process.exit(0)
