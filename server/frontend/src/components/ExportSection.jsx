/**
 * ExportSection
 *
 * CSV export plus the server-side export history, mirroring the backup tab the
 * elixir / csharp frontends already have. This app had no export surface at
 * all, so the library could not be backed up from the UI even though the
 * backend endpoints existed.
 *
 * Two modes, one button:
 *   remote — a plain link to the contract endpoint; the browser handles the
 *            file and the server records the export, so the history refreshes.
 *   local  — the CSV is built from the IndexedDB library and saved as a blob;
 *            there is no server to record anything, so the history is hidden
 *            rather than shown empty.
 */
import { useState, useEffect } from 'react'
import { api } from '../api/client'
import { exportLibraryCsv } from '../services/localDatabase'
import { downloadLibraryCsv } from '../services/exportDownload'
import {
  backupFolderSupported, chooseBackupFolder, clearBackupFolder,
  getBackupFolderName, saveBackupToFolder,
} from '../services/backupFolder'

function formatDate(value) {
  if (!value) return ''
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString()
}

export function ExportSection({ onToast, ds, autoExport = false, onToggleAutoExport }) {
  const [open, setOpen] = useState(false)
  // null = loading, [] = nothing exported yet
  const [history, setHistory] = useState(null)
  const [folderName, setFolderName] = useState('')
  const isLocal = Boolean(ds?.isLocal)

  useEffect(() => {
    let cancelled = false
    getBackupFolderName()
      .then((name) => { if (!cancelled) setFolderName(name) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const loadHistory = async () => {
    try {
      const res = await api.exportHistory()
      setHistory(res?.data ?? [])
    } catch {
      setHistory([])
    }
  }

  useEffect(() => {
    if (open && !isLocal) void loadHistory()
  }, [open, isLocal])

  const saveBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const saveBlobToFolderOrDownload = async (blob, filename) => {
    const saved = await saveBackupToFolder(blob, filename)
    if (saved) {
      onToast?.(`Saved ${filename} to the backup folder`, true)
      return true
    }
    saveBlob(blob, filename)
    return false
  }

  const handleExport = async () => {
    const filename = `spotify-library-${new Date().toISOString().slice(0, 10)}.csv`
    if (isLocal) {
      try {
        const blob = await exportLibraryCsv()
        const saved = await saveBlobToFolderOrDownload(blob, filename)
        if (!saved) onToast?.('Exported the local library as CSV', true)
      } catch (e) {
        onToast?.(e?.message || 'Export failed', false)
      }
      return
    }

    try {
      const blob = await api.exportCsvBlob()
      const saved = await saveBlobToFolderOrDownload(blob, filename)
      if (!saved) {
        const href = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = href
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(href)
      }
      setOpen(true)
      onToast?.(saved ? 'Export saved to the backup folder' : 'Export started — downloading CSV', true)
      setTimeout(() => void loadHistory(), 1200)
    } catch (e) {
      onToast?.(e?.message || 'Export failed', false)
    }
  }

  const handleChooseFolder = async () => {
    try {
      const name = await chooseBackupFolder()
      setFolderName(name)
      onToast?.(`Backup folder set to ${name}`, true)
    } catch (e) {
      onToast?.(e?.message || 'Could not choose a backup folder', false)
    }
  }

  const handleClearFolder = async () => {
    await clearBackupFolder()
    setFolderName('')
    onToast?.('Backup folder cleared', true)
  }

  return (
    <div>
      <div className="flex items-center gap-3">
        <button
          className="btn btn-ghost btn-sm"
          title={isLocal ? 'Export the local library as CSV' : 'Export the library as CSV'}
          onClick={handleExport}
        >
          ⤓ Export CSV
        </button>
        {!isLocal && (
          <button
            className="btn btn-ghost btn-sm"
            title="Server export history"
            onClick={() => setOpen(o => !o)}
          >
            {open ? '▾ History' : '▸ History'}
          </button>
        )}
        {!isLocal && (
          <label
            className="flex items-center gap-2 font-mono text-[0.65rem] text-muted"
            title="Download a CSV backup automatically whenever a sync inserts albums"
            style={{ cursor: 'pointer' }}
          >
            <input
              type="checkbox"
              checked={Boolean(autoExport)}
              onChange={() => onToggleAutoExport?.()}
            />
            Auto-export after sync
          </label>
        )}
      </div>

      {backupFolderSupported() && (
        <div className="mt-3 pt-3" style={{ borderTop: '1px solid #333333' }}>
          <div className="font-mono text-[0.65rem] text-muted mb-2">
            Backup folder: {folderName || 'Browser downloads'}
          </div>
          <div className="flex items-center gap-2">
            <button className="btn btn-ghost btn-sm" onClick={handleChooseFolder}>
              Choose folder
            </button>
            {folderName && (
              <button className="btn btn-ghost btn-sm" onClick={handleClearFolder}>
                Clear folder
              </button>
            )}
          </div>
        </div>
      )}

      {open && !isLocal && (
        <div className="mt-2 font-mono text-[0.72rem] text-muted">
          {history === null ? (
            <span>Loading…</span>
          ) : history.length === 0 ? (
            <span>No exports yet — use Export CSV above.</span>
          ) : (
            <ul className="list-none m-0 p-0">
              {history.map((h) => (
                <li key={`${h.filename}-${h.exported_at}`} className="mt-0.5">
                  {h.filename} · {h.row_count} rows · {formatDate(h.exported_at)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
