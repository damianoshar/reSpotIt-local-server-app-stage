import { useEffect, useState } from 'react'
import { useSyncPhotos } from '../hooks/useSyncPhotos'
import { api } from '../api/client'
import { getLocalSpotifyToken, hasLocalSpotify } from '../services/spotifyAuth'
import { playUris } from '../services/webPlayback'
import { spotifyAlbumUrl } from '../utils/spotifyLinks'

const SPOTIFY_ID = /^[A-Za-z0-9]{22}$/

function trackUrl(track) {
  const id = track?.spotify_id || track?.id
  return typeof id === 'string' && SPOTIFY_ID.test(id)
    ? `https://open.spotify.com/track/${id}`
    : (track?.uri || track?.track_uri || '').replace('spotify:track:', 'https://open.spotify.com/track/') || ''
}

export function AlbumTrackSheet({ album, onClose, onToast }) {
  const [syncPhotos] = useSyncPhotos()
  const [tracks, setTracks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [queueing, setQueueing] = useState(false)
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.getAlbumTracks(album.id)
      .then((data) => {
        if (cancelled) return
        setTracks(Array.isArray(data?.items) ? data.items : Array.isArray(data?.tracks) ? data.tracks : Array.isArray(data) ? data : [])
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || 'Failed to load tracks')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [album.id])

  const playbackToken = async () => (
    hasLocalSpotify()
      ? getLocalSpotifyToken()
      : (await api.getPlayerToken()).access_token
  )

  const handleQueue = async () => {
    const uris = tracks.map((t) => t.uri || t.track_uri).filter(Boolean)
    if (!uris.length) return
    setQueueing(true)
    try {
      await api.queueTrackUris(uris)
      onToast?.(`Queued ${uris.length} track${uris.length === 1 ? '' : 's'}`, true)
    } catch (e) {
      onToast?.(e?.message || 'Failed to queue tracks', false)
    } finally {
      setQueueing(false)
    }
  }

  const handlePlayAlbum = async () => {
    const uris = tracks.map((t) => t.uri || t.track_uri).filter(Boolean)
    if (!uris.length) {
      onToast?.('No playable track URIs for this album', false)
      return
    }
    setPlaying(true)
    try {
      await playUris(uris, playbackToken)
      onToast?.(`Playing ${uris.length} track${uris.length === 1 ? '' : 's'}`, true)
    } catch (e) {
      onToast?.(e?.message || 'Playback failed', false)
    } finally {
      setPlaying(false)
    }
  }

  const handlePlayTrack = async (track) => {
    const uri = track?.uri || track?.track_uri
    if (!uri) {
      onToast?.('No playable track URI', false)
      return
    }
    setPlaying(true)
    try {
      await playUris([uri], playbackToken)
      onToast?.(`Playing ${track.name || track.title || 'track'}`, true)
    } catch (e) {
      onToast?.(e?.message || 'Playback failed', false)
    } finally {
      setPlaying(false)
    }
  }

  const href = spotifyAlbumUrl(album)
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,0.75)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}
         onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{ background: '#181818', border: '1px solid #333333', borderRadius: 8,
                    width: '100%', maxWidth: 640, maxHeight: '80vh', display: 'flex',
                    flexDirection: 'column', boxShadow: '0 24px 64px rgba(0,0,0,0.6)' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #333333',
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: 'Bodoni Moda, serif', fontSize: '1.1rem', color: '#fff' }}>
              {album.title}
            </div>
            <div style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.65rem', color: '#B3B3B3', marginTop: 3 }}>
              {album.artist} · {tracks.length || album.track_count || '?'} track{tracks.length !== 1 ? 's' : ''}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            {tracks.length > 0 && (
              <button className="btn btn-primary btn-sm" onClick={handlePlayAlbum} disabled={playing}>
                {playing ? 'Playing…' : 'Play album'}
              </button>
            )}
            {tracks.length > 0 && (
              <button className="btn btn-ghost btn-sm" onClick={handleQueue} disabled={queueing}>
                {queueing ? 'Queuing…' : 'Queue all'}
              </button>
            )}
            {href && (
              <a className="btn btn-ghost btn-sm" href={href} target="_blank" rel="noopener noreferrer">
                Spotify ↗
              </a>
            )}
            <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
          </div>
        </div>
        <div style={{ overflowY: 'auto', padding: '8px 12px', flex: 1 }}>
          {loading && <div className="font-mono text-xs text-muted">Loading tracks…</div>}
          {error && <div className="font-mono text-xs" style={{ color: '#E22134' }}>{error}</div>}
          {!loading && !error && tracks.length === 0 && (
            <div className="text-sm text-muted">No cached tracks for this album.</div>
          )}
          {!loading && tracks.map((track, index) => {
            const href = trackUrl(track)
            return (
              <div key={track.uri || track.track_uri || index}
                   style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 6px',
                            borderBottom: '1px solid #242424' }}>
                <span style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.65rem', color: '#555555', width: 24, textAlign: 'right' }}>
                  {index + 1}
                </span>
                {syncPhotos && (track.image_url || album.image_url) && (
                  <img src={track.image_url || album.image_url} alt=""
                       style={{ width: 32, height: 32, borderRadius: 3, objectFit: 'cover', flexShrink: 0 }} />
                )}
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="text-sm text-ink truncate" title={track.name || track.title}>
                    {track.name || track.title || 'Unknown track'}
                  </div>
                  <div className="font-mono text-[0.6rem] text-muted truncate">
                    {track.artist || album.artist}{track.duration_ms ? ` · ${Math.round(track.duration_ms / 1000)}s` : ''}
                  </div>
                </div>
                {(track.uri || track.track_uri) && (
                  <button type="button" className="btn btn-ghost btn-sm"
                          onClick={() => handlePlayTrack(track)} disabled={playing}
                          style={{ padding: '2px 8px', fontSize: '0.7rem' }}>
                    ▶
                  </button>
                )}
                {href && (
                  <a href={href} target="_blank" rel="noopener noreferrer"
                     style={{ color: '#1DB954', fontSize: '0.75rem', textDecoration: 'none' }}>
                    ↗
                  </a>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
