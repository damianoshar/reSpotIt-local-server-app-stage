import { useState } from 'react'
import { ApiError } from '../api/client'
import { SpotifyLogo } from './SpotifyLogo'

const GOLD = '#1DB954'

const field = {
  width: '100%', padding: '11px 13px', background: '#121212',
  border: '1px solid #333333', borderRadius: 6, color: '#FFFFFF',
  fontFamily: 'Outfit, sans-serif', fontSize: '0.9rem', outline: 'none',
  boxSizing: 'border-box',
}

export function LoginGate({ onAuthenticate, onForgot }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)

    const mail = email.trim()
    if (!mail || !password) {
      setError('Email and password are required.')
      return
    }
    if (mode === 'register' && password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters.')
      return
    }

    setBusy(true)
    try {
      await onAuthenticate(mail, password, mode)
    } catch (err) {
      const msg = err instanceof ApiError
        ? (err.status === 409
            ? 'An account with that email already exists — sign in instead.'
            : err.status === 401 && mode === 'login'
              ? 'Wrong email or password.'
              : err.message)
        : 'Something went wrong. Try again.'
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  const switchMode = () => {
    setMode(mode === 'login' ? 'register' : 'login')
    setError(null)
  }

  return (
    <div style={{
      minHeight: '100vh', background: '#121212',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem',
    }}>
      <div style={{
        background: '#191414', border: '1px solid #333333', borderRadius: 12,
        padding: '3rem 3.5rem', maxWidth: 420, width: '100%',
        boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                      gap: 10, marginBottom: '2rem' }}>
          <span style={{ color: GOLD, fontSize: '1.8rem' }}>◉</span>
          <span style={{ fontFamily: 'Bodoni Moda, serif', fontSize: '1.8rem',
                         fontWeight: 600, color: '#FFFFFF' }}>reSpotIt</span>
        </div>

        <h2 style={{ fontFamily: 'Bodoni Moda, serif', fontSize: '1.35rem',
                     color: '#FFFFFF', marginBottom: '0.4rem', fontWeight: 600 }}>
          {mode === 'login' ? 'Sign in to your library' : 'Create an account'}
        </h2>
        <p style={{ color: '#B3B3B3', fontSize: '0.855rem', lineHeight: 1.6, marginBottom: '1.75rem' }}>
          {mode === 'login'
            ? 'Your albums, playlists and queue are scoped to this account.'
            : 'A new library starts empty. Connect Spotify after signing in.'}
        </p>

        <form onSubmit={submit} noValidate>
          <label style={{ display: 'block', fontSize: '0.72rem', color: '#B3B3B3',
                          marginBottom: 5, fontFamily: 'Space Mono, monospace' }}>
            EMAIL
          </label>
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            autoFocus autoComplete="email"
            placeholder="you@example.com" style={{ ...field, marginBottom: '1rem' }}
          />

          <label style={{ display: 'block', fontSize: '0.72rem', color: '#B3B3B3',
                          marginBottom: 5, fontFamily: 'Space Mono, monospace' }}>
            PASSWORD
          </label>
          <input
            type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            placeholder="••••••••" style={{ ...field, marginBottom: '1rem' }}
          />

          {mode === 'register' && (<>
            <label style={{ display: 'block', fontSize: '0.72rem', color: '#B3B3B3',
                            marginBottom: 5, fontFamily: 'Space Mono, monospace' }}>
              CONFIRM PASSWORD
            </label>
            <input
              type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              placeholder="••••••••" style={{ ...field, marginBottom: '1rem' }}
            />
          </>)}

          {error && (
            <div style={{
              background: 'rgba(196,74,74,0.08)', border: '1px solid #E2213466',
              borderRadius: 6, padding: '10px 13px', marginBottom: '1rem',
              color: '#e08a8a', fontSize: '0.83rem', lineHeight: 1.5,
            }}>
              {error}
            </div>
          )}

          <button type="submit" disabled={busy} className="btn"
            style={{
              width: '100%', padding: '13px 24px', justifyContent: 'center',
              background: busy ? '#24211b' : GOLD, color: '#1a1508',
              border: 'none', fontWeight: 700,
              boxShadow: busy ? 'none' : `0 4px 20px ${GOLD}44`,
            }}>
            <SpotifyLogo size={18} color="#1a1508" />
            {busy
              ? (mode === 'login' ? 'Signing in…' : 'Creating account…')
              : (mode === 'login' ? 'Sign in' : 'Create account')}
          </button>
        </form>

        <button onClick={switchMode} disabled={busy}
          style={{
            background: 'none', border: 'none', cursor: 'pointer', marginTop: '1.25rem',
            color: '#B3B3B3', fontSize: '0.82rem', fontFamily: 'Outfit, sans-serif',
            textDecoration: mode === 'login' ? 'underline' : 'none',
          }}>
          {mode === 'login' ? 'Create a new account' : 'Already have an account? Sign in'}
        </button>

        {mode === 'login' && (
          <p style={{ marginTop: '1.25rem', color: '#555555', fontSize: '0.72rem', lineHeight: 1.5 }}>
            Spotify linking happens after sign-in. Requests are scoped per user.
          </p>
        )}
      </div>
    </div>
  )
}
