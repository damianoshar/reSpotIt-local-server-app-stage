/**
 * DataSourceModal
 *
 * Where the app is told which library to use: the server (nginx β†’ FastAPI, the
 * default and the only place the Spotify sync pipeline can run) or a local
 * on-device library in IndexedDB.
 *
 * In local mode the Spotify pipeline, playlists and queue are unavailable by
 * nature β€” they are server-side operations that need credentials this app does
 * not hold β€” so the local half of this panel is what replaces them: CSV import,
 * export and a clear.
 *
 * Same surface as the csharp frontend's "Data source" tab, condensed into one
 * panel because this app has no settings modal to hang it off.
 */
import { useEffect, useState } from 'react'
import { importCsvText, exportLibraryCsv, clearLibrary, countAlbums } from '../services/localDatabase'
import { api } from '../api/client'

const OVERLAY = {
  position: 'fixed', inset: 0, zIndex: 100,
  background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  padding: '1rem',
}

const PANEL = {
  background: '#181818', border: '1px solid #333333', borderRadius: 8,
  width: '100%', maxWidth: 520, maxHeight: '85vh', overflowY: 'auto',
  boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
}

const LABEL = {
  fontFamily: 'Space Mono, monospace', fontSize: '0.65rem',
  textTransform: 'uppercase', letterSpacing: '0.16em', color: '#B3B3B3',
}

function Segment({ active, onClick, children }) {
  return (
    <button
      className="btn btn-sm"
      onClick={onClick}
      style={active
        ? { background: '#1DB954', color: '#121212', border: '1px solid #1DB954' }
        : { background: 'transparent', color: '#B3B3B3', border: '1px solid #3E3E3E' }}
    >
      {children}
    </button>
  )
}

