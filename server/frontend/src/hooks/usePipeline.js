/**
 * usePipeline
 * -----------
 * The library sync as ONE canonical job.
 *
 * POST /api/v1/sync/albums starts fetch → images → load server-side and the
 * job's `stage` says which part is running, so this hook is a single poller —
 * not the three-chained-jobs orchestrator it used to be, which needed a
 * start/read/cancel route per stage and therefore only ever worked against this
 * one backend.
 *
 * Polling and cancellation go through the generic job endpoints, and the
 * stage → row mapping lives in ../pipelineStages (pure, unit-checked).
 *
 * Status, stage and last known progress are persisted, so a reload re-attaches
 * to a sync that is still running instead of showing a blank panel. When there
 * is nothing local to show, the hook reads GET /api/v1/sync/history instead, so
 * a fresh browser still says when the library was last synced.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'
import { describeRemoteError } from '../api/errorCodes'
import {
  blankSteps, stepsFromJob, overallPct as overallPctOf, activeIndex, isTerminal,
  recentSyncs,
} from '../pipelineStages'

const STORAGE_KEY  = 'reSpotIt_sync_job_v2'
const POLL_MS      = 2000
const HISTORY_ROWS = 3   // one "Last sync" line + two compact "earlier" rows

// Saved sync state is per account — two users sharing a browser must not see
// each other's mid-flight sync rows (and 401s would look like gibberish too).
function storageKeyFor(userKey) {
  return userKey && userKey !== 'anon' ? `${STORAGE_KEY}:${userKey}` : STORAGE_KEY
}

function loadSaved(key) {
  try {
    const raw = localStorage.getItem(key)
    if (raw) return JSON.parse(raw)
  } catch { /**/ }
  return null
}

