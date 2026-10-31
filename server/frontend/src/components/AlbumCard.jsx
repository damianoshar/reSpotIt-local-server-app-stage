import { useState } from 'react'
import { useSyncPhotos } from '../hooks/useSyncPhotos'
import { api } from '../api/client'
import { getLocalSpotifyToken, hasLocalSpotify } from '../services/spotifyAuth'
import { playContext } from '../services/webPlayback'
import { spotifyAlbumUrl } from '../utils/spotifyLinks'

const PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300' viewBox='0 0 300 300'%3E%3Crect fill='%231b1916' width='300' height='300'/%3E%3Ccircle cx='150' cy='150' r='60' fill='%232e2a22'/%3E%3Ccircle cx='150' cy='150' r='18' fill='%231b1916'/%3E%3C/svg%3E"

function Checkbox({ checked, onChange }) {
  return (
    <div
      onClick={e => { e.stopPropagation(); onChange() }}
      style={{
        position: 'absolute', top: 6, left: 6, zIndex: 5,
        width: 20, height: 20, borderRadius: 4,
        border: `2px solid ${checked ? '#1DB954' : 'rgba(255,255,255,0.5)'}`,
        background: checked ? '#1DB954' : 'rgba(0,0,0,0.4)',
        backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'pointer', transition: 'all 0.15s', flexShrink: 0,
      }}
    >
      {checked && (
        <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
          <path d="M1 3.5L4 6.5L9 1" stroke="#121212" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      )}
    </div>
  )
}

export function AlbumCard({ album, isSelected = false, onToggleSelect, selectionActive = false, onShowTracks }) {
  const [imgErr, setImgErr]   = useState(false)
  const [hovered, setHovered] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [syncPhotos] = useSyncPhotos()

  const year    = album.release_date?.split('-')[0] ?? ''
  const artists = album.artists?.map(a => a.name).join(', ') ?? ''
  const genres  = album.genres?.slice(0, 2) ?? []
  const imgSrc  = syncPhotos && !imgErr && album.image_url ? album.image_url : PLACEHOLDER

  const showCheck = selectionActive || hovered || isSelected
  const spotifyHref = spotifyAlbumUrl(album)
  const contextUri = album?.spotify_id ? `spotify:album:${album.spotify_id}` : null

  const playbackToken = async () => (
    hasLocalSpotify()
      ? getLocalSpotifyToken()
      : (await api.getPlayerToken()).access_token
  )

  const handlePlayAlbum = async () => {
    if (!contextUri) {
      return
    }
    setPlaying(true)
    try {
      await playContext(contextUri, playbackToken)
    } catch (e) {
      // Keep the card usable even if playback cannot start.
    } finally {
      setPlaying(false)
    }
  }

  return (
    <div
      className="album-card animate-fade-in"
      style={isSelected ? { outline: '2px solid #1DB954', outlineOffset: 0 } : {}}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Cover */}
      <div className="album-cover" style={{ position: 'relative' }}>
        {showCheck && (
          <Checkbox checked={isSelected} onChange={() => onToggleSelect?.(album.spotify_id)} />
        )}
        <img src={imgSrc} alt={album.name} loading="lazy" onError={() => setImgErr(true)}
          style={{ opacity: isSelected ? 0.75 : 1, transition: 'opacity 0.2s' }} />
        <div className="album-cover-overlay">
          {contextUri && (
            <button type="button" className="btn btn-sm btn-primary" onClick={(e) => { e.stopPropagation(); void handlePlayAlbum() }} disabled={playing}>
              {playing ? '…' : '▶'}
            </button>
          )}
          {spotifyHref && (
            <a href={spotifyHref} target="_blank" rel="noopener noreferrer"
              className="btn btn-sm btn-primary" onClick={e => e.stopPropagation()}>
              ↗ Spotify
            </a>
          )}
        </div>
      </div>

      {/* Info */}
      <div className="album-info">
        <div className="album-title" title={album.name}>{album.name}</div>
        <div className="album-artist" title={artists}>{artists || '—'}</div>
        {genres.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {genres.map(g => <span key={g} className="badge">{g}</span>)}
          </div>
        )}
        <div className="album-meta">
          {year && <span className="font-mono text-[0.65rem] text-muted">{year}</span>}
          {album.album_type && album.album_type !== 'album' && (
            <span className="badge">{album.album_type}</span>
          )}
          {album.popularity != null && (
            <span className="badge badge-accent ml-auto" title="Popularity">{album.popularity}</span>
          )}
          {onShowTracks && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); onShowTracks(album) }}>
              Tracks
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
