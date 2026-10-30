/**
 * useQuickJob
 * -----------
 * One short background job (cover refresh, DB reload) with polling.
 *
 * Jobs are generic on the wire: start through the endpoint that owns the work,
 * then poll and cancel through /api/v1/jobs/{id} — there are no per-type
 * read/cancel routes any more.
 *
 * The stored object is the canonical envelope plus two derived fields, because
 * the envelope has neither:
 *   pct     — fetched/total (shared with the pipeline via ../pipelineStages)
 *   message — the failure text, or "Cancelled." for a cancelled job
 *
 * Without that derivation the row's progress bar sat at 0% for the whole run:
 * it was reading `job.pct`, which the canonical envelope does not contain.
 *
 * The job id is persisted so the row survives a page refresh — server mode only,
 * since in local mode there is no server to poll.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'
import { describeRemoteError } from '../api/errorCodes'
import { isTerminal, jobPct } from '../pipelineStages'

const POLL_MS = 2000

/** Canonical envelope + the fields the row renders. */
function toRow(data) {
  return {
    ...data,
    pct: jobPct(data),
    message: data.error || (data.status === 'cancelled' ? 'Cancelled.' : undefined),
  }
}

export function useQuickJob({ storageKey, starter, enabled = true }) {
  const [job, setJob] = useState(() => {
    try { return JSON.parse(localStorage.getItem(storageKey)) || null } catch { return null }
  })
  const timerRef = useRef(null)
  const jobRef   = useRef(job)
  useEffect(() => { jobRef.current = job }, [job])

  // storageKey carries the account scope (`:userId` suffix). When it changes
  // (a different user signed in), the row must show that account's job — not
  // the previous one's.
  const prevKeyRef = useRef(null)
  useEffect(() => {
    if (prevKeyRef.current === storageKey) return
    prevKeyRef.current = storageKey
    let saved = null
    try { saved = JSON.parse(localStorage.getItem(storageKey)) || null } catch { /**/ }
    setJob(saved)
    jobRef.current = saved
  }, [storageKey])

  const persist = useCallback((j) => {
    setJob(j)
    jobRef.current = j
    if (j) localStorage.setItem(storageKey, JSON.stringify(j))
    else   localStorage.removeItem(storageKey)
  }, [storageKey])

  const stopPolling = useCallback(() => {
    clearInterval(timerRef.current)
    timerRef.current = null
  }, [])

  const poll = useCallback(async (jobId) => {
    try {
      const data = await api.getJob(jobId)
      const row = toRow(data)
      persist(row)
      if (isTerminal(data.status)) stopPolling()
      return row
    } catch (e) {
      if (e?.status === 404) {
        persist({ ...(jobRef.current || {}), status: 'error',
                  message: 'That job is no longer on the server.' })
        stopPolling()
        return null
      }
      console.error('Poll error:', e)   // network blip: keep the last state
      return null
    }
  }, [persist, stopPolling])

  // Resume on mount if there was an in-flight job. Server mode only: in local
  // mode there is nothing to poll and a saved server job must not surface.
  useEffect(() => {
    if (!enabled) { stopPolling(); return undefined }
    const saved = jobRef.current
    if (saved?.job_id && !isTerminal(saved.status)) {
      timerRef.current = setInterval(() => poll(saved.job_id), POLL_MS)
      poll(saved.job_id)
    }
    return stopPolling
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, storageKey])

  const start = useCallback(async () => {
    if (!enabled) return
    stopPolling()
    persist({ status: 'pending', fetched: 0, total: 0, pct: 0 })
    try {
      const res = await starter()
      persist({ job_id: res.job_id, status: 'running', fetched: 0, total: 0, pct: 0 })
      timerRef.current = setInterval(() => poll(res.job_id), POLL_MS)
      await poll(res.job_id)
    } catch (e) {
      persist({ status: 'error', message: describeRemoteError(e, 'Request failed') })
    }
  }, [enabled, starter, persist, poll, stopPolling])

  const cancel = useCallback(async () => {
    const id = jobRef.current?.job_id
    stopPolling()
    if (!id) return
    try { await api.cancelJob(id) } catch { /**/ }
    const row = await poll(id)
    // A cancel that arrived before the worker started leaves the job pending;
    // keep watching until it actually reports a terminal state.
    if (row && !isTerminal(row.status)) {
      timerRef.current = setInterval(() => poll(id), POLL_MS)
    }
  }, [poll, stopPolling])

  const dismiss = useCallback(() => { stopPolling(); persist(null) }, [persist, stopPolling])

  return { job, isRunning: !!job && !isTerminal(job.status), pct: job?.pct ?? 0, start, cancel, dismiss }
}
