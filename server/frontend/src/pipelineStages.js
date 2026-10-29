/**
 * pipelineStages — turns one canonical sync job into the panel's three rows.
 *
 * The backend runs fetch → images → load inside a SINGLE job (API-PARITY-PLAN
 * §1) and reports `stage` + `fetched`/`total` while it runs. There is no
 * per-stage job to poll, so this is where "the job is in stage `images`" becomes
 * "row 1 is running, row 0 is done".
 *
 * Pure functions, no React, so the panel and `scripts/verify-pipeline.mjs`
 * share one definition and the mapping can be asserted without a browser.
 *
 * It reads only the frozen envelope keys — job_id, type, status, stage,
 * fetched, total, result, error — so it works against any backend. A stage this
 * client does not know falls back to the first row instead of breaking the
 * panel: stage names are the backend's business (python says albums | images |
 * saving; others may use their own words).
 */

export const STEP_DEFS = [
  { name: 'sync',   label: 'Fetch Library'    },
  { name: 'images', label: 'Download Covers'  },
  { name: 'load',   label: 'Load to Database' },
]

/** Known stage names → row. Everything else lands on row 0. */
const STAGE_ROW = {
  albums: 0, fetching: 0, tracks: 0, library: 0,
  images: 1, covers: 1, artwork: 1,
  saving: 2, load: 2, loading: 2, genres: 2, queueing: 2,
}

export const TERMINAL = ['done', 'error', 'cancelled']

export function isTerminal(status) {
  return TERMINAL.includes(status)
}

/** Row index a stage belongs to (unknown or missing stage → the first row). */
export function stageRow(stage) {
  return STAGE_ROW[String(stage ?? '').trim().toLowerCase()] ?? 0
}

/**
 * The envelope has no percentage — every consumer derives it here, so the two
 * job hooks and the panel can never disagree about what "50%" means.
 */
export function jobPct(job) {
  const total = job?.total ?? 0
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round(((job?.fetched ?? 0) / total) * 100)))
}

export function blankSteps() {
  return STEP_DEFS.map(def => ({ ...def, status: 'idle', data: null }))
}

function stageData(job, status) {
  const data = {
    fetched: job.fetched ?? 0,
    done:    job.fetched ?? 0,   // the panel's count for the images/load rows
    total:   job.total   ?? 0,
    pct:     status === 'done' ? 100 : jobPct(job),
  }
  if (job.error) data.message = job.error
  else if (status === 'cancelled') data.message = 'Cancelled.'

  // Optional extra some backends add (python does, at the bottom of its
  // envelope): the album being worked on right now. Read defensively — the
  // frozen envelope has no such key.
  if (job.current_album) data.current_album = job.current_album

  // Terminal summary. The envelope words these imported/existing/skipped; the
  // panel words them inserted/updated, which is what its summary line shows.
  if (job.result) {
    data.inserted = job.result.imported
    data.updated  = job.result.existing
    data.skipped  = job.result.skipped
  }
  return data
}

/** The three rows for a job envelope. `null` → three idle rows. */
export function stepsFromJob(job) {
  if (!job) return blankSteps()

  const active = stageRow(job.stage)
  const last   = STEP_DEFS.length - 1

  return STEP_DEFS.map((def, i) => {
    if (job.status === 'done') {
      // All rows done; the final one carries the summary.
      return i === last
        ? { ...def, status: 'done', data: stageData(job, 'done') }
        : { ...def, status: 'done', data: { pct: 100 } }
    }
    if (i < active)  return { ...def, status: 'done', data: { pct: 100 } }
    if (i > active)  return { ...def, status: 'idle', data: null }

    const status = job.status === 'error'     ? 'error'
                 : job.status === 'cancelled' ? 'cancelled'
                 : 'running'
    return { ...def, status, data: stageData(job, status) }
  })
}

/** Progress across all three rows — the header bar. Caps at 99 until done. */
export function overallPct(job) {
  if (!job) return 0
  if (job.status === 'done') return 100

  const rows = stepsFromJob(job)
  const sum = rows.reduce((acc, s) => {
    if (s.status === 'done') return acc + 100 / rows.length
    // A failed or cancelled stage keeps the bar where it stopped — dropping it
    // to zero would look like the sync never started.
    if (['running', 'error', 'cancelled'].includes(s.status)) {
      return acc + (s.data?.pct ?? 0) / rows.length
    }
    return acc
  }, 0)
  return Math.max(0, Math.min(99, Math.round(sum)))
}

/** Index of the running row (for the highlight), or -1 when nothing runs. */
export function activeIndex(job) {
  if (!job || isTerminal(job.status)) return -1
  return stageRow(job.stage)
}

/**
 * Finished syncs from GET /api/v1/sync/history, newest first, capped at `max`.
 *
 * History holds every job type (elixir and C# list their whole job tables), so
 * a queue job can be first — the panel's sync rows only ever mean a
 * `type: "sync"` run. 200 with an empty list is a normal answer (python's store
 * is in-memory), never an error state. Ordering is the backend's job (every
 * implementation lists newest first); the panel just takes the head.
 */
export function recentSyncs(items, max = 3) {
  if (!Array.isArray(items)) return []
  return items
    .filter(j => j && isTerminal(j.status) && j.type === 'sync')
    .slice(0, Math.max(0, max))
}

/**
 * The newest finished sync from the history list, or null. Kept for the single
 * "last sync" line; `recentSyncs` is the same filter with more rows.
 */
export function pickLastSync(items) {
  return recentSyncs(items, 1)[0] || null
}

/**
 * "4 min ago" style age for a history timestamp; '' when unparseable.
 *
 * `now` is injectable so the unit checks pin exact boundaries. The timestamps
 * are a python-only *extra* (finished_at/created_at) — elixir and C# send the
 * bare envelope — so callers must fall back to showing no time at all.
 */
export function relativeTime(iso, now = Date.now()) {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''

  const secs = Math.max(0, Math.round((now - t) / 1000))
  if (secs < 60) return 'just now'

  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins} min ago`

  const hours = Math.floor(mins / 60)
  if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`

  const days = Math.floor(hours / 24)
  if (days < 30) return days === 1 ? '1 day ago' : `${days} days ago`

  return new Date(t).toLocaleDateString()
}
