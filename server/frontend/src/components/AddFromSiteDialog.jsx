import { useEffect, useState } from 'react'
import { api } from '../api/client'
import * as localSpotify from '../services/localSpotify'
import { hasLocalSpotify } from '../services/spotifyAuth'
import { importCsvText } from '../services/localDatabase'

const ID_RE = /open\.spotify\.com\/(?:embed\/)?album\/([A-Za-z0-9]{22})/gi

function detectIds(text) {
  const found = new Set()
  let m
  ID_RE.lastIndex = 0
  while ((m = ID_RE.exec(text || ''))) found.add(m[1])
  ID_RE.lastIndex = 0
  return [...found]
}

function csvEscape(value) {
  const s = String(value ?? '')
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

export function AddFromSiteDialog({ open, onClose, onToast, localMode = false }) {
  const [text, setText] = useState('')
  const [ids, setIds] = useState([])
  const [meta, setMeta] = useState({})
  const [selected, setSelected] = useState(new Set())
  const [scanning, setScanning] = useState(false)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')

  useEffect(() => {
    if (!open) {
      setText('')
      setIds([])
      setMeta({})
      setSelected(new Set())
      setError('')
      setResult('')
    }
  }, [open])

  const detect = () => {
    const found = detectIds(text)
    if (!found.length) {
      setError('No Spotify album links found in that text.')
      return
    }
    setIds((prev) => [...new Set([...prev, ...found])])
    setSelected((prev) => new Set([...prev, ...found]))
    setError('')
  }

  useEffect(() => {
    const missing = ids.filter((id) => !meta[id])
    if (!missing.length) return
    let cancelled = false
    (localMode ? localSpotify.getSpotifyAlbums(missing) : api.getSpotifyAlbums(missing))
      .then((data) => {
        if (cancelled) return
        setMeta((prev) => {
          const next = { ...prev }
          for (const album of data.albums || []) next[album.id] = album
          return next
        })
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || 'Failed to load album metadata')
      })
    return () => { cancelled = true }
  }, [ids])

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const importSelected = async () => {
    const selectedIds = [...selected]
    if (!selectedIds.length) return
    setImporting(true)
    setError('')
    setResult('')
    try {
      const rows = selectedIds.map((id) => {
        const m = meta[id] || {}
        return {
          id,
          title: m.title || id,
          artist: m.artist || 'Unknown artist',
          year: m.year || '',
          genre: m.genre || '',
          image_url: m.image_url || '',
          added_at: new Date().toISOString().slice(0, 10),
        }
      })
      const header = ['id', 'title', 'artist', 'year', 'genre', 'image_url', 'added_at']
      const csv = [header.join(',')]
        .concat(rows.map((row) => header.map((key) => csvEscape(row[key])).join(',')))
        .join('\n')
      let res
      if (localMode) {
        const { importCsvText } = await import('../services/localDatabase')
        res = await importCsvText(csv)
      } else {
        res = await api.importCsv(csv, false)
      }
      setResult(`Imported ${res.imported}, existing ${res.existing}, skipped ${res.skipped}.`)
      onToast?.(`Imported ${res.imported} album${res.imported === 1 ? '' : 's'}`, true)
    } catch (e) {
      setError(e?.message || 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  if (!open) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,0.75)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}
         onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{ background: '#181818', border: '1px solid #333333', borderRadius: 8, width: '100%',
                    maxWidth: 720, maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #333333', display: 'flex', justifyContent: 'space-between' }}>
          <h2 style={{ fontFamily: 'Bodoni Moda, serif', fontSize: '1.15rem', color: '#fff' }}>Add from site</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
        </div>
        <div style={{ padding: 20, overflowY: 'auto', flex: 1 }}>
          <textarea className="filter-input" rows={5} style={{ width: '100%', resize: 'vertical' }}
                    placeholder="Paste a page URL or text containing Spotify album links"
                    value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex items-center gap-2 mt-3">
            <button className="btn btn-ghost btn-sm" onClick={detect}>Detect links</button>
            <button className="btn btn-ghost btn-sm" onClick={() => { setIds([]); setMeta({}); setSelected(new Set()) }}>Clear</button>
          </div>
          {error && <div className="font-mono text-xs mt-3" style={{ color: '#E22134' }}>{error}</div>}
          {result && <div className="font-mono text-xs mt-3" style={{ color: '#1DB954' }}>{result}</div>}
          {ids.length > 0 && (
            <>
              <div className="flex items-center gap-2 mt-4 mb-2">
                <h3 className="font-display text-lg">Detected albums ({ids.length})</h3>
                <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set(ids))}>Select all</button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {ids.map((id) => {
                  const m = meta[id]
                  return (
                    <label key={id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '8px 10px',
                                           border: '1px solid #333333', borderRadius: 6 }}>
                      <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)} />
                      <div style={{ minWidth: 0 }}>
                        <div className="text-sm text-ink truncate">{m?.title || 'Loading…'}</div>
                        <div className="font-mono text-[0.6rem] text-muted truncate">{m?.artist || id}</div>
                      </div>
                    </label>
                  )
                })}
              </div>
              <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={importSelected}
                      disabled={importing || selected.size === 0}>
                {importing ? 'Importing…' : `Import ${selected.size} selected`}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
