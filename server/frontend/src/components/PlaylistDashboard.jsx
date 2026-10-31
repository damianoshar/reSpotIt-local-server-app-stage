import { useEffect, useMemo, useRef, useState } from 'react'
import { useSyncPhotos } from '../hooks/useSyncPhotos'
import { api } from '../api/client'
import { usePlaylistDashboard } from '../hooks/usePlaylistDashboard'
import { spotifyPlaylistUrl, spotifyAlbumUrl } from '../utils/spotifyLinks'
import { PlaylistModal } from './PlaylistModal'
import { AlbumTrackSheet } from './AlbumTrackSheet'

function PlaylistCard({ playlist, disabled, selected = false, onToggleSelect, onOpen, viewMode = 'grid' }) {
  const [syncPhotos] = useSyncPhotos()
  const href = spotifyPlaylistUrl(playlist.id)
  if (viewMode === 'list') {
    return (
      <div className="pl-list-row" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
            borderBottom: '1px solid #242424' }}>
        {onToggleSelect && (
          <input type="checkbox" checked={selected} onChange={() => onToggleSelect(playlist.id)} />
        )}
        <button type="button" className="btn btn-ghost btn-sm" style={{ flex: 1, justifyContent: 'flex-start', textAlign: 'left' }}
                onClick={() => onOpen(playlist)} disabled={disabled}>
          {syncPhotos && playlist.image_url && (
            <img src={playlist.image_url} alt="" style={{ width: 32, height: 32, borderRadius: 4, objectFit: 'cover', marginRight: 10 }} />
          )}
          <span style={{ minWidth: 0 }}>
            <span className="block text-sm text-ink truncate">{playlist.name}</span>
            <span className="font-mono text-[0.6rem] text-muted">
              {playlist.track_count} track{playlist.track_count === 1 ? '' : 's'} · {playlist.synced_at ? 'synced' : 'not synced'}
            </span>
          </span>
        </button>
        {href && <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#1DB954' }}>↗</a>}
      </div>
    )
  }
  return (
    <div className="pl-card-wrap" style={{ position: 'relative' }}>
      <label style={{ position: 'absolute', top: 6, right: 6, zIndex: 3, background: 'rgba(0,0,0,0.55)', borderRadius: 4, padding: '2px 4px' }}>
        <input type="checkbox" checked={selected}
          onChange={(e) => { e.stopPropagation(); onToggleSelect?.(playlist.id) }} />
      </label>
      <button
        type="button"
        className={'pl-card text-left animate-fade-in' + (playlist.synced_at ? ' pl-card--cached' : '')}
        onClick={() => onOpen(playlist)}
        disabled={disabled}
        title={playlist.synced_at ? 'Cached on the server — opens instantly' : 'Not synced yet — syncs when opened'}
        style={{ background: '#181818', border: '1px solid #333333', borderRadius: 8, padding: 12,
                 cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.6 : 1, width: '100%' }}
      >
        <div className="flex items-center gap-3">
          <span aria-hidden="true" style={{ width: 44, height: 44, flexShrink: 0, borderRadius: 6, background: '#191414',
            display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#555555',
            fontSize: '1.1rem', overflow: 'hidden', position: 'relative' }}>
            ◉
            {syncPhotos && playlist.image_url && (
              <img src={playlist.image_url} alt="" loading="lazy"
                   style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
                   onError={(e) => { e.currentTarget.style.display = 'none' }} />
            )}
          </span>
          <span className="min-w-0">
            <span className="block text-sm text-ink truncate" title={playlist.name}>{playlist.name}</span>
            <span className="block font-mono text-[0.6rem] text-muted">
              {playlist.track_count} track{playlist.track_count === 1 ? '' : 's'} · {playlist.synced_at ? 'synced' : 'not synced'}
            </span>
          </span>
        </div>
      </button>
      {href && (
        <a className="pl-card-link" href={href} target="_blank" rel="noopener noreferrer"
           onClick={(e) => e.stopPropagation()} aria-label={'Open ' + playlist.name + ' on Spotify'} title="Open on Spotify">
          ↗
        </a>
      )}
    </div>
  )
}

