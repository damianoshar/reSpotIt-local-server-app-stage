import { useState } from 'react'
import { TERMINAL, relativeTime } from '../pipelineStages'

// β”€β”€ Last server-side sync (history line) β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

/** The one-line outcome for a finished run: counts, or why it did not finish. */
function historySummary(job) {
  if (job.status === 'error')     return job.error || 'failed'
  if (job.status === 'cancelled') return 'cancelled'
  const r = job.result || {}
  return `${r.imported ?? 0} inserted, ${r.existing ?? 0} updated`
}

// β”€β”€ Pipeline step row β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

function pct(step) {
  if (step.status === 'done')       return 100
  if (step.status === 'error')      return 100
  if (step.status === 'cancelled')  return step.data?.pct ?? 0
  if (step.status === 'running')    return step.data?.pct ?? 0
  return 0
}

function StepRow({ step, isActive }) {
  const p = pct(step)
  const fillColor =
    step.status === 'done'       ? '#1DB954'
    : step.status === 'error'    ? '#E22134'
    : step.status === 'cancelled'? '#7a7060'
    : '#1DB954'

  const dotClass =
    step.status === 'running'    ? 'step-dot-running'
    : step.status === 'done'     ? 'step-dot-done'
    : step.status === 'error'    ? 'step-dot-error'
    : 'step-dot-idle'

  const counts = (() => {
    const d = step.data
    if (!d) return null
    if (step.name === 'sync')   return d.total ? `${d.fetched ?? 0}/${d.total}` : null
    if (step.name === 'images') return d.total ? `${d.done ?? 0}/${d.total}`    : null
    if (step.name === 'load')   return d.total ? `${d.done ?? 0}/${d.total}`    : null
    return null
  })()

  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 mb-1.5">
        <span className={`step-dot ${dotClass}`} />
        <span className="font-mono text-[0.65rem] uppercase tracking-widest text-secondary">
          {step.label}
        </span>
        {counts && <span className="font-mono text-[0.6rem] text-muted ml-auto">{counts}</span>}
      </div>
      <div className="progress-track">
        <div style={{ width: `${p}%`, height: '100%', borderRadius: '999px',
                      background: fillColor, transition: 'width 0.4s ease' }} />
      </div>
      {isActive && step.data?.current_album && (
        <div className="mt-1 text-[0.7rem] text-muted truncate">{step.data.current_album}</div>
      )}
      {(step.status === 'error' || step.status === 'cancelled') && step.data?.message && (
        <div className="mt-1 text-[0.7rem] truncate"
             style={{ color: step.status === 'error' ? '#E22134' : '#B3B3B3' }}>
          {step.data.message}
        </div>
      )}
    </div>
  )
}

// β”€β”€ Quick-job row (images / load refresh) β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

function QuickJobRow({ label, job, onCancel, onDismiss }) {
  if (!job) return null

  const isRunning = !TERMINAL.includes(job.status)
  const p         = job.pct ?? 0
  const fillColor = job.status === 'done' ? '#1DB954' : job.status === 'error' ? '#E22134' : '#1DB954'
  const counts    = job.total ? `${job.fetched ?? 0}/${job.total}` : null
  // While running: which stage the job reports. When it stopped: why.
  const detail    = isRunning ? (job.stage || null) : (job.message || job.error || null)

  return (
    <div style={{ borderTop: '1px solid #333333', paddingTop: 10, marginTop: 10 }}>
      <div className="flex items-center gap-3">
        <span className={`step-dot ${isRunning ? 'step-dot-running' : job.status === 'done' ? 'step-dot-done' : job.status === 'error' ? 'step-dot-error' : 'step-dot-idle'}`} />
        <span className="font-mono text-[0.65rem] uppercase tracking-widest text-secondary flex-1">
          {label}
        </span>
        {counts && <span className="font-mono text-[0.6rem] text-muted">{counts}</span>}

        {isRunning && (
          <button className="btn btn-ghost btn-sm" style={{ color: '#E22134' }} onClick={onCancel}>
            β—Ό Stop
          </button>
        )}
        {!isRunning && (
          <button className="btn btn-ghost btn-sm" onClick={onDismiss} title="Dismiss">Γ—</button>
        )}
      </div>

      <div className="progress-track mt-2">
        <div style={{ width: `${job.status === 'done' ? 100 : p}%`, height: '100%',
                      borderRadius: '999px', background: fillColor, transition: 'width 0.4s ease' }} />
      </div>

      {detail && (
        <div className="mt-1 text-[0.7rem] text-muted truncate"
             style={{ color: job.status === 'error' ? '#E22134' : undefined }}>{detail}</div>
      )}
    </div>
  )
}

// β”€β”€ Main export β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

