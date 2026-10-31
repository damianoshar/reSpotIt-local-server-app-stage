import { useState, useEffect } from 'react'
import { api } from '../api/client'
import { getArtistNames } from '../services/localDatabase'

/**
 * Artist rows for the filter datalist. Local mode derives them from the stored
 * library; remote mode asks the server — the `{id,name}` shape is the same.
 *
 * `sessionKey` ('anon' until a JWT account exists) gates the remote fetch:
 * since per-user scoping the request would 401 before sign-in, and it must
 * re-run when the signed-in account changes.
 */
export function useArtists(source, sessionKey) {
  const [artists, setArtists] = useState([])
  const [loading, setLoading] = useState(false)

  const isLocal = Boolean(source?.isLocal)
  const serverUrl = source?.serverUrl ?? ''
  // Local mode needs to re-read when the library changes; remote mode only when
  // the target server changes.
  const libraryKey = source?.libraryVersion ?? 0
  const sessionEpoch = sessionKey ?? 'anon'

  useEffect(() => {
    if (!isLocal && sessionEpoch === 'anon') { setArtists([]); return }
    setLoading(true)
    const request = isLocal
      ? getArtistNames().then((items) => ({ items }))
      : api.getArtists()

    request
      .then(data => setArtists(data.items ?? []))
      .catch(() => setArtists([]))
      .finally(() => setLoading(false))
  }, [isLocal, serverUrl, libraryKey, sessionEpoch])

  return { artists, loading }
}
