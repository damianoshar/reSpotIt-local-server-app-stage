/**
 * SelectionToolbar
 * Floating bar at the bottom of the screen when albums are selected.
 */
import { useState } from 'react'
import { api } from '../api/client'
import { describeRemoteError } from '../api/errorCodes'
import { useLocalSpotify } from '../hooks/useLocalSpotify'
import * as localSpotify from '../services/localSpotify'

export function SelectionToolbar({
  selectedIds, onClear, onOpenModal, onToast,
  localMode = false, spotifyLinked = true,
}) {
  const count = selectedIds.size
  const local = useLocalSpotify()
  const localLinked = local.linked
  const [queueStatus, setQueueStatus] = useState(null)
  const [queueing, setQueueing]       = useState(false)

  if (count === 0) return null

  const notify = (msg, ok = true) => {
    if (onToast) onToast(msg, ok)
    else setQueueStatus({ type: ok ? 'success' : 'error', message: msg })
  }

  const handleQueue = async () => {
    setQueueing(true)
    setQueueStatus(null)
    try {
      if (localMode) {
        const res = await localSpotify.queueAlbums([...selectedIds], (done, total) => {
          setQueueStatus({ type: 'working', message: `β³ ${done}/${total || '?'}` })
        })
        const failed = res.failed || 0
        notify(
          failed ? `β“ Queued ${res.queued} tracks (${failed} failed)`
                 : `β“ Queued ${res.queued} tracks`,
          !failed
        )
      } else {
        const res = await api.addToQueue([...selectedIds], (job) => {
          setQueueStatus({ type: 'working', message: `β³ ${job.fetched}/${job.total || '?'}` })
        })
        const failed = res.failed || 0
        notify(
          failed ? `β“ Queued ${res.queued} tracks (${failed} failed)`
                 : `β“ Queued ${res.queued} tracks`,
          !failed
        )
      }
      setQueueStatus(null)
      setTimeout(() => setQueueStatus(null), 8888)
    } catch (e) {
      notify(describeRemoteError(e, 'Queue failed'), false)
      setTimeout(() => setQueueStatus(null), 4000)
    } finally {
      setQueueing(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
      zIndex: 50, display: 'flex', alignItems: 'center', gap: 8,
      background: '#232019', border: '1px solid #3E3E3E',
      borderRadius: 10, padding: '10px 14px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.6), 0 0 0 1px #1DB95422',
      backdropFilter: 'blur(8px)',
      flexWrap: 'wrap', maxWidth: 'calc(100vw - 48px)',
    }}>
      {/* Count badge */}
      <div style={{
        background: '#1DB954', color: '#121212', borderRadius: 5,
        padding: '3px 10px', fontFamily: 'Space Mono, monospace',
        fontSize: '0.72rem', fontWeight: 700, flexShrink: 0,
      }}>
        {count} album{count !== 1 ? 's' : ''}
      </div>

      <div style={{ width: 1, height: 20, background: '#3E3E3E', flexShrink: 0 }} />

      {/* Playlists and the queue are Spotify operations performed by the
          server; in local mode there is nothing to send them to. */}
      {localMode && !localLinked ? (
        <span className="font-mono text-[0.65rem]" style={{ color: '#B3B3B3' }}>
          Connect Spotify on this device to use playlists and the queue
        </span>
      ) : localMode && localLinked ? (
        <>
          <button className="btn btn-ghost btn-sm" onClick={() => onOpenModal('create')}>
            + Create Playlist
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => onOpenModal('add')}>
            Add to Playlist
          </button>
          <button className="btn btn-ghost btn-sm" onClick={handleQueue} disabled={queueing}
                  title="Add to queue">
            {queueing ? '…' : '▶ Add to Queue'}
          </button>
        </>
      ) : !spotifyLinked ? (
        <span className="font-mono text-[0.65rem]" style={{ color: '#B3B3B3' }}>
          Link Spotify to use playlists and the queue
        </span>
      ) : (
        <>
          <button className="btn btn-ghost btn-sm" onClick={() => onOpenModal('create')}>
            + Create Playlist
          </button>

          <button className="btn btn-ghost btn-sm" onClick={() => onOpenModal('add')}>
            β† Add to Playlist
          </button>

          <button
            className="btn btn-ghost btn-sm"
            onClick={handleQueue}
            disabled={queueing}
            title="Add to queue"
          >
            {queueing ? '…' : 'β–¶ Add to Queue'}
          </button>
        </>
      )}

      {/* Status */}
      {queueStatus && (
        <div style={{
          fontFamily: 'Space Mono, monospace', fontSize: '0.65rem',
          color: queueStatus.type === 'success' ? '#1DB954' : '#E22134',
          maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {queueStatus.message}
        </div>
      )}

      <div style={{ flex: 1, minWidth: 4 }} />

      {/* Clear */}
      <button
        onClick={onClear}
        style={{
          background: 'none', border: 'none', color: '#555555',
          cursor: 'pointer', fontSize: '0.8rem', padding: '2px 4px',
          flexShrink: 0,
        }}
        title="Clear selection"
      >
        β• Clear
      </button>
    </div>
  )
}