export function usePipeline(enabled = true, userKey = 'anon') {
  const [job, setJob] = useState(() => loadSaved(storageKeyFor(userKey)))
  const [lastSync, setLastSync] = useState(null)
  const [recentRuns, setRecentRuns] = useState([])
  // "Clean" wipes the server library before fetching. Destructive, so it is a
  // deliberate switch: default off, and deliberately not persisted — a reload
  // must never silently arm a wipe.
  const [clean, setClean] = useState(false)
  const timerRef = useRef(null)
  const jobRef   = useRef(job)
  useEffect(() => { jobRef.current = job }, [job])

  const persist = useCallback((j) => {
    setJob(j)
    jobRef.current = j
    const key = storageKeyFor(userKey)
    if (j) localStorage.setItem(key, JSON.stringify(j))
    else   localStorage.removeItem(key)
  }, [userKey])

  // Re-scope when the signed-in account changes (login/logout in this tab):
  // the panel shows the new account's saved state, never the old one's.
  const prevKeyRef = useRef(null)
  useEffect(() => {
    const key = storageKeyFor(userKey)
    if (prevKeyRef.current === key) return
    prevKeyRef.current = key
    const saved = loadSaved(key)
    setJob(saved)
    jobRef.current = saved
  }, [userKey])

  const stopPolling = useCallback(() => {
    clearInterval(timerRef.current)
    timerRef.current = null
  }, [])

  const poll = useCallback(async (jobId) => {
    try {
      const data = await api.getJob(jobId)
      persist(data)
      if (isTerminal(data.status)) stopPolling()
      return data
    } catch (e) {
      if (e?.status === 404) {
        // The job is not on the server: it was finished and evicted, or the id
        // is a leftover from a previous session. Saying "Syncing…" forever
        // would be a lie, so say what happened.
        persist({ ...(jobRef.current || {}), status: 'error',
                  error: 'That sync job is no longer on the server.' })
        stopPolling()
        return null
      }
      // Network blip or a restarting server: keep the last known state and let
      // the next tick try again rather than wiping the panel.
      console.error('Poll error:', e)
      return null
    }
  }, [persist, stopPolling])

  // Resume an in-flight sync on mount — server mode only: in local mode there
  // is no server to poll and a saved job must not surface.
  useEffect(() => {
    if (!enabled) { stopPolling(); return undefined }
    const saved = jobRef.current
    if (saved?.job_id && !isTerminal(saved.status)) {
      timerRef.current = setInterval(() => poll(saved.job_id), POLL_MS)
      poll(saved.job_id)
    }
    return stopPolling
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, userKey])

  // The "last sync" line comes from the server's job history, not from
  // localStorage: that is the one source that knows about a run this browser
  // never saw (another device, a cleared site, a closed tab). Only fetched when
  // there is no saved job to show, and a failure is silently ignored — history
  // is a nicety, never a reason to block or empty the panel.
  useEffect(() => {
    // Disabling (local mode) must drop the server-side lines, not freeze them.
    // 'anon' means the JWT login gate is up: /sync/history is per-user too and
    // would 401, so wait for an account.
    if (!enabled || userKey === 'anon') { setLastSync(null); setRecentRuns([]); return undefined }
    if (jobRef.current) return undefined   // a saved job already fills the panel
    let alive = true
    api.getSyncHistory(10)
      .then(res => {
        if (!alive) return
        const runs = recentSyncs(res?.data, HISTORY_ROWS)
        setLastSync(runs[0] ?? null)
        setRecentRuns(runs.slice(1))
      })
      .catch(() => { /**/ })
    return () => { alive = false }
  }, [enabled, userKey])

  const start = useCallback(async () => {
    if (!enabled) return
    stopPolling()
    setLastSync(null)
    setRecentRuns([])
    persist({ status: 'pending', stage: 'albums', fetched: 0, total: 0 })
    try {
      // What "Sync" does: fetch everything, download any missing covers, load —
      // one canonical job. `clean` (wipe the server library first) is the one
      // caller-chosen option.
      const res = await api.startFullSync({ clean, downloadImages: true })
      persist({ job_id: res.job_id, status: 'running', stage: 'albums', fetched: 0, total: 0 })
      timerRef.current = setInterval(() => poll(res.job_id), POLL_MS)
      await poll(res.job_id)
    } catch (e) {
      // The start call itself failed — 422 not_connected is the common one.
      // Render it on the sync row exactly like a failed job, so there is one
      // "this did not run" path instead of two.
      persist({ status: 'error', stage: 'albums', fetched: 0, total: 0,
                error: describeRemoteError(e, 'Sync failed') })
    }
  }, [enabled, clean, persist, poll, stopPolling])

  const stop = useCallback(async () => {
    const id = jobRef.current?.job_id
    stopPolling()
    if (!id) return

    // The canonical cancel answers 409 when the job is not running — it may
    // have finished while the button was being clicked. Retry once after a beat
    // (the worker may not have flipped to running yet), then let the poll decide
    // rather than inventing a state locally.
    for (const attempt of [0, 1]) {
      try { await api.cancelJob(id); break }
      catch (e) {
        if (e?.status !== 409 || attempt === 1) break
        await new Promise(r => setTimeout(r, 800))
      }
    }

    const state = await poll(id)
    if (state && !isTerminal(state.status)) {
      timerRef.current = setInterval(() => poll(id), POLL_MS)
    }
  }, [poll, stopPolling])

  const reset = useCallback(() => {
    stopPolling()
    persist(null)
    // Dismissing hides the panel, so the history lines must go too — otherwise
    // "×" would appear to do nothing (the server would keep answering with the
    // same last run until the next reload).
    setLastSync(null)
    setRecentRuns([])
  }, [persist, stopPolling])

  // ── Derived ────────────────────────────────────────────────────────────────

  const steps       = job ? stepsFromJob(job) : blankSteps()
  const isRunning   = !!job && !isTerminal(job.status)
  const isDone      = job?.status === 'done'
  const hasError    = job?.status === 'error'
  const isCancelled = job?.status === 'cancelled'
  const hasActivity = !!job

  return {
    steps,
    isRunning, isDone, hasError, isCancelled, hasActivity,
    activeIdx:  activeIndex(job),
    overallPct: overallPctOf(job),
    lastSync,
    recentRuns,
    clean, setClean,
    start, stop, reset,
  }
}
