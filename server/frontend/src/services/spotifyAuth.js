const CLIENT_ID = (import.meta.env.VITE_SPOTIFY_CLIENT_ID || '').trim()
const SCOPES = [
  'user-library-read',
  'user-library-modify',
  'user-follow-read',
  'user-follow-modify',
  'user-read-private',
  'user-read-email',
  'playlist-read-private',
  'playlist-read-collaborative',
  'playlist-modify-private',
  'playlist-modify-public',
  'user-modify-playback-state',
  'user-read-playback-state',
  'user-read-currently-playing',
].join(' ')

const TOKEN_KEY = 'reSpotIt_spotify_tokens'
const PKCE_KEY = 'reSpotIt_spotify_pkce'
const PKCE_TTL_MS = 30 * 60 * 1000

function base64Url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
}

function randomString(length) {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return base64Url(bytes)
}

async function sha256Base64Url(value) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return base64Url(new Uint8Array(digest))
}

function redirectUri() {
  const origin = window.location.origin.replace('localhost', '127.0.0.1')
  return `${origin}/callback`
}

export function loadLocalSpotifyTokens() {
  try {
    const raw = localStorage.getItem(TOKEN_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function hasLocalSpotify() {
  return Boolean(loadLocalSpotifyTokens()?.access_token)
}

function storeTokens(tokens) {
  localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens))
  window.dispatchEvent(new Event('local-spotify-auth-changed'))
}

export function clearLocalSpotifyTokens() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(PKCE_KEY)
  window.dispatchEvent(new Event('local-spotify-auth-changed'))
}

export async function startLocalSpotifyAuth() {
  if (!CLIENT_ID) throw new Error('VITE_SPOTIFY_CLIENT_ID is not set.')
  const verifier = randomString(96)
  const challenge = await sha256Base64Url(verifier)
  const state = randomString(24)
  const uri = redirectUri()
  localStorage.setItem(PKCE_KEY, JSON.stringify({
    verifier,
    state,
    redirectUri: uri,
    createdAt: Date.now(),
  }))
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: 'code',
    redirect_uri: uri,
    scope: SCOPES,
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })
  window.location.assign(`https://accounts.spotify.com/authorize?${params.toString()}`)
}

export async function handleLocalSpotifyCallback() {
  if (window.location.pathname !== '/callback') return false
  const params = new URLSearchParams(window.location.search)
  const code = params.get('code')
  const state = params.get('state')
  const error = params.get('error')
  if (error) {
    window.location.replace('/')
    return true
  }
  if (!code || !state) return false

  let pkce = null
  try {
    pkce = JSON.parse(localStorage.getItem(PKCE_KEY) || 'null')
  } catch {
    pkce = null
  }
  if (!pkce || pkce.state !== state || Date.now() - pkce.createdAt > PKCE_TTL_MS) {
    localStorage.removeItem(PKCE_KEY)
    window.location.replace('/')
    return true
  }

  try {
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: pkce.redirectUri,
      client_id: CLIENT_ID,
      code_verifier: pkce.verifier,
    })
    const res = await fetch('https://accounts.spotify.com/api/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
    if (!res.ok) throw new Error(`Spotify token exchange failed (${res.status})`)
    const data = await res.json()
    storeTokens({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: Date.now() + (data.expires_in || 3600) * 1000,
      token_type: data.token_type || 'Bearer',
    })
    localStorage.removeItem(PKCE_KEY)
  } catch (e) {
    console.error(e)
  }
  window.location.replace('/')
  return true
}

export async function refreshLocalSpotifyToken() {
  const tokens = loadLocalSpotifyTokens()
  if (!tokens?.refresh_token) return null
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: tokens.refresh_token,
    client_id: CLIENT_ID,
  })
  const res = await fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) {
    clearLocalSpotifyTokens()
    return null
  }
  const data = await res.json()
  const next = {
    access_token: data.access_token,
    refresh_token: data.refresh_token || tokens.refresh_token,
    expires_at: Date.now() + (data.expires_in || 3600) * 1000,
    token_type: data.token_type || tokens.token_type || 'Bearer',
  }
  storeTokens(next)
  return next.access_token
}

export async function getLocalSpotifyToken() {
  const tokens = loadLocalSpotifyTokens()
  if (!tokens?.access_token) return null
  if (tokens.expires_at && Date.now() > tokens.expires_at - 60000) {
    return refreshLocalSpotifyToken()
  }
  return tokens.access_token
}