export function SyncPanel({ pipeline, imagesJob, loadJob, spotifyLinked = true }) {
  const { steps, isRunning, isDone, hasError, isCancelled, overallPct,
          lastSync, start, stop, reset } = pipeline
  const [expanded, setExpanded] = useState(true)

  const hasQuickActivity = imagesJob?.job || loadJob?.job
  // The history line is why a brand-new browser gets a panel at all; the
  // moment this browser has a job of its own, that job wins (and lastSync was
  // cleared by start/reset anyway).
  const showPanel        = pipeline.hasActivity || hasQuickActivity || !!lastSync
  if (!showPanel) return null

  const statusLabel =
    isRunning    ? `Syncingβ€¦ ${overallPct}%`
    : isDone     ? 'Sync complete'
    : hasError   ? 'Sync failed'
    : isCancelled? 'Sync cancelled'
    : 'Last sync'

  return (
    <div className="animate-slide-down" style={{ borderBottom: '1px solid #333333', background: '#191414' }}>
      <div className="max-w-screen-xl mx-auto px-6 py-4">

        {/* Pipeline section */}
        {pipeline.hasActivity && (
          <>
            <div className="flex items-center gap-3 mb-3">
              <span className="font-display text-sm font-semibold text-ink flex-1">{statusLabel}</span>
              <div className="flex items-center gap-2">
                {isRunning && (
                  <button className="btn btn-sm"
                    style={{ background: '#3a1a1a', color: '#E22134', border: '1px solid #5a2a2a' }}
                    onClick={stop}>
                    β—Ό Stop
                  </button>
                )}
                {!isRunning && (isDone || hasError || isCancelled) && spotifyLinked && (
                  <button className="btn btn-ghost btn-sm" onClick={() => { reset(); start() }}>
                    β†Ί Re-sync
                  </button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={() => setExpanded(e => !e)}>
                  {expanded ? 'β†‘' : 'β†“'}
                </button>
                {!isRunning && (
                  <button className="btn btn-ghost btn-sm" onClick={reset} title="Dismiss">Γ—</button>
                )}
              </div>
            </div>

            {isRunning && (
              <div className="progress-track mb-4">
                <div className="progress-fill" style={{ width: `${overallPct}%` }} />
              </div>
            )}

            {expanded && (
              <div className="flex gap-6">
                {steps.map((step, i) => (
                  <StepRow key={step.name} step={step} isActive={i === pipeline.activeIdx} />
                ))}
              </div>
            )}

            {isDone && expanded && (
              <div className="mt-3 font-mono text-[0.72rem]" style={{ color: '#1DB954' }}>
                β“ Library synced β€” {steps[2]?.data?.inserted ?? '?'} inserted,{' '}
                {steps[2]?.data?.updated ?? '?'} updated.
              </div>
            )}
          </>
        )}

        {/* Server-side history line: only when this browser has no job of its
            own, so a fresh device still says when the library was last synced
            instead of showing nothing at all. No time is shown when the backend
            sends no timestamp (elixir and C# do not) β€” better than a wrong one. */}
        {!pipeline.hasActivity && lastSync && (
          <div style={{ borderTop: '1px solid #333333', paddingTop: 10, marginTop: 10 }}>
            <div className="flex items-center gap-3">
              <span className={`step-dot ${lastSync.status === 'error' ? 'step-dot-error' : lastSync.status === 'cancelled' ? 'step-dot-idle' : 'step-dot-done'}`} />
              <span className="font-mono text-[0.65rem] uppercase tracking-widest text-secondary">
                Last sync
              </span>
              <span className="font-mono text-[0.7rem] truncate"
                    style={{ color: lastSync.status === 'error' ? '#E22134' : '#B3B3B3' }}>
                {historySummary(lastSync)}
              </span>
              <span className="font-mono text-[0.6rem] text-muted ml-auto whitespace-nowrap">
                {relativeTime(lastSync.finished_at || lastSync.created_at)}
              </span>
              {spotifyLinked && (
                <button className="btn btn-ghost btn-sm" onClick={start}>β†Ί Re-sync</button>
              )}
              <button className="btn btn-ghost btn-sm" onClick={reset} title="Dismiss">Γ—</button>
            </div>

            {/* Up to two older runs, compact. Plain text: the newest run above
                keeps the controls; these rows only carry outcome + age. */}
            {(pipeline.recentRuns || []).slice(0, 2).map((run, i) => (
              <div key={run?.job_id || `run-${i}`} className="recent-run-row flex items-center gap-3 mt-1.5 pl-5">
                <span className={`step-dot ${run?.status === 'error' ? 'step-dot-error' : run?.status === 'cancelled' ? 'step-dot-idle' : 'step-dot-done'}`} />
                <span className="font-mono text-[0.68rem] truncate"
                      style={{ color: run?.status === 'error' ? '#E22134' : '#7a7060' }}>
                  {historySummary(run || {})}
                </span>
                <span className="font-mono text-[0.6rem] text-muted ml-auto whitespace-nowrap">
                  {relativeTime(run?.finished_at || run?.created_at)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Quick job rows */}
        {imagesJob && (
          <QuickJobRow
            label="Refresh Covers"
            job={imagesJob.job}
            onCancel={imagesJob.cancel}
            onDismiss={imagesJob.dismiss}
          />
        )}
        {loadJob && (
          <QuickJobRow
            label="Reload Database"
            job={loadJob.job}
            onCancel={loadJob.cancel}
            onDismiss={loadJob.dismiss}
          />
        )}
      </div>
    </div>
  )
}