function PlaylistAlbumCard({ album, selected, onToggleSelect, onShowTracks }) {
  const [syncPhotos] = useSyncPhotos()
  const href = spotifyAlbumUrl(album)
  return (
    <div className="pl-album-card animate-fade-in">
      <div style={{ position: 'relative', paddingBottom: '100%', background: '#181818', borderRadius: 6, overflow: 'hidden' }}>
        <span aria-hidden="true" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', color: '#555555', fontSize: '1.4rem' }}>◉</span>
        {syncPhotos && album.image_url && (
          <img src={album.image_url} alt={album.title} loading="lazy"
               style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
               onError={(e) => { e.currentTarget.style.display = 'none' }} />
        )}
        <label style={{ position: 'absolute', top: 6, left: 6, zIndex: 3, background: 'rgba(0,0,0,0.55)', borderRadius: 4, padding: '2px 4px' }}>
          <input type="checkbox" checked={selected} onChange={() => onToggleSelect?.(album.id)} />
        </label>
        {href && (
          <a className="pl-album-link" href={href} target="_blank" rel="noopener noreferrer"
             onClick={(e) => e.stopPropagation()} aria-label={'Open ' + album.title + ' on Spotify'} title="Open on Spotify">
            ↗
          </a>
        )}
      </div>
      <div className="mt-2 min-w-0">
        <div className="text-sm text-ink truncate" title={album.title}>{album.title}</div>
        <div className="text-xs text-secondary truncate" title={album.artist}>{album.artist || '—'}</div>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          {album.year ? <span className="font-mono text-[0.6rem] text-muted">{album.year}</span> : null}
          <span className="badge" title={(album.track_titles || []).join(' · ')}>
            {album.track_count} track{album.track_count === 1 ? '' : 's'}
          </span>
          {album.genre ? <span className="badge badge-accent">{album.genre}</span> : null}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onShowTracks?.(album)}>
            Tracks
          </button>
        </div>
      </div>
    </div>
  )
}

