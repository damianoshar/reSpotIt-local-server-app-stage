/**
 * PlaylistModal
 * Handles two modes:
 *   "create"  β€” text input for playlist name, then POST /spotify/playlists
 *   "add"     β€” pick from existing playlists, then POST /spotify/playlists/{id}/add
 */
import { useState, useEffect } from 'react'
import { useSyncPhotos } from '../hooks/useSyncPhotos'
import { api } from '../api/client'
import * as localSpotify from '../services/localSpotify'

const OVERLAY = {
  position: 'fixed', inset: 0, zIndex: 100,
  background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  padding: '1rem',
}

const PANEL = {
  background: '#181818', border: '1px solid #333333', borderRadius: 8,
  width: '100%', maxWidth: 480, maxHeight: '80vh',
  display: 'flex', flexDirection: 'column',
  boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
}

function StatusBanner({ type, message }) {
  const bg = type === 'success' ? '#1a3a1a' : '#3a1a1a'
  const color = type === 'success' ? '#1DB954' : '#E22134'
  return (
    <div style={{ background: bg, border: `1px solid ${color}33`, borderRadius: 5,
                  padding: '10px 14px', fontFamily: 'Space Mono, monospace',
                  fontSize: '0.75rem', color, marginTop: 12 }}>
      {message}
    </div>
  )
}

export function PlaylistModal({ mode, albumIds, onClose, localMode = false }) {
  const [syncPhotos] = useSyncPhotos()
  const [name, setName]           = useState('')
  const [playlists, setPlaylists] = useState([])
  const [loadingPL, setLoadingPL] = useState(mode === 'add')
  const [selected, setSelected]   = useState(null)
  const [loading, setLoading]     = useState(false)
  const [status, setStatus]       = useState(null)   // {type, message}

  useEffect(() => {
    if (mode === 'add') {
      const loader = localMode ? localSpotify.getUserPlaylists() : api.getPlaylists()
      Promise.resolve(loader)
        .then(data => setPlaylists(data))
        .catch(e => setStatus({ type: 'error', message: e.message }))
        .finally(() => setLoadingPL(false))
    }
  }, [mode])

  const handleSubmit = async () => {
    setLoading(true)
    setStatus(null)
    try {
      if (mode === 'create') {
        let res
        if (localMode) {
          res = await localSpotify.createPlaylist(name.trim(), albumIds)
        } else {
          res = await api.createPlaylist(name.trim(), '', albumIds)
        }
        setStatus({
          type: 'success',
          message: `✓ Created "${res.playlist_name || res.name}" with ${res.tracks_added || albumIds.length * 0 || 'some'} tracks.`,
        })
      } else {
        if (!selected) return
        let added
        if (localMode) {
          added = await localSpotify.addAlbumsToPlaylist(selected.id, albumIds)
        } else {
          const res = await api.addToPlaylist(selected.id, albumIds)
          added = res.tracks_added
        }
        setStatus({
          type: 'success',
          message: `✓ Added ${added} tracks to "${selected.name}".`,
        })
      }
    } catch (e) {
      const msg = e.message.includes('403')
        ? 'Permission denied. Delete your token and re-authenticate with expanded scopes.'
        : e.message
      setStatus({ type: 'error', message: msg })
    } finally {
      setLoading(false)
    }
  }

  const canSubmit = mode === 'create'
    ? name.trim().length > 0 && !loading
    : selected !== null && !loading

  return (
    <div style={OVERLAY} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={PANEL}>
        {/* Header */}
        <div style={{ padding: '18px 20px 14px', borderBottom: '1px solid #333333',
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontFamily: 'Bodoni Moda, serif', fontSize: '1.15rem', color: '#FFFFFF' }}>
              {mode === 'create' ? 'Create Playlist' : 'Add to Playlist'}
            </div>
            <div style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.65rem',
                          color: '#B3B3B3', marginTop: 3 }}>
              {albumIds.length} album{albumIds.length !== 1 ? 's' : ''} selected
            </div>
          </div>
          <button onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#555555',
                     cursor: 'pointer', fontSize: '1.2rem', lineHeight: 1 }}>Γ—</button>
        </div>

        {/* Body */}
        <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
          {mode === 'create' && (
            <>
              <label style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.65rem',
                              textTransform: 'uppercase', letterSpacing: '0.1em', color: '#555555',
                              display: 'block', marginBottom: 6 }}>
                Playlist Name
              </label>
              <input
                autoFocus
                className="filter-input"
                placeholder="My awesome playlist…"
                value={name}
                onChange={e => setName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && canSubmit && handleSubmit()}
                disabled={!!status?.type && status.type === 'success'}
              />
            </>
          )}

          {mode === 'add' && (
            <>
              {loadingPL ? (
                <div style={{ color: '#B3B3B3', fontSize: '0.85rem', padding: '12px 0' }}>
                  Loading playlists…
                </div>
              ) : playlists.length === 0 && !status ? (
                <div style={{ color: '#B3B3B3', fontSize: '0.85rem' }}>No playlists found.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {playlists.map(pl => (
                    <button
                      key={pl.id}
                      onClick={() => setSelected(pl)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        padding: '8px 10px', borderRadius: 5, border: 'none',
                        cursor: 'pointer', textAlign: 'left', transition: 'background 0.15s',
                        background: selected?.id === pl.id ? '#142410' : '#191414',
                        outline: selected?.id === pl.id ? '1px solid #1DB954' : '1px solid #333333',
                      }}
                    >
                      {pl.image_url
                        ? (syncPhotos && pl.image_url ? <img src={pl.image_url} alt="" style={{ width: 36, height: 36, borderRadius: 3, objectFit: 'cover', flexShrink: 0 }} /> : null)
                        : <div style={{ width: 36, height: 36, borderRadius: 3, background: '#333333', flexShrink: 0 }} />
                      }
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: '0.85rem', color: '#FFFFFF', fontWeight: 500,
                                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {pl.name}
                        </div>
                        <div style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.6rem', color: '#B3B3B3' }}>
                          {pl.track_count} tracks Β· {pl.owner}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {status && <StatusBanner {...status} />}
        </div>

        {/* Footer */}
        {!status?.type || status.type === 'error' ? (
          <div style={{ padding: '12px 20px', borderTop: '1px solid #333333',
                        display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button className="btn btn-ghost" onClick={onClose} disabled={loading}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSubmit} disabled={!canSubmit}>
              {loading ? '…' : mode === 'create' ? 'Create' : 'Add'}
            </button>
          </div>
        ) : (
          <div style={{ padding: '12px 20px', borderTop: '1px solid #333333', textAlign: 'right' }}>
            <button className="btn btn-ghost" onClick={onClose}>Close</button>
          </div>
        )}
      </div>
    </div>
  )
}
