import { useEffect, useState } from 'react'
import { hasLocalSpotify, loadLocalSpotifyTokens } from '../services/spotifyAuth'

export function useLocalSpotify() {
  const [linked, setLinked] = useState(() => hasLocalSpotify())
  useEffect(() => {
    const update = () => setLinked(hasLocalSpotify())
    window.addEventListener('local-spotify-auth-changed', update)
    window.addEventListener('storage', update)
    const timer = window.setInterval(update, 1000)
    return () => {
      window.removeEventListener('local-spotify-auth-changed', update)
      window.removeEventListener('storage', update)
      window.clearInterval(timer)
    }
  }, [])
  return { linked, tokens: loadLocalSpotifyTokens() }
}