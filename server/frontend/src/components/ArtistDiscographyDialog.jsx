import { useEffect, useState } from 'react'
import { api } from '../api/client'
import * as localSpotify from '../services/localSpotify'

const GROUPS = [
  { key: 'all', label: 'All' },
  { key: 'album', label: 'Albums' },
  { key: 'single', label: 'Singles' },
  { key: 'appears_on', label: 'Appears on' },
  { key: 'compilation', label: 'Compilations' },
]

export function ArtistDiscographyDialog({ open, onClose, onToast, localMode = false }) {
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [artists, setArtists] = useState([])
  const [albums, setAlbums] = useState([])
  const [artist, setArtist] = useState(null)
  const [group, setGroup] = useState('all')
  const [selected, setSelected] = useState(new Set())
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) {
      setQuery('')
      setArtists([])
      setAlbums([])
      setArtist(null)
      setSelected(new Set())
      setName('')
      setError('')
    }
  }, [open])

  const search = async () => {
    if (!query.trim()) return
    setSearching(true)
    setError('')
    try {
      const res = localMode
        ? await localSpotify.searchSpotifyCatalog(query.trim(), 8)
        : await api.searchSpotifyCatalog(query.trim(), 8)
      setArtists(res.artists || [])
      setAlbums([])
      setArtist(null)
      setSelected(new Set())
    } catch (e) {
      setError(e?.message || 'Search failed')
    } finally {
      setSearching(false)
    }
  }

  const loadArtist = async (a) => {
    setArtist(a)
    setGroup('all')
    setSelected(new Set())
    setBusy(true)
    setError('')
    try {
      const res = localMode
        ? { albums: await localSpotify.getArtistAlbums(a.id) }
        : await api.getArtistAlbums(a.id)
      setAlbums(res.albums || [])
      setName(`${a.name} discography`)
    } catch (e) {
      setError(e?.message || 'Failed to load discography')
      setAlbums([])
    } finally {
      setBusy(false)
    }
  }

  const visibleAlbums = albums.filter((album) => group === 'all' || album.album_group === group || album.album_type === group)

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const createPlaylist = async () => {
    const ids = [...selected]
    if (!ids.length || !name.trim()) return
    setBusy(true)
    try {
      const res = localMode
        ? await localSpotify.createPlaylist(name.trim(), ids)
        : await api.createPlaylist(name.trim(), '', ids)
      onToast?.(`Created "${res.playlist_name || res.name}" with ${res.tracks_added ?? selected.size} tracks.`, true)
    } catch (e) {
      onToast?.(e?.message || 'Failed to create playlist', false)
    } finally {
      setBusy(false)
    }
  }

  const saveAlbums = async () => {
    const ids = [...selected]
    if (!ids.length) return
    setBusy(true)
    try {
      const res = localMode
        ? await localSpotify.saveAlbums(ids)
        : await api.saveSpotifyAlbums(ids)
      onToast?.(`Saved ${res.saved} album${res.saved === 1 ? '' : 's'} to Spotify.`, true)
    } catch (e) {
      onToast?.(e?.message || 'Failed to save albums', false)
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,0.75)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}
         onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{ background: '#181818', border: '1px solid #333333', borderRadius: 8, width: '100%',
                    maxWidth: 820, maxHeight: '88vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #333333', display: 'flex', justifyContent: 'space-between' }}>
          <h2 style={{ fontFamily: 'Bodoni Moda, serif', fontSize: '1.15rem', color: '#fff' }}>Artist discography &amp; playlist</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
        </div>
        <div style={{ padding: 20, overflowY: 'auto', flex: 1 }}>
          <div className="flex items-center gap-2 mb-4">
            <input className="filter-input" style={{ flex: 1 }} placeholder="Search Spotify artists or albums"
                   value={query} onChange={(e) => setQuery(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && search()} />
            <button className="btn btn-ghost btn-sm" onClick={search} disabled={searching}>
              {searching ? 'Searching…' : 'Search'}
            </button>
          </div>
          {error && <div className="font-mono text-xs mb-3" style={{ color: '#E22134' }}>{error}</div>}

          {artists.length > 0 && !artist && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10, marginBottom: 16 }}>
              {artists.map((a) => (
                <button key={a.id} className="btn btn-ghost" style={{ justifyContent: 'flex-start', textAlign: 'left' }}
                        onClick={() => loadArtist(a)}>
                  {a.image_url && <img src={a.image_url} alt="" style={{ width: 36, height: 36, borderRadius: 18, objectFit: 'cover' }} />}
                  <span style={{ minWidth: 0 }}>
                    <span className="block text-sm text-ink truncate">{a.name}</span>
                    <span className="font-mono text-[0.6rem] text-muted">{a.followers.toLocaleString()} followers</span>
                  </span>
                </button>
              ))}
            </div>
          )}

          {artist && (
            <>
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-display text-lg">{artist.name}</h3>
                <button className="btn btn-ghost btn-sm" onClick={() => { setArtist(null); setAlbums([]) }}>Back to results</button>
              </div>
              <div className="flex items-center gap-1 mb-3 flex-wrap">
                {GROUPS.map((g) => (
                  <button key={g.key} className={'btn btn-ghost btn-sm' + (group === g.key ? ' btn-primary' : '')}
                          onClick={() => setGroup(g.key)}>
                    {g.label}
                  </button>
                ))}
                <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set(visibleAlbums.map((a) => a.id)))}>
                  Select all shown
                </button>
              </div>
              {busy && <div className="font-mono text-xs text-muted mb-3">Loading discography…</div>}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
                {visibleAlbums.map((album) => (
                  <label key={album.id} style={{ border: '1px solid #333333', borderRadius: 6, padding: 8, cursor: 'pointer',
                                                background: selected.has(album.id) ? '#142410' : '#181818' }}>
                    <input type="checkbox" checked={selected.has(album.id)} onChange={() => toggle(album.id)} style={{ marginBottom: 6 }} />
                    {album.image_url && (
                      <img src={album.image_url} alt="" style={{ width: '100%', aspectRatio: '1', objectFit: 'cover', borderRadius: 4, marginBottom: 6 }} />
                    )}
                    <div className="text-sm text-ink truncate" title={album.title}>{album.title}</div>
                    <div className="font-mono text-[0.6rem] text-muted">{album.year || '?'} · {album.album_group || album.album_type}</div>
                  </label>
                ))}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <input className="filter-input" style={{ maxWidth: 260 }} placeholder="Playlist name"
                       value={name} onChange={(e) => setName(e.target.value)} />
                <button className="btn btn-primary btn-sm" onClick={createPlaylist}
                        disabled={busy || selected.size === 0 || !name.trim()}>
                  Create private playlist
                </button>
                <button className="btn btn-ghost btn-sm" onClick={saveAlbums}
                        disabled={busy || selected.size === 0}>
                  Save selected to Spotify
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
