import { useState } from 'react'
import { useSyncPhotos } from '../hooks/useSyncPhotos'
import { api } from '../api/client'
import { getLocalSpotifyToken, hasLocalSpotify } from '../services/spotifyAuth'
import { playContext } from '../services/webPlayback'
import { spotifyAlbumUrl } from '../utils/spotifyLinks'

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='60'%3E%3Crect fill='%231b1916' width='60' height='60'/%3E%3Ccircle cx='30' cy='30' r='14' fill='%232e2a22'/%3E%3Ccircle cx='30' cy='30' r='4' fill='%231b1916'/%3E%3C/svg%3E"

const TH = ({ children, align = 'left', className = '', style = {} }) => (
  <th className={`font-mono text-[0.6rem] uppercase tracking-widest text-muted px-3 py-2 font-normal ${className}`}
    style={{ textAlign: align, background: '#191414', borderBottom: '1px solid #333333',
             position: 'sticky', top: 0, zIndex: 10, whiteSpace: 'nowrap', ...style }}>
    {children}
  </th>
)

const TD = ({ children, align = 'left', className = '', style = {} }) => (
  <td className={`px-3 py-0 ${className}`}
    style={{ textAlign: align, borderBottom: '1px solid #181818', verticalAlign: 'middle', ...style }}>
    {children}
  </td>
)

function CheckCell({ checked, onChange, hovered }) {
  return (
    <td style={{ width: 36, padding: '0 8px', borderBottom: '1px solid #181818',
                 verticalAlign: 'middle', textAlign: 'center' }}>
      <div
        onClick={e => { e.stopPropagation(); onChange() }}
        style={{
          width: 16, height: 16, borderRadius: 3, margin: '0 auto',
          border: `2px solid ${checked ? '#1DB954' : hovered ? 'rgba(255,255,255,0.3)' : 'transparent'}`,
          background: checked ? '#1DB954' : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', transition: 'all 0.15s',
        }}
      >
        {checked && (
          <svg width="8" height="6" viewBox="0 0 10 8" fill="none">
            <path d="M1 3.5L4 6.5L9 1" stroke="#121212" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        )}
      </div>
    </td>
  )
}

