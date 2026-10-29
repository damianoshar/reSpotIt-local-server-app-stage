import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  getWebPlaybackState,
  initWebPlayback,
  nextWebPlayback,
  previousWebPlayback,
  seekWebPlayback,
  setWebPlaybackTokenGetter,
  setWebPlaybackVolume,
  subscribeWebPlayback,
  toggleWebPlayback,
} from '../services/webPlayback'
import { getLocalSpotifyToken } from '../services/spotifyAuth'

export function PlayerView({ ds, onToast }) {
  const [playback, setPlayback] = useState(getWebPlaybackState())
  const [volume, setVolume] = useState(getWebPlaybackState().volume)
  const [queue, setQueue] = useState([])
  const localMode = Boolean(ds?.isLocal)

  const getToken = async () => {
    if (localMode) {
      const token = await getLocalSpotifyToken()
      if (!token) throw new Error('Connect Spotify on this device first.')
      return token
    }
    const data = await api.getPlayerToken()
    return data.access_token
  }

  useEffect(() => {
    setWebPlaybackTokenGetter(getToken)
    const unsubscribe = subscribeWebPlayback(setPlayback)
    let cancelled = false
    void initWebPlayback(getToken).catch((e) => {
      if (!cancelled) setPlayback((current) => ({ ...current, error: e?.message || 'Player setup failed' }))
    })
    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [localMode])

  useEffect(() => {
    if (!playback.deviceId) return
    let cancelled = false
    const loadQueue = async () => {
      try {
        const data = localMode
          ? await (async () => {
              const token = await getLocalSpotifyToken()
              const res = await fetch('https://api.spotify.com/v1/me/player/queue', {
                headers: { Authorization: `Bearer ${token}` },
              })
              return res.ok ? res.json() : { queue: [] }
            })()
          : await api.getPlayerQueue()
        if (!cancelled) setQueue(data.queue || [])
      } catch {
        if (!cancelled) setQueue([])
      }
    }
    void loadQueue()
    const timer = window.setInterval(loadQueue, 10000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [playback.deviceId, localMode])

  useEffect(() => {
    setVolume(playback.volume)
  }, [playback.volume])

  const toggle = async () => {
    try { await toggleWebPlayback() } catch (e) { onToast?.(e?.message || 'Playback failed', false) }
  }
  const next = async () => {
    try { await nextWebPlayback() } catch (e) { onToast?.(e?.message || 'Next failed', false) }
  }
  const previous = async () => {
    try { await previousWebPlayback() } catch (e) { onToast?.(e?.message || 'Previous failed', false) }
  }
  const seek = async (value) => {
    try { await seekWebPlayback(value) } catch {}
  }
  const changeVolume = async (value) => {
    const v = Number(value)
    setVolume(v)
    try { await setWebPlaybackVolume(v) } catch {}
  }

  const percent = playback.duration > 0 ? Math.min(100, (playback.position / playback.duration) * 100) : 0

  return (
    <div className="player-tab">
      <h1 className="font-display text-2xl font-semibold mb-5">Player</h1>
      {playback.error && <div className="font-mono text-xs mb-4" style={{ color: '#E22134' }}>{playback.error}</div>}
      {!playback.ready && !playback.error && <div className="font-mono text-xs text-muted mb-4">Connecting to Spotify…</div>}

      <div className="rounded-lg border border-border bg-panel px-5 py-4 mb-4">
        <div className="flex items-center gap-4">
          {playback.track?.image && (
            <img src={playback.track.image} alt="" style={{ width: 88, height: 88, borderRadius: 6, objectFit: 'cover' }} />
          )}
          <div style={{ minWidth: 0 }}>
            <div className="font-display text-xl truncate">{playback.track?.name || 'No active playback'}</div>
            <div className="text-sm text-secondary truncate">{playback.track?.artist || 'Open Spotify or start playback from the library'}</div>
            <div className="font-mono text-[0.65rem] text-muted truncate">{playback.track?.album || ''}</div>
          </div>
        </div>
        <div className="mt-4">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${percent}%` }} />
          </div>
          <div className="flex justify-between font-mono text-[0.6rem] text-muted mt-1">
            <span>{Math.round(playback.position / 1000)}s</span>
            <span>{Math.round(playback.duration / 1000)}s</span>
          </div>
        </div>
        <div className="flex items-center gap-2 mt-4">
          <button className="btn btn-ghost btn-sm" onClick={previous} disabled={!playback.ready}>⏮</button>
          <button className="btn btn-primary btn-sm" onClick={toggle} disabled={!playback.ready}>
            {playback.playing ? 'Pause' : 'Play'}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={next} disabled={!playback.ready}>⏭</button>
          <input type="range" min="0" max={playback.duration || 0} value={playback.position} onChange={(e) => seek(e.target.value)}
                 style={{ flex: 1 }} disabled={!playback.ready} />
          <input type="range" min="0" max="1" step="0.01" value={volume} onChange={(e) => changeVolume(e.target.value)}
                 style={{ width: 90 }} disabled={!playback.ready} />
        </div>
        <div className="font-mono text-[0.6rem] text-muted mt-2">
          Device ID: {playback.deviceId || '—'} {playback.ready ? '· connected' : ''}
        </div>
      </div>

      <section className="settings-section">
        <h3 className="settings-heading">Up next</h3>
        {queue.length === 0 ? (
          <p className="text-sm text-muted">No queued tracks reported by Spotify.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {queue.slice(0, 20).map((item, index) => (
              <div key={`${item.uri}-${index}`} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #242424' }}>
                <span className="font-mono text-[0.6rem] text-muted" style={{ width: 20, textAlign: 'right' }}>{index + 1}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="text-sm text-ink truncate">{item.name}</div>
                  <div className="font-mono text-[0.6rem] text-muted truncate">{(item.artists || []).map((a) => a.name).join(', ')}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}