export function DataSourcePanel({ ds, onToast }) {
  const { mode, serverUrl, setMode, setServerUrl, testConnection, testing, testResult } = ds

  const [urlDraft, setUrlDraft]   = useState(serverUrl)
  const [localCount, setLocalCount] = useState(null)
  const [busy, setBusy]           = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  // Last import's counters + per-row errors, shown as a report under the
  // buttons. Cleared on a new import or a clear, never persisted.
  const [lastImport, setLastImport] = useState(null)

  const refreshCount = async () => {
    try { setLocalCount(await countAlbums()) } catch { setLocalCount(null) }
  }

  // Read the local count when the panel opens and whenever the mode flips, so
  // "N albums stored in this browser" is never stale.
  useEffect(() => { void refreshCount() }, [mode])

  const handleImport = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''            // let the same file be picked again
    if (!file) return

    setBusy(true)
    try {
      const res = await importCsvText(await file.text())
      setLastImport(res)
      // File-level failures (empty file, missing columns) report zero skipped
      // rows; per-row failures report them. Word the toast from the counters,
      // not from errors[0] β€” a file with one bad row among fifty still
      // imported the other forty-nine.
      const nothingLanded = res.imported + res.existing === 0 && res.skipped === 0
      if (res.errors.length > 0 && nothingLanded) {
        onToast?.(`Import failed β€” ${res.errors[0]}`, false)
      } else if (res.imported + res.existing === 0 && res.skipped > 0) {
        onToast?.(`Import failed β€” all ${res.skipped} data row${res.skipped === 1 ? '' : 's'} skipped`, false)
      } else {
        onToast?.(
          `Imported ${res.imported} album${res.imported === 1 ? '' : 's'}` +
          (res.existing ? ` (${res.existing} already present)` : '') +
          (res.skipped ? ` Β· ${res.skipped} skipped` : ''),
          true,
        )
      }
      await refreshCount()
      ds.notifyLibraryChanged?.()
    } catch (e) {
      onToast?.(e?.message || 'Import failed', false)
    } finally {
      setBusy(false)
    }
  }

  const handleExport = async () => {
    setBusy(true)
    try {
      const blob = await exportLibraryCsv()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `spotify-library-${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      onToast?.(`Exported ${localCount ?? ''} local album${localCount === 1 ? '' : 's'}`.trim(), true)
    } catch (e) {
      onToast?.(e?.message || 'Export failed', false)
    } finally {
      setBusy(false)
    }
  }

  const handleClear = async () => {
    if (!confirmClear) { setConfirmClear(true); return }
    setBusy(true)
    try {
      await clearLibrary()
      setLastImport(null)
      await refreshCount()
      ds.notifyLibraryChanged?.()
      onToast?.('Local library cleared', true)
    } catch (e) {
      onToast?.(e?.message || 'Could not clear the local library', false)
    } finally {
      setBusy(false)
      setConfirmClear(false)
    }
  }

  const handleClearServer = async () => {
    if (!window.confirm('Clear the server library for this account? This cannot be undone.')) return
    setBusy(true)
    try {
      const res = await api.clearLibrary()
      ds.notifyLibraryChanged?.()
      onToast?.(`Server library cleared (${res?.deleted ?? 0} albums)`, true)
    } catch (e) {
      onToast?.(e?.message || 'Could not clear the server library', false)
    } finally {
      setBusy(false)
    }
  }

  const handlePushToServer = async () => {
    setBusy(true)
    try {
      const csv = await exportLibraryCsv()
      const text = await csv.text()
      const res = await api.importCsv(text, true)
      onToast?.(
        `Pushed to server: ${res.imported} imported, ${res.existing} existing, ${res.removed || 0} removed`,
        true,
      )
      ds.notifyLibraryChanged?.()
    } catch (e) {
      onToast?.(e?.message || 'Could not push the local library to the server', false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
          {/* Mode */}
          <div style={LABEL}>Library</div>
          <div className="flex gap-2 mt-2">
            <Segment active={mode === 'remote'} onClick={() => setMode('remote')}>Server</Segment>
            <Segment active={mode === 'local'}  onClick={() => setMode('local')}>This device</Segment>
          </div>
          <p className="text-xs text-muted mt-3 mb-5">
            {mode === 'remote'
              ? 'Reading from the server. Spotify sync, covers, playlists and the queue all run there.'
              : 'Reading from this browser only. Spotify sync, covers, playlists and the queue are server-side operations and are hidden β€” import a CSV to fill the library.'}
          </p>

          {/* Server URL β€” only meaningful in remote mode */}
          {mode === 'remote' && (
            <>
              <div style={LABEL}>Server URL</div>
              <div className="flex gap-2 mt-2">
                <input
                  className="filter-input flex-1 server-url-input"
                  type="text"
                  placeholder="Same origin (leave blank)"
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  onBlur={() => setServerUrl(urlDraft)}
                />
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={testing}
                  onClick={async () => { setServerUrl(urlDraft); await testConnection() }}
                >
                  {testing ? 'β€¦' : 'Test'}
                </button>
              </div>
              {testResult && (
                <div className="font-mono text-[0.7rem] mt-2"
                     style={{ color: testResult.ok ? '#1DB954' : '#E22134' }}>
                  {testResult.ok ? 'β“ ' : 'β• '}{testResult.message}
                </div>
              )}
              <p className="text-xs text-muted mt-2 mb-5">
                Blank means this page's own origin, which nginx proxies to the API.
              </p>
              <button className="btn btn-ghost btn-sm" onClick={handleClearServer} disabled={busy}
                      style={{ color: '#E22134' }}>
                Clear server library
              </button>
            </>
          )}

          {/* Local library actions */}
          {mode === 'local' && (
            <>
              <div style={LABEL}>Local library</div>
              <div className="font-mono text-xs text-secondary mt-2 mb-3">
                {localCount === null ? 'Readingβ€¦' : `${localCount.toLocaleString()} album${localCount === 1 ? '' : 's'} stored in this browser`}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <label className="btn btn-ghost btn-sm" style={{ cursor: busy ? 'default' : 'pointer' }}>
                  β¤’ Import CSV
                  <input type="file" accept=".csv,text/csv" onChange={handleImport}
                         disabled={busy} style={{ display: 'none' }} />
                </label>
                <button className="btn btn-ghost btn-sm" onClick={handleExport} disabled={busy}>
                  β¤“ Export CSV
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={handleClear}
                  disabled={busy}
                  style={{ color: confirmClear ? '#E22134' : undefined }}
                >
                  {confirmClear ? 'Confirm clear' : 'Clear library'}
                </button>
                {confirmClear && (
                  <button className="btn btn-ghost btn-sm" onClick={() => setConfirmClear(false)}>Cancel</button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={handlePushToServer} disabled={busy}>
                  Push to server
                </button>
              </div>

              {/* Per-row import report β€” the bad rows the toast only counts,
                  with the server's own wording so both import paths read the
                  same. Capped like the server's list; a long tail is counted. */}
              {lastImport && lastImport.errors.length > 0 && (
                <div className="mt-3 pt-3" style={{ borderTop: '1px solid #333333' }}>
                  <div style={LABEL}>Import report</div>
                  <div className="font-mono text-[0.7rem] text-secondary mt-2">
                    {lastImport.imported} imported Β· {lastImport.existing} already present Β· {lastImport.skipped} skipped
                  </div>
                  <ul className="mt-2 font-mono text-[0.68rem]"
                      style={{ color: '#E22134', paddingLeft: 18, listStyle: 'disc' }}>
                    {lastImport.errors.slice(0, 10).map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                  {lastImport.errors.length > 10 && (
                    <div className="font-mono text-[0.62rem] text-muted mt-1">
                      β€¦and {lastImport.errors.length - 10} more
                    </div>
                  )}
                </div>
              )}

              <p className="text-xs text-muted mt-3">
                Uses the frozen column set: <span className="font-mono">id,title,artist,year,genre,image_url,added_at</span>.
              </p>
            </>
          )}
    </div>
  )
}

/** The modal presentation of the same panel (kept for direct call sites/tests). */
export function DataSourceModal({ ds, onClose, onToast }) {
  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={PANEL} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid #333333' }}>
          <span className="font-display text-lg font-semibold text-ink">Data source</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose} title="Close">β•</button>
        </div>
        <div className="px-5 py-4">
          <DataSourcePanel ds={ds} onToast={onToast} />
        </div>
      </div>
    </div>
  )
}