export function AlbumListRow({ album, compact = false, isSelected = false, onToggleSelect, selectionActive = false }) {
  const [imgErr, setImgErr]   = useState(false)
  const [hovered, setHovered] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [syncPhotos] = useSyncPhotos()

  const year    = album.release_date?.split('-')[0] ?? '—'
  const artists = album.artists?.map(a => a.name).join(', ') ?? '—'
  const genres  = album.genres ?? []
  const imgSrc  = syncPhotos && !imgErr && album.image_url ? album.image_url : PLACEHOLDER
  const rowH    = compact ? 44 : 64
  const spotifyHref = spotifyAlbumUrl(album)
  const contextUri = album?.spotify_id ? `spotify:album:${album.spotify_id}` : null

  const playbackToken = async () => (
    hasLocalSpotify()
      ? getLocalSpotifyToken()
      : (await api.getPlayerToken()).access_token
  )

  const handlePlayAlbum = async () => {
    if (!contextUri) return
    setPlaying(true)
    try {
      await playContext(contextUri, playbackToken)
    } catch {
      // Keep the row usable even if playback cannot start.
    } finally {
      setPlaying(false)
    }
  }

  const rowBg = isSelected ? '#2a2010' : hovered ? '#1e1c17' : 'transparent'

  return (
    <tr style={{ background: rowBg, height: rowH, outline: isSelected ? '1px solid #1DB95444' : 'none' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}>

      {/* Checkbox */}
      <CheckCell
        checked={isSelected}
        onChange={() => onToggleSelect?.(album.spotify_id)}
        hovered={hovered || selectionActive}
      />

      {/* Cover */}
      <TD style={{ width: compact ? 44 : 68, padding: '4px 8px' }}>
        <img src={imgSrc} alt={album.name} loading="lazy" onError={() => setImgErr(true)}
          style={{ width: compact ? 36 : 52, height: compact ? 36 : 52,
                   objectFit: 'cover', borderRadius: 3, display: 'block',
                   opacity: isSelected ? 0.75 : 1 }} />
      </TD>

      {/* Title */}
      <TD style={{ maxWidth: 220 }}>
        <div className="font-medium text-sm text-ink truncate" title={album.name}>{album.name}</div>
      </TD>

      {/* Artist */}
      <TD style={{ maxWidth: 180 }} className="hidden sm:table-cell">
        <div className="text-xs text-secondary truncate" title={artists}>{artists}</div>
      </TD>

      {/* Year */}
      <TD align="center" className="hidden md:table-cell">
        <span className="font-mono text-xs text-secondary">{year}</span>
      </TD>

      {/* Genres */}
      {!compact && (
        <TD className="hidden lg:table-cell" style={{ maxWidth: 200 }}>
          <div className="flex flex-wrap gap-1">
            {genres.slice(0, 2).map(g => <span key={g} className="badge">{g}</span>)}
            {!genres.length && <span className="text-muted text-xs">—</span>}
          </div>
        </TD>
      )}

      {/* Tracks */}
      <TD align="center" className="hidden md:table-cell">
        <span className="font-mono text-xs text-muted">{album.total_tracks ?? '—'}</span>
      </TD>

      {/* Type */}
      <TD align="center" className="hidden lg:table-cell">
        {album.album_type && album.album_type !== 'album'
          ? <span className="badge">{album.album_type}</span>
          : <span className="text-muted text-xs">—</span>}
      </TD>

      {/* Popularity */}
      <TD align="right" className="hidden sm:table-cell" style={{ width: 100 }}>
        {album.popularity != null ? (
          <div className="flex items-center gap-2 justify-end">
            <div style={{ flex: 1, height: 4, background: '#333333', borderRadius: 999,
                          overflow: 'hidden', maxWidth: 60 }}>
              <div style={{ width: `${album.popularity}%`, height: '100%',
                            background: `hsl(${album.popularity * 1.2}, 55%, 48%)`, borderRadius: 999 }} />
            </div>
            <span className="font-mono text-[0.6rem] text-muted w-5 text-right">{album.popularity}</span>
          </div>
        ) : <span className="text-muted text-xs">—</span>}
      </TD>

      {/* Label */}
      {!compact && (
        <TD className="hidden xl:table-cell" style={{ maxWidth: 140 }}>
          <span className="text-xs text-muted truncate block" title={album.label ?? ''}>{album.label || '—'}</span>
        </TD>
      )}

      {/* Playback / Spotify link */}
      <TD align="center" style={{ width: 48 }}>
        <div style={{ display: 'flex', gap: 6, justifyContent: 'center', alignItems: 'center' }}>
          {contextUri && (
            <button type="button"
              onClick={(e) => { e.stopPropagation(); void handlePlayAlbum() }}
              disabled={playing}
              title="Play album"
              style={{ opacity: hovered ? 1 : 0.7, transition: 'opacity 0.15s', background: 'none', border: 'none', color: '#1DB954', cursor: 'pointer', fontSize: '0.85rem', padding: 0 }}>
              {playing ? '…' : '▶'}
            </button>
          )}
          {spotifyHref && (
            <a href={spotifyHref} target="_blank" rel="noopener noreferrer"
              className="font-mono text-[0.65rem] text-accent hover:text-accent-2 transition-colors"
              style={{ opacity: hovered ? 1 : 0, transition: 'opacity 0.15s' }} title="Open in Spotify">
              ↗
            </a>
          )}
        </div>
      </TD>
    </tr>
  )
}

export function AlbumTable({ albums, compact = false, loading, selectedIds, onToggleSelect, selectionActive }) {
  return (
    <div style={{ overflowX: 'auto', border: '1px solid #333333', borderRadius: 6 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: 36 }} />
          <col style={{ width: compact ? 44 : 68 }} />
          <col style={{ minWidth: 160 }} />
          <col style={{ width: 160 }} className="hidden sm:table-column" />
          <col style={{ width: 64 }}  className="hidden md:table-column" />
          {!compact && <col style={{ width: 180 }} className="hidden lg:table-column" />}
          <col style={{ width: 64 }}  className="hidden md:table-column" />
          <col style={{ width: 80 }}  className="hidden lg:table-column" />
          <col style={{ width: 110 }} className="hidden sm:table-column" />
          {!compact && <col style={{ width: 140 }} className="hidden xl:table-column" />}
          <col style={{ width: 32 }} />
        </colgroup>
        <thead>
          <tr>
            <TH style={{ padding: '6px 8px', width: 36 }}></TH>
            <TH style={{ padding: '6px 8px' }}></TH>
            <TH>Title</TH>
            <TH className="hidden sm:table-cell">Artist</TH>
            <TH align="center" className="hidden md:table-cell">Year</TH>
            {!compact && <TH className="hidden lg:table-cell">Genres</TH>}
            <TH align="center" className="hidden md:table-cell">Tracks</TH>
            <TH align="center" className="hidden lg:table-cell">Type</TH>
            <TH align="right" className="hidden sm:table-cell">Pop.</TH>
            {!compact && <TH className="hidden xl:table-cell">Label</TH>}
            <TH></TH>
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: 15 }).map((_, i) => (
                <tr key={i} style={{ height: compact ? 44 : 64 }}>
                  <td style={{ borderBottom: '1px solid #181818', width: 36 }} />
                  <td style={{ padding: '4px 8px', borderBottom: '1px solid #181818' }}>
                    <div className="skeleton rounded" style={{ width: compact ? 36 : 52, height: compact ? 36 : 52 }} />
                  </td>
                  <td style={{ borderBottom: '1px solid #181818', padding: '0 12px' }}>
                    <div className="skeleton h-3 rounded w-3/4" />
                  </td>
                  {[...Array(compact ? 4 : 6)].map((_, j) => (
                    <td key={j} style={{ borderBottom: '1px solid #181818' }} />
                  ))}
                </tr>
              ))
            : albums.map(album => (
                <AlbumListRow
                  key={album.id}
                  album={album}
                  compact={compact}
                  isSelected={selectedIds?.has(album.spotify_id)}
                  onToggleSelect={onToggleSelect}
                  selectionActive={selectionActive}
                />
              ))
          }
        </tbody>
      </table>
    </div>
  )
}