export function PlaylistDashboard({ onExit, onToast, spotifyLinked = true }) {
  const pd = usePlaylistDashboard()
  const startedRef = useRef(false)

  const [playlistSearch, setPlaylistSearch] = useState('')
  const [playlistSort, setPlaylistSort] = useState('name')
  const [playlistOrder, setPlaylistOrder] = useState('asc')
  const [playlistViewMode, setPlaylistViewMode] = useState('grid')
  const [albumViewMode, setAlbumViewMode] = useState('grid')
  const [columns, setColumns] = useState(4)
  const [selectedAlbumIds, setSelectedAlbumIds] = useState(new Set())
  const [trackAlbum, setTrackAlbum] = useState(null)
  const [modalMode, setModalMode] = useState(null)
  const [retention, setRetention] = useState(null)
  const [visibilityBusy, setVisibilityBusy] = useState(false)
  const [retentionBusy, setRetentionBusy] = useState(false)

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void pd.loadPlaylists()
  }, [])

  useEffect(() => {
    if (!pd.selected) {
      setRetention(null)
      return
    }
    let cancelled = false
    api.getPlaylistRetention()
      .then((rows) => {
        if (cancelled) return
        const row = Array.isArray(rows) ? rows.find((r) => r.playlist_id === pd.selected.id) : null
        setRetention(row?.expires_at || null)
      })
      .catch(() => {
        if (!cancelled) setRetention(null)
      })
    return () => { cancelled = true }
  }, [pd.selected])

  const visiblePlaylists = useMemo(() => {
    const q = playlistSearch.trim().toLowerCase()
    let list = (pd.playlists || []).filter((p) => !q || String(p.name || '').toLowerCase().includes(q))
    list = list.slice().sort((a, b) => {
      let cmp = 0
      if (playlistSort === 'tracks') cmp = (a.track_count || 0) - (b.track_count || 0)
      else if (playlistSort === 'added') cmp = (a.added_order || 0) - (b.added_order || 0)
      else cmp = String(a.name || '').localeCompare(String(b.name || ''))
      return playlistOrder === 'asc' ? cmp : -cmp
    })
    return list
  }, [pd.playlists, playlistSearch, playlistSort, playlistOrder])

  const toggleAlbumSelection = (id) => {
    setSelectedAlbumIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const clearAlbumSelection = () => setSelectedAlbumIds(new Set())

  const handleQueueSelected = async () => {
    const ids = [...selectedAlbumIds]
    if (!ids.length) return
    try {
      const res = await api.addToQueue(ids, (job) => {})
      onToast?.(`Queued ${res.queued || 0} album${res.queued === 1 ? '' : 's'}${res.failed ? ` (${res.failed} failed)` : ''}`, true)
      clearAlbumSelection()
    } catch (e) {
      onToast?.(e?.message || 'Failed to queue albums', false)
    }
  }

  const handleRemoveSelected = async () => {
    const ids = [...selectedAlbumIds]
    if (!ids.length || !pd.selected) return
    if (!window.confirm(`Remove ${ids.length} selected album${ids.length === 1 ? '' : 's'} from this playlist?`)) return
    try {
      await api.removeAlbumsFromPlaylist(pd.selected.id, ids)
      await pd.loadAlbums(true)
      onToast?.(`Removed ${ids.length} album${ids.length === 1 ? '' : 's'} from the playlist`, true)
      clearAlbumSelection()
    } catch (e) {
      onToast?.(e?.message || 'Failed to remove albums', false)
    }
  }

  const sortAlbums = (field) => {
    const nextOrder = field === pd.filters.sort && pd.filters.order === 'asc' ? 'desc' : 'asc'
    pd.updateFilter({ sort: field, order: nextOrder })
  }

  const albumGridStyle = albumViewMode === 'list'
    ? { display: 'flex', flexDirection: 'column', gap: 8 }
    : { display: 'grid', gap: 16, gridTemplateColumns: `repeat(auto-fill, minmax(${Math.max(120, columns * 28)}px, 1fr))` }

  return (
    <div className="pl-dashboard animate-fade-in">
      <div className="flex items-center justify-between mb-5 gap-4 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="font-display text-2xl font-semibold truncate">
            {pd.selected ? pd.selected.name : 'Playlists'}
          </h1>
          {pd.selected && (
            <button className="btn btn-ghost btn-sm" onClick={pd.clearPlaylist}>← All playlists</button>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {pd.selected && (
            <button className="btn btn-ghost btn-sm" onClick={() => api.playlistExportCsv(pd.selected.id)}
                    title="Export this playlist's cached albums as CSV">⤓ Export CSV</button>
          )}
          {pd.selected && spotifyLinked && (
            <>
              <button className="btn btn-ghost btn-sm" disabled={visibilityBusy}
                      onClick={async () => {
                        setVisibilityBusy(true)
                        try {
                          await api.setPlaylistVisibility(pd.selected.id, !pd.selected.public)
                          onToast?.(`Playlist is now ${pd.selected.public ? 'private' : 'public'}`, true)
                        } catch (e) {
                          onToast?.(e?.message || 'Failed to change visibility', false)
                        } finally {
                          setVisibilityBusy(false)
                        }
                      }}>
                {pd.selected.public ? 'Make private' : 'Make public'}
              </button>
              <button className="btn btn-ghost btn-sm" disabled={retentionBusy}
                      onClick={async () => {
                        const hours = window.prompt('Expire this playlist in how many hours? (leave blank to cancel)')
                        if (!hours) return
                        const n = Number(hours)
                        if (!Number.isFinite(n) || n <= 0) {
                          onToast?.('Enter a positive number of hours', false)
                          return
                        }
                        setRetentionBusy(true)
                        try {
                          const row = await api.setPlaylistRetention(pd.selected.id, { hours: n })
                          setRetention(row?.expires_at || null)
                          onToast?.('Playlist expiry set', true)
                        } catch (e) {
                          onToast?.(e?.message || 'Failed to set expiry', false)
                        } finally {
                          setRetentionBusy(false)
                        }
                      }}>
                Set expiry
              </button>
              {retention && (
                <>
                  <button className="btn btn-ghost btn-sm" disabled={retentionBusy}
                          onClick={async () => {
                            setRetentionBusy(true)
                            try {
                              await api.keepPlaylistForever(pd.selected.id)
                              setRetention(null)
                              onToast?.('Playlist kept forever', true)
                            } catch (e) {
                              onToast?.(e?.message || 'Failed to keep playlist', false)
                            } finally {
                              setRetentionBusy(false)
                            }
                          }}>
                    Keep forever
                  </button>
                  <button className="btn btn-ghost btn-sm" style={{ color: '#E22134' }} disabled={retentionBusy}
                          onClick={async () => {
                            if (!window.confirm('Delete this playlist now?')) return
                            setRetentionBusy(true)
                            try {
                              await api.deletePlaylistNow(pd.selected.id)
                              onToast?.('Playlist deleted', true)
                              pd.clearPlaylist()
                            } catch (e) {
                              onToast?.(e?.message || 'Failed to delete playlist', false)
                            } finally {
                              setRetentionBusy(false)
                            }
                          }}>
                    Delete now
                  </button>
                </>
              )}
              {retention && (
                <span className="font-mono text-[0.6rem] text-muted">expires {new Date(retention).toLocaleString()}</span>
              )}
            </>
          )}
          {pd.selected && !pd.syncBusy && spotifyLinked && (
            <button className="btn btn-ghost btn-sm" onClick={pd.syncNow} disabled={pd.loading}>↺ Resync</button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={onExit} title="Back to the library">✕ Close</button>
        </div>
      </div>

      {pd.syncBusy && (
        <div className="flex items-center gap-3 mb-4">
          <span className="step-dot step-dot-running" />
          <span className="font-mono text-xs text-accent">
            Syncing playlist… {pd.syncState.total ? `${pd.syncState.current}/${pd.syncState.total}` : pd.syncState.stage}
          </span>
          <button className="btn btn-ghost btn-sm" style={{ color: '#E22134' }} onClick={pd.cancelSync}>◼ Stop</button>
        </div>
      )}
      {pd.syncError && (
        <div className="font-mono text-xs mb-4" style={{ color: '#E22134' }}>{pd.syncError}</div>
      )}

      {!pd.selected && (
        <>
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <input
              className="filter-input"
              style={{ maxWidth: 260 }}
              placeholder={`Search ${pd.playlists.length} playlists…`}
              value={playlistSearch}
              onChange={(e) => setPlaylistSearch(e.target.value)}
            />
            <div className="flex items-center gap-1">
              {['name', 'tracks', 'added'].map((field) => (
                <button key={field} type="button" className={'btn btn-ghost btn-sm' + (playlistSort === field ? ' btn-primary' : '')}
                        onClick={() => {
                          if (playlistSort === field) setPlaylistOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
                          else { setPlaylistSort(field); setPlaylistOrder(field === 'name' ? 'asc' : 'desc') }
                        }}>
                  {field === 'name' ? 'Name' : field === 'tracks' ? 'Tracks' : 'Date added'}
                  {playlistSort === field && (playlistOrder === 'asc' ? ' ▲' : ' ▼')}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1">
              {['grid', 'list', 'compact'].map((mode) => (
                <button key={mode} type="button" className={'btn btn-ghost btn-sm' + (playlistViewMode === mode ? ' btn-primary' : '')}
                        onClick={() => setPlaylistViewMode(mode)}>
                  {mode.charAt(0).toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>
            <button className="btn btn-ghost btn-sm" onClick={pd.loadPlaylists} disabled={pd.playlistsLoading} title="Refresh">
              {pd.playlistsLoading ? '…' : '↺'}
            </button>
          </div>

          {pd.playlistsLoading && <div className="font-mono text-xs text-muted">Loading playlists…</div>}
          {pd.playlistsError && !pd.playlistsLoading && (
            <div className="font-mono text-xs" style={{ color: '#E22134' }}>{pd.playlistsError}</div>
          )}
          {!pd.playlistsLoading && !pd.playlistsError && pd.playlists.length === 0 && (
            <div className="text-sm text-muted">
              {spotifyLinked ? 'No playlists on this Spotify account yet.' : 'No cached playlists. Link Spotify to load them from your account.'}
            </div>
          )}
          {pd.selectedPlaylistIds && pd.selectedPlaylistIds.size > 0 && (
            <div className="flex items-center gap-2 mb-3">
              <span className="font-mono text-xs text-muted">{pd.selectedPlaylistIds.size} selected</span>
              <button className="btn btn-ghost btn-sm" style={{ color: '#E22134' }}
                      onClick={() => {
                        const ok = window.confirm('Delete the selected playlists from Spotify? This cannot be undone.')
                        if (ok) void pd.deleteSelectedPlaylists()
                      }}>
                Delete selected
              </button>
              <button className="btn btn-ghost btn-sm" onClick={pd.clearPlaylistSelection}>Clear selection</button>
            </div>
          )}
          {visiblePlaylists.length > 0 && (
            playlistViewMode === 'list' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {visiblePlaylists.map((p) => (
                  <PlaylistCard key={p.id} playlist={p} disabled={pd.syncBusy} viewMode="list"
                                selected={pd.selectedPlaylistIds?.has(p.id) ?? false}
                                onToggleSelect={pd.togglePlaylistSelection}
                                onOpen={(pl) => {
                                  pd.selectPlaylist(pl)
                                  onToast?.(pl.synced_at ? `Opening ${pl.name}…` : `Syncing ${pl.name} — first visit…`, true)
                                }} />
                ))}
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 12, gridTemplateColumns: playlistViewMode === 'compact'
                ? 'repeat(auto-fill, minmax(150px, 1fr))' : 'repeat(auto-fill, minmax(230px, 1fr))' }}>
                {visiblePlaylists.map((p) => (
                  <PlaylistCard key={p.id} playlist={p} disabled={pd.syncBusy}
                                selected={pd.selectedPlaylistIds?.has(p.id) ?? false}
                                onToggleSelect={pd.togglePlaylistSelection}
                                onOpen={(pl) => {
                                  pd.selectPlaylist(pl)
                                  onToast?.(pl.synced_at ? `Opening ${pl.name}…` : `Syncing ${pl.name} — first visit…`, true)
                                }} />
                ))}
              </div>
            )
          )}
        </>
      )}

      {pd.selected && (
        <>
          <div className="flex items-center gap-2 flex-wrap mb-5">
            <input className="filter-input" style={{ maxWidth: 240 }} placeholder="Search title or artist…"
                   value={pd.filters.search} onChange={(e) => pd.updateFilter({ search: e.target.value })} />
            <select className="filter-input filter-select" value={pd.filters.genre}
                    onChange={(e) => pd.updateFilter({ genre: e.target.value })}>
              <option value="">All genres</option>
              {pd.genres.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
            <select className="filter-input filter-select" value={pd.filters.artist}
                    onChange={(e) => pd.updateFilter({ artist: e.target.value })}>
              <option value="">All artists</option>
              {pd.artists.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <select className="filter-input filter-select" value={pd.filters.year}
                    onChange={(e) => pd.updateFilter({ year: e.target.value })}>
              <option value="">All years</option>
              {pd.years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <div className="flex items-center gap-1">
              {[
                { key: 'title', label: 'Title' },
                { key: 'artist', label: 'Artist' },
                { key: 'year', label: 'Year' },
                { key: 'track_count', label: 'Tracks' },
              ].map((item) => (
                <button key={item.key} type="button" className={'btn btn-ghost btn-sm' + (pd.filters.sort === item.key ? ' btn-primary' : '')}
                        onClick={() => sortAlbums(item.key)}>
                  {item.label}{pd.filters.sort === item.key && (pd.filters.order === 'asc' ? ' ▲' : ' ▼')}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1">
              {['grid', 'list', 'compact'].map((mode) => (
                <button key={mode} type="button" className={'btn btn-ghost btn-sm' + (albumViewMode === mode ? ' btn-primary' : '')}
                        onClick={() => setAlbumViewMode(mode)}>
                  {mode.charAt(0).toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'Space Mono, monospace', fontSize: '0.65rem' }}>
              Size
              <input type="range" min="2" max="6" value={columns} onChange={(e) => setColumns(Number(e.target.value))} />
            </label>
            {pd.hasActiveFilters && (
              <button className="btn btn-ghost btn-sm" onClick={pd.resetFilters}>Clear</button>
            )}
            <span className="font-mono text-[0.65rem] text-muted ml-auto pl-count">
              {pd.total.toLocaleString()} album{pd.total !== 1 ? 's' : ''}
            </span>
          </div>

          {selectedAlbumIds.size > 0 && (
            <div className="flex items-center gap-2 mb-4 flex-wrap">
              <span className="font-mono text-xs text-muted">{selectedAlbumIds.size} selected</span>
              <button className="btn btn-ghost btn-sm" onClick={handleQueueSelected}>Queue selected</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setModalMode('add')}>Add to playlist</button>
              <button className="btn btn-ghost btn-sm" style={{ color: '#E22134' }} onClick={handleRemoveSelected}>
                Remove from playlist
              </button>
              <button className="btn btn-ghost btn-sm" onClick={clearAlbumSelection}>Clear selection</button>
            </div>
          )}

          {pd.loading && pd.albums.length === 0 && (
            <div className="font-mono text-xs text-muted">Loading albums…</div>
          )}
          {!pd.loading && pd.albums.length === 0 && (
            <div className="text-sm text-muted">
              {pd.hasActiveFilters ? 'No albums match these filters.' : 'Nothing cached yet — hit Resync to fetch this playlist.'}
            </div>
          )}
          {pd.albums.length > 0 && (
            albumViewMode === 'list' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {pd.albums.map((album) => (
                  <div key={album.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderBottom: '1px solid #242424' }}>
                    <input type="checkbox" checked={selectedAlbumIds.has(album.id)} onChange={() => toggleAlbumSelection(album.id)} />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span className="block text-sm text-ink truncate">{album.title}</span>
                      <span className="font-mono text-[0.6rem] text-muted truncate">{album.artist} · {album.track_count} tracks</span>
                    </span>
                    <button className="btn btn-ghost btn-sm" onClick={() => setTrackAlbum(album)}>Tracks</button>
                  </div>
                ))}
              </div>
            ) : (
              <div style={albumGridStyle}>
                {pd.albums.map((album) => (
                  <PlaylistAlbumCard key={album.id} album={album}
                                    selected={selectedAlbumIds.has(album.id)}
                                    onToggleSelect={toggleAlbumSelection}
                                    onShowTracks={setTrackAlbum} />
                ))}
              </div>
            )
          )}
          {pd.hasMore && (
            <div className="flex justify-center mt-6">
              <button className="btn btn-ghost btn-sm" onClick={pd.loadMore} disabled={pd.loadingMore}>
                {pd.loadingMore ? 'Loading…' : `Load more (${pd.albums.length}/${pd.total})`}
              </button>
            </div>
          )}
        </>
      )}

      {modalMode === 'add' && (
        <PlaylistModal mode="add" albumIds={[...selectedAlbumIds]} onClose={() => setModalMode(null)} />
      )}
      {trackAlbum && (
        <AlbumTrackSheet album={trackAlbum} onClose={() => setTrackAlbum(null)} onToast={onToast} />
      )}
    </div>
  )
}
