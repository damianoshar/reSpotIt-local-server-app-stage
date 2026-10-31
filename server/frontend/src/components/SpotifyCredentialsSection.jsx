import React, { useEffect, useState } from 'react'

const PREFS_KEY = 'respotit_spotify_creds'

function load() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {} } catch { return {} }
}
function save(v) { try { localStorage.setItem(PREFS_KEY, JSON.stringify(v)) } catch {} }

export function SpotifyCredentialsSection() {
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const v = load()
    setClientId(v.clientId || '')
    setClientSecret(v.clientSecret || '')
  }, [])

  const canSave = clientId.trim().length > 0

  const handleSave = () => {
    if (!canSave) return
    save({ clientId: clientId.trim(), clientSecret: clientSecret.trim() })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div style={{ marginTop: '1.5rem' }}>
      <div style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.65rem',
                    textTransform: 'uppercase', letterSpacing: '0.16em', color: '#B3B3B3',
                    marginBottom: 8 }}>
        Spotify credentials
      </div>
      <input className="form-input" style={{ marginBottom: '0.6rem', width: '100%' }}
             type="text" placeholder="Spotify Client ID (required)"
             value={clientId} onChange={(e) => setClientId(e.target.value)} />
      <input className="form-input" style={{ marginBottom: '1rem', width: '100%' }}
             type="password" placeholder="Spotify Client Secret (optional)"
             value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
      <button className="login-btn" onClick={handleSave} disabled={!canSave}
              style={{ width: '100%' }}>
        {saved ? 'Saved β“' : 'Save'}
      </button>
      <p className="login-note" style={{ marginTop: '0.5rem' }}>
        Stored locally in this browser. A single shared client_id is not permitted (Spotify ToS).
        Note: the local server itself uses server-side credentials via .env.
      </p>
    </div>
  )
}
