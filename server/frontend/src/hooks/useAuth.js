/**
 * useAuth
 * -------
 * Manages JWT user session AND Spotify link state — two different things.
 *
 *   user             → JWT session from /api/v1/auth/login; gates the app.
 *   spotifyConnected → whether the signed-in user's Spotify account is linked.
 *
 * API calls go through the (same-origin) nginx/Vite proxy — never direct to
 * port 8000. Tokens live in localStorage under `reSpotIt_jwt_session` and every
 * request carries `Authorization: Bearer <token>` automatically (api/client).
 *
 * In local mode there is no account and no server: the on-device library is
 * the whole app, so this short-circuits to "authenticated". Asking a server
 * that may not be running whether you are signed in is how the sibling
 * frontend ended up wiping a stored token on a mode switch.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { api, ApiError } from '../api/client'

export function useAuth(source) {
  const [user, setUser] = useState(null)
  const [authenticated, setAuthenticated] = useState(() => Boolean(source?.isLocal))
  const [displayName,   setDisplayName]   = useState(null)
  // Local mode is usable immediately — no server round-trip to wait for — so
  // start past the splash instead of flashing it on every load.
  const [loading,       setLoading]       = useState(() => !source?.isLocal)
  const [signingIn,     setSigningIn]     = useState(false)
  const popupRef = useRef(null)
  const pollRef  = useRef(null)

  const isLocal   = Boolean(source?.isLocal)
  const serverUrl = source?.serverUrl ?? ''

  const checkSpotifyStatus = useCallback(async () => {
    try {
      const data = await api.spotifyStatus()
      setAuthenticated(Boolean(data.connected))
      setDisplayName(data.display_name ?? null)
      return Boolean(data.connected)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        // Session expired while we were away — fall through to the login gate.
        setUser(null)
        api.clearSession()
      }
      setAuthenticated(false)
      return false
    }
  }, [])

  useEffect(() => {
    if (isLocal) {
      // No server, no sign-in: local mode is always "usable".
      setUser(null)
      setAuthenticated(true)
      setDisplayName(null)
      setLoading(false)
      return
    }

    if (!api.hasSession()) {
      setUser(null)
      setAuthenticated(false)
      setDisplayName(null)
      setLoading(false)
      return
    }

    setLoading(true)
    ;(async () => {
      try {
        // Refresh once on boot, then read the JWT profile through /auth/me.
        await api.refreshTokens()
        const me = await api.me()
        setUser({ id: me.id, email: me.email })
      } catch {
        setUser(null)
        api.clearSession()
      } finally {
        setLoading(false)
      }
    })()
  }, [isLocal, serverUrl])

  // The JWT profile says *who* you are; the Spotify link lives with that
  // account server-side. Fetch it as soon as the session is known, so a
  // returning linked user does not have to press "Sign in with Spotify"
  // again, and an unlinked user can still see the library (phone push).
  useEffect(() => {
    if (isLocal || !user) return
    void checkSpotifyStatus()
  }, [isLocal, user?.id, checkSpotifyStatus])

  // Listen for postMessage from the OAuth popup
  useEffect(() => {
    const handler = async (event) => {
      if (event.data?.type === 'SPOTIFY_AUTH_SUCCESS') {
        clearInterval(pollRef.current)
        popupRef.current?.close()
        popupRef.current = null
        setSigningIn(false)
        await checkSpotifyStatus()
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [checkSpotifyStatus])

  /** JWT login (or register) — both issue tokens with the same payload shape. */
  const signInWithPassword = useCallback(async (email, password, mode = 'login') => {
    if (isLocal) return
    const call = mode === 'register' ? api.register : api.login
    try {
      const body = await call(email.trim().toLowerCase(), password)
      api.saveSession(body)
      api.me().then((me) => setUser({ id: me.id, email: me.email })).catch(() => {
        setUser({ id: body.user?.id ?? '', email: email.trim().toLowerCase() })
      })
      return body
    } catch (e) {
      // 401 (login) and 409 (register) already carry a readable message via
      // parseError — surface them as-is for the form.
      throw e
    }
  }, [isLocal])

  const signIn = useCallback(async () => {
    if (isLocal) return
    setSigningIn(true)
    try {
      const { auth_url } = await api.spotifyLogin()

      const w = 480, h = 700
      const left = Math.round(window.screenX + (window.outerWidth  - w) / 2)
      const top  = Math.round(window.screenY + (window.outerHeight - h) / 2)
      const popup = window.open(
        auth_url,
        'spotify_auth',
        `width=${w},height=${h},left=${left},top=${top},toolbar=no,menubar=no`,
      )
      popupRef.current = popup

      // Fallback poll — in case postMessage doesn't fire
      pollRef.current = setInterval(async () => {
        if (!popup || popup.closed) {
          clearInterval(pollRef.current)
          setSigningIn(false)
          await checkSpotifyStatus()
          return
        }
        const ok = await checkSpotifyStatus()
        if (ok) {
          clearInterval(pollRef.current)
          popup.close()
          popupRef.current = null
          setSigningIn(false)
        }
      }, 1500)
    } catch (e) {
      console.error('Sign-in error:', e)
      setSigningIn(false)
    }
  }, [checkSpotifyStatus, isLocal])

  /** JWT session goes away; the server-side Spotify link stays with the account. */
  const signOut = useCallback(async () => {
    // Network/401 failures don't matter: the local session discard is enough.
    try { await api.logoutJWT?.() } catch { /**/ }
    api.clearSession()
    setUser(null)
    setAuthenticated(false)
    setDisplayName(null)
  }, [isLocal])

  useEffect(() => () => {
    clearInterval(pollRef.current)
    popupRef.current?.close()
  }, [])

  return {
    user, authenticated, displayName, loading, signingIn,
    isSpotifyLinked: authenticated,
    signIn, signInWithPassword, signOut, checkSpotifyStatus,
  }
